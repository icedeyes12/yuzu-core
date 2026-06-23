# FILE: app/llm_client.py
# DESCRIPTION: AI response generation + shared Chutes HTTP helper.
#              Consolidates the three near-identical raw-Chutes call sites
#              previously duplicated across app.py.

from __future__ import annotations

import asyncio
import time
from typing import Any, Iterable, AsyncIterator

import httpx

from app.db import Database
from app.logging_config import get_logger
from app.prompts import build_messages
from app.providers import get_ai_manager
from app.providers.base import _rate_limit_provider
from app.tools import multimodal_tools
from app.tools.registry import get_tool_definitions
from app.visual_context import (
    consume_visual_context,
    has_visual_reference,
)

log = get_logger(__name__)

CHUTES_URL = "https://llm.chutes.ai/v1/chat/completions"
CHUTES_MODEL = "google/gemma-4-31B-turbo-TEE"  # Default model for chutes_chat
_DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "HTTP-Referer": "https://github.com/icedeyes12/yuzu-companion",
}


# ---------------------------------------------------------------------------
# Shared Chutes HTTP helper (replaces three duplicated call sites)
# ---------------------------------------------------------------------------


async def chutes_chat(
    prompt: str,
    model: str = CHUTES_MODEL,
    *,
    system: str | None = None,
    title: str = "chutes_chat",
    api_key: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    timeout: float = 90.0,
    fallback_models: Iterable[str] = (),
    max_429_retries: int = 3,
    backoff_base: float = 2.0,
    source: str = "helper",
) -> str | None:
    """POST a single-turn prompt to the Chutes API. Try *fallback_models* on failure.

    Returns the assistant text or None.
    """
    if not api_key:
        log.warning("chutes_chat: No API key provided - call will return None")
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

    last_error: str | None = None
    async with httpx.AsyncClient() as client:
        for candidate in (model, *fallback_models):
            for retry in range(max_429_retries):
                try:
                    async with _rate_limit_provider("chutes", candidate, source):
                        response = await client.post(
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
                except httpx.RequestError as e:
                    last_error = f"RequestError: {e}"
                    log.warning("chutes call failed for %s: %s", candidate, e)
                    continue

                if response.status_code == 200:
                    try:
                        return response.json()["choices"][0]["message"][
                            "content"
                        ].strip()
                    except (KeyError, IndexError, ValueError) as e:
                        last_error = f"ParseError: {e}"
                        log.warning(
                            "chutes response parse failed for %s: %s", candidate, e
                        )
                        continue

                if response.status_code == 429 and retry < max_429_retries - 1:
                    last_error = "HTTP 429 (rate limited)"
                    log.warning("chutes %s -> HTTP 429, retrying...", candidate)
                    await asyncio.sleep(backoff_base**retry)
                    continue

                last_error = f"HTTP {response.status_code}"
                log.warning(
                    "chutes %s -> HTTP %s: %s",
                    candidate,
                    response.status_code,
                    response.text[:200],
                )

    # Log final failure reason when all retries exhausted
    if last_error:
        log.warning("chutes_chat: All retries failed. Last error: %s", last_error)
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
    messages: list[dict[str, Any]],
    user_message: str,
    session_id: str | None,
    is_tool_loop: bool = False,
) -> None:
    if not (session_id and has_visual_reference(user_message)):
        return
    prev_b64, prev_mime = consume_visual_context(session_id, is_tool_loop=is_tool_loop)
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


async def _send_to_provider(
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    *,
    image_context: list[dict[str, Any]] | None,
    source: str = "chat",
) -> tuple[str | None, dict[str, Any] | None]:
    """Single LLM dispatch with timing log. Returns (text, raw_response)."""
    ai_manager = await get_ai_manager()
    schemas = _unique_tool_schemas()

    if image_context and provider in ai_manager.providers:
        # Capability check: prefer native vision model if available
        if multimodal_tools.is_vision_model(model, provider):
            log.info(
                "2nd-pass: %s/%s is vision-capable, reusing for image synthesis",
                provider,
                model,
            )
        else:
            # Current model lacks vision support, use fallback
            v_provider, v_model = multimodal_tools.get_best_vision_provider()
            if v_provider and v_model:
                log.info(
                    "2nd-pass vision fallback: %s/%s (non-vision) -> %s/%s",
                    provider,
                    model,
                    v_provider,
                    v_model,
                )
                provider, model = v_provider, v_model
                schemas = []  # vision models don't accept tool schemas

    started = time.time()
    raw_response: dict[str, Any] | None = None
    try:
        raw_response = await ai_manager.send_message_raw(
            provider, model, messages, source=source, timeout=180, tools=schemas
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


async def generate_ai_response(
    profile: dict[str, Any],
    user_message: str,
    interface: str = "terminal",
    session_id: str | None = None,
    image_content_for_context: list[dict[str, Any]] | None = None,
    ephemeral_context: list[dict[str, str]] | None = None,
    is_tool_loop: bool = False,
    user_id: str | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    """Single (text, raw_response) AI generation pass.

    raw_response is the full API response dict, used for tool-call parsing.
    Legacy /command detection lives in the orchestrator.

    NOTE: build_messages() fetches full history including the just-persisted
    user message. We do NOT re-append user_message to avoid duplication.

    ephemeral_context: In-memory context (assistant tool calls + results)
    not yet persisted to DB. Stitched after build_messages() for synthesis.
    """
    if session_id is None:
        session_id = (await Database.get_active_session_async(user_id))["id"]

    provider, model = _resolve_provider(profile, None, None)

    # Validation: If images are present but model is not vision-capable, abort
    if multimodal_tools.has_images(
        user_message
    ) and not multimodal_tools.is_vision_model(model):
        error_msg = "[System] Current model does not support vision. Please reconfigure your active model to a multimodal one first~ :3"
        await Database.add_message_async("system", error_msg, session_id=session_id, user_id=user_id)
        return error_msg, None

    # build_messages() fetches history which ALREADY contains the user message
    # (persisted by orchestrator before calling this function)
    messages = await build_messages(
        profile, session_id, interface, user_message, user_id, include_image_paths=True
    )

    # Stitch in-memory context (assistant tool calls + results) not yet in DB
    if ephemeral_context:
        messages.extend(ephemeral_context)

    # DO NOT re-append user_message here - it's already in history
    # The history from build_messages() is authoritative

    # Apply the Interceptor Hook
    messages = multimodal_tools.inject_vision_context(messages, model)

    if image_content_for_context:
        # 2nd pass synthesis often has image context from tool results
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Here's the generated image for your reference.",
                    },
                    *image_content_for_context,
                ],
            }
        )

    _inject_persistent_visual(
        messages, user_message, session_id, is_tool_loop=is_tool_loop
    )

    text, raw = await _send_to_provider(
        provider,
        model,
        messages,
        image_context=image_content_for_context,
        source="chat",
    )
    return text, raw


async def _stream_from_provider(
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    *,
    image_context: list[dict[str, Any]] | None,
    source: str = "chat",
) -> AsyncIterator[str]:
    """Yield raw chunks from the provider's streaming API."""
    ai_manager = await get_ai_manager()

    if image_context and provider in ai_manager.providers:
        # Capability check: prefer native vision model if available
        if multimodal_tools.is_vision_model(model, provider):
            log.info(
                "streaming 2nd-pass: %s/%s is vision-capable, reusing for image synthesis",
                provider,
                model,
            )
        else:
            # Current model lacks vision support, use fallback
            v_provider, v_model = multimodal_tools.get_best_vision_provider()
            if v_provider and v_model:
                log.info(
                    "streaming 2nd-pass vision fallback: %s/%s (non-vision) -> %s/%s",
                    provider,
                    model,
                    v_provider,
                    v_model,
                )
                provider, model = v_provider, v_model

    received = 0
    try:
        async for chunk in ai_manager.send_message_streaming(
            provider, model, messages, source=source, timeout=180
        ):
            if chunk:
                received += len(chunk)
                yield chunk
    except asyncio.CancelledError:
        # Stream was cancelled (user clicked Stop) - propagate up
        log.info(
            "stream cancelled by user at llm_client layer (%d chars received)", received
        )
        raise
    except Exception as e:  # noqa: BLE001
        log.error("streaming exception (%s/%s): %s", provider, model, e)
        return


async def generate_ai_response_streaming(
    profile: dict[str, Any],
    user_message: str,
    interface: str = "terminal",
    session_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    image_content_for_context: list[dict[str, Any]] | None = None,
    ephemeral_context: list[dict[str, str]] | None = None,
    is_tool_loop: bool = False,
    user_id: str | None = None,
) -> AsyncIterator[str]:
    """Stream a response from the configured provider chunk by chunk.

    Performs the same context assembly and vision routing as the
    non-streaming variant, then dispatches via the provider's streaming
    API. Yields raw provider chunks; the orchestrator is responsible for
    filtering /command preambles and post-processing.

    NOTE: build_messages() fetches full history including the just-persisted
    user message. We do NOT re-append user_message to avoid duplication.
    """
    if session_id is None:
        session_id = (await Database.get_active_session_async(user_id))["id"]

    resolved_provider, resolved_model = _resolve_provider(profile, provider, model)

    # Validation: If images are present but model is not vision-capable, abort
    if multimodal_tools.has_images(
        user_message
    ) and not multimodal_tools.is_vision_model(resolved_model):
        error_msg = "[System] Current model does not support vision. Please reconfigure your active model to a multimodal one first~ :3"
        await Database.add_message_async("system", error_msg, session_id=session_id, user_id=user_id)
        yield error_msg
        return

    # build_messages() fetches history which ALREADY contains the user message
    # (persisted by orchestrator before calling this function)
    messages = await build_messages(
        profile, session_id, interface, user_message, user_id, include_image_paths=True
    )

    # Stitch in-memory context (assistant tool calls + results) not yet in DB
    if ephemeral_context:
        messages.extend(ephemeral_context)

    # DO NOT re-append user_message here - it's already in history
    # The history from build_messages() is authoritative

    # Apply the Interceptor Hook
    messages = multimodal_tools.inject_vision_context(messages, resolved_model)

    if image_content_for_context:
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Here's the generated image for your reference.",
                    },
                    *image_content_for_context,
                ],
            }
        )

    _inject_persistent_visual(
        messages, user_message, session_id, is_tool_loop=is_tool_loop
    )

    async for chunk in _stream_from_provider(
        resolved_provider,
        resolved_model,
        messages,
        image_context=image_content_for_context,
        source="chat",
    ):
        yield chunk
