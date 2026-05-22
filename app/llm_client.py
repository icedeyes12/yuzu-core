# FILE: app/llm_client.py
# DESCRIPTION: AI response generation + shared Chutes HTTP helper.
#              Consolidates the three near-identical raw-Chutes call sites
#              previously duplicated across app.py.

from __future__ import annotations

import time
from typing import Any, Iterable, Iterator

import requests

from app.database import Database
from app.logging_config import get_logger
from app.prompts import build_messages
from app.providers import get_ai_manager
from app.tools import multimodal_tools
from app.tools.registry import get_tool_definitions
from app.visual_context import (
    consume_visual_context,
    has_visual_reference,
)

log = get_logger(__name__)

CHUTES_URL = "https://llm.chutes.ai/v1/chat/completions"
_DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "HTTP-Referer": "https://github.com/icedeyes12/yuzu-companion",
}


# ---------------------------------------------------------------------------
# Shared Chutes HTTP helper (replaces three duplicated call sites)
# ---------------------------------------------------------------------------


def chutes_chat(
    prompt: str,
    *,
    api_key: str,
    model: str,
    system: str | None = None,
    title: str = "Yuzu",
    temperature: float = 0.3,
    max_tokens: int = 1000,
    timeout: int = 60,
    fallback_models: Iterable[str] = (),
) -> str | None:
    """POST a single-turn prompt to the Chutes API. Try *fallback_models* on failure.

    Returns the assistant text or None.
    """
    if not api_key:
        return None

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    headers = {
        **_DEFAULT_HEADERS,
        "X-Title": title,
        "Authorization": f"Bearer {api_key}",
    }

    for candidate in (model, *fallback_models):
        try:
            response = requests.post(
                CHUTES_URL,
                headers=headers,
                json={
                    "model": candidate,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": False,
                },
                timeout=timeout,
            )
        except requests.RequestException as e:
            log.warning("chutes call failed for %s: %s", candidate, e)
            continue

        if response.status_code == 200:
            try:
                return response.json()["choices"][0]["message"]["content"].strip()
            except (KeyError, IndexError, ValueError) as e:
                log.warning("chutes response parse failed for %s: %s", candidate, e)
                continue

        log.warning(
            "chutes %s -> HTTP %s: %s",
            candidate,
            response.status_code,
            response.text[:200],
        )

    return None


# ---------------------------------------------------------------------------
# Vision context injection
# ---------------------------------------------------------------------------


def _apply_vision_routing(
    messages: list[dict[str, Any]],
    user_message: str,
    provider: str,
    model: str,
    image_content_for_context: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], str, str]:
    """Switch to vision provider/model when needed and rewrite the last user msg."""
    # DEPRECATED: Automatic vision model switching is removed in favor of manual configuration and validation.
    return messages, provider, model


def _inject_persistent_visual(
    messages: list[dict[str, Any]], user_message: str, session_id: int | None
) -> None:
    if not (session_id and has_visual_reference(user_message)):
        return
    prev_b64, prev_mime = consume_visual_context(session_id)
    if not (prev_b64 and prev_mime):
        return
    messages.append(
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "[Previous image context re-attached for comparison]",
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{prev_mime};base64,{prev_b64}"},
                },
            ],
        }
    )
    log.info("re-injected persistent visual context")


def _unique_tool_schemas() -> list[dict[str, Any]]:
    seen: set[str] = set()
    schemas: list[dict[str, Any]] = []
    for tool in get_tool_definitions():
        schema = tool.to_llm_schema()
        name = schema.get("function", {}).get("name", "")
        if name and name not in seen:
            seen.add(name)
            schemas.append(schema)
    return schemas


# ---------------------------------------------------------------------------
# Direct /imagine handling (used by both response variants)
# ---------------------------------------------------------------------------

# REMOVED: _handle_imagine_command was a duplicate image-generation path
# that bypassed the tool registry. All /imagine handling now goes through
# the orchestrator -> detect_command -> execute_command -> execute_tool.


# ---------------------------------------------------------------------------
# Response generation
# ---------------------------------------------------------------------------


def _resolve_provider(
    profile: dict[str, Any], provider: str | None, model: str | None
) -> tuple[str, str]:
    config = profile.get("providers_config") or {}
    return (
        provider or config.get("preferred_provider", "ollama"),
        model or config.get("preferred_model", "glm-4.6:cloud"),
    )


def _send_to_provider(
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    *,
    image_context: list[dict[str, Any]] | None,
) -> tuple[str | None, dict[str, Any] | None]:
    """Single LLM dispatch with timing log. Returns (text, raw_response)."""
    ai_manager = get_ai_manager()
    schemas = _unique_tool_schemas()

    if image_context and provider in ai_manager.providers:
        v_provider, v_model = multimodal_tools.get_best_vision_provider()
        if v_provider and v_model:
            log.info("2nd-pass vision: %s/%s", v_provider, v_model)
            provider, model = v_provider, v_model
            schemas = []  # vision models don't accept tool schemas

    started = time.time()
    raw_response: dict[str, Any] | None = None
    try:
        raw_response = ai_manager.send_message_raw(
            provider, model, messages, timeout=180, tools=schemas
        )
    except Exception as e:  # noqa: BLE001
        log.error("send_message exception (%s/%s): %s", provider, model, e)
        return None, None

    duration = time.time() - started
    if raw_response is None:
        log.warning("chat %s/%s returned empty (%.1fs)", provider, model, duration)
        return None, None

    # Extract text content from the raw response
    try:
        text = raw_response["choices"][0]["message"].get("content") or ""
        text = text.strip()
    except (KeyError, IndexError):
        text = ""

    if text:
        log.info(
            "chat %s/%s | tools=%d | %.1fs ok",
            provider,
            model,
            len(schemas),
            duration,
        )
        return text, raw_response

    log.warning("chat %s/%s returned empty (%.1fs)", provider, model, duration)
    return text, raw_response


def generate_ai_response(
    profile: dict[str, Any],
    user_message: str,
    interface: str = "terminal",
    session_id: int | None = None,
    image_content_for_context: list[dict[str, Any]] | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    """Single (text, raw_response) AI generation pass.

    raw_response is the full API response dict, used for tool-call parsing.
    Legacy /command detection lives in the orchestrator.
    """
    if session_id is None:
        session_id = Database.get_active_session()["id"]

    provider, model = _resolve_provider(profile, None, None)
    
    # Validation: If images are present but model is not vision-capable, abort
    if multimodal_tools.has_images(user_message) and not multimodal_tools.is_vision_model(model):
        error_msg = "[System] Current model does not support vision. Please reconfigure your active model to a multimodal one first~ :3"
        Database.add_message("system", error_msg, session_id=session_id)
        return error_msg, None

    messages = build_messages(profile, session_id, interface, user_message, include_image_paths=True)
    if user_message and user_message.strip():
        # Note: image_paths will be populated by orchestrator and available in history if needed,
        # but for the current message we might need to handle it if build_messages doesn't.
        # However, build_messages typically handles history. 
        # For the CURRENT turn's message:
        cached_images = []
        try:
            from app.orchestrator import _cache_images_from_message
            cached_images = _cache_images_from_message(user_message)
        except ImportError:
            pass
            
        messages.append({
            "role": "user", 
            "content": user_message,
            "image_paths": cached_images
        })

    # Apply the Interceptor Hook
    messages = multimodal_tools.inject_vision_context(messages, model)
    
    if image_content_for_context:
        # 2nd pass synthesis often has image context from tool results
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": "Here's the generated image for your reference."},
                *image_content_for_context
            ]
        })

    _inject_persistent_visual(messages, user_message, session_id)

    text, raw = _send_to_provider(
        provider, model, messages, image_context=image_content_for_context
    )
    return text, raw


def _stream_from_provider(
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    *,
    image_context: list[dict[str, Any]] | None,
) -> Iterator[str]:
    """Yield raw chunks from the provider's streaming API."""
    ai_manager = get_ai_manager()

    if image_context and provider in ai_manager.providers:
        v_provider, v_model = multimodal_tools.get_best_vision_provider()
        if v_provider and v_model:
            log.info("streaming 2nd-pass vision: %s/%s", v_provider, v_model)
            provider, model = v_provider, v_model

    started = time.time()
    received = 0
    try:
        for chunk in ai_manager.send_message_streaming(
            provider, model, messages, timeout=180
        ):
            if chunk:
                received += len(chunk)
                yield chunk
    except Exception as e:  # noqa: BLE001
        log.error("streaming exception (%s/%s): %s", provider, model, e)
        return

    duration = time.time() - started
    log.info(
        "chat (stream) %s/%s | chars=%d | %.1fs",
        provider,
        model,
        received,
        duration,
    )


def generate_ai_response_streaming(
    profile: dict[str, Any],
    user_message: str,
    interface: str = "terminal",
    session_id: int | None = None,
    provider: str | None = None,
    model: str | None = None,
    image_content_for_context: list[dict[str, Any]] | None = None,
) -> Iterator[str]:
    """Stream a response from the configured provider chunk by chunk.

    Performs the same context assembly and vision routing as the
    non-streaming variant, then dispatches via the provider's streaming
    API. Yields raw provider chunks; the orchestrator is responsible for
    filtering /command preambles and post-processing.
    """
    if session_id is None:
        session_id = Database.get_active_session()["id"]

    resolved_provider, resolved_model = _resolve_provider(profile, provider, model)
    
    # Validation: If images are present but model is not vision-capable, abort
    if multimodal_tools.has_images(user_message) and not multimodal_tools.is_vision_model(resolved_model):
        error_msg = "[System] Current model does not support vision. Please reconfigure your active model to a multimodal one first~ :3"
        Database.add_message("system", error_msg, session_id=session_id)
        yield error_msg
        return

    messages = build_messages(profile, session_id, interface, user_message, include_image_paths=True)
    if user_message and user_message.strip():
        cached_images = []
        try:
            from app.orchestrator import _cache_images_from_message
            cached_images = _cache_images_from_message(user_message)
        except ImportError:
            pass
            
        messages.append({
            "role": "user", 
            "content": user_message,
            "image_paths": cached_images
        })

    # Apply the Interceptor Hook
    messages = multimodal_tools.inject_vision_context(messages, resolved_model)
    
    if image_content_for_context:
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": "Here's the generated image for your reference."},
                *image_content_for_context
            ]
        })

    _inject_persistent_visual(messages, user_message, session_id)

    yield from _stream_from_provider(
        resolved_provider,
        resolved_model,
        messages,
        image_context=image_content_for_context,
    )
