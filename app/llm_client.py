"""AI response generation + shared Chutes HTTP helper."""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncGenerator, AsyncIterator

import httpx

from app.db import Database
from app.logging_config import get_logger
from app.prompts import build_messages
from app.providers import get_ai_manager
from app.providers.base import _rate_limit_provider
from app.tools.schemas import StreamToolEvent
from app.tools.registry import get_tool_schemas

log = get_logger(__name__)

CHUTES_URL = "https://llm.chutes.ai/v1/chat/completions"
CHUTES_MODEL = "google/gemma-4-31B-turbo-TEE"  # Default model for chutes_chat
_DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "HTTP-Referer": "https://github.com/icedeyes12/yuzu-companion",
}


# Shared Chutes HTTP helper


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


# Vision context injection


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


def _unique_tool_schemas(**kwargs) -> list[dict[str, Any]]:
    """Get deduplicated tool schemas for LLM requests.

    Delegates to the canonical registry function ``get_tool_schemas()``.
    """
    return get_tool_schemas(**kwargs)


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
    source: str = "chat",
    suppress_tools: bool = False,
) -> tuple[str | None, dict[str, Any] | None]:
    """Single LLM dispatch with timing log. Returns (text, raw_response)."""
    ai_manager = await get_ai_manager()
    schemas = _unique_tool_schemas() if not suppress_tools else []

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
    ephemeral_context: list[dict[str, str]] | None = None,
    is_tool_loop: bool = False,
    suppress_tools: bool = False,
    user_id: str | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    """Single (text, raw_response) AI generation pass.

    raw_response is the full API response dict, used for tool-call parsing.
    ephemeral_context: In-memory context (assistant tool calls + results)
    not yet persisted to DB. Stitched after build_messages() for synthesis.
    suppress_tools: If True, strip tool definitions from provider call and
    remove tool docs from system prompt. Used for synthesis/final passes to
    prevent the model from re-invoking tools.
    """
    if session_id is None:
        session_id = (await Database.get_active_session(user_id))["id"]

    provider, model = _resolve_provider(profile, None, None)

    # FC9-C: Check if provider supports native FC for prompt construction
    ai_manager = await get_ai_manager()
    provider_supports_fc = ai_manager.provider_supports_tools(provider)

    messages = await build_messages(
        profile,
        session_id,
        interface,
        user_message,
        user_id,
        include_image_paths=True,
        suppress_tools=suppress_tools,
        provider_supports_fc=provider_supports_fc,
    )

    if ephemeral_context:
        messages.extend(ephemeral_context)

    text, raw = await _send_to_provider(
        provider,
        model,
        messages,
        source="chat",
        suppress_tools=suppress_tools,
    )
    return text, raw


async def _stream_from_provider(
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    *,
    source: str = "chat",
    suppress_tools: bool = False,
) -> AsyncGenerator[str | StreamToolEvent, None]:
    """Yield raw chunks from the provider's streaming API."""
    ai_manager = await get_ai_manager()

    # Generate tool schemas unless suppressed
    tools = [] if suppress_tools else _unique_tool_schemas()

    received = 0
    try:
        async for chunk in ai_manager.send_message_streaming(
            provider,
            model,
            messages,
            source=source,
            timeout=180,
            suppress_tools=suppress_tools,
            tools=tools,
        ):
            if chunk:
                received += len(chunk) if isinstance(chunk, str) else 0
                yield chunk
    except asyncio.CancelledError:
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
    ephemeral_context: list[dict[str, str]] | None = None,
    is_tool_loop: bool = False,
    suppress_tools: bool = False,
    user_id: str | None = None,
) -> AsyncGenerator[str | StreamToolEvent, None]:
    """Stream a response from the configured provider chunk by chunk.

    Yields either plain text chunks (str) or StreamToolEvent objects
    when the provider emits tool calls in streaming mode.

    suppress_tools: If True, strip tool definitions from provider call and
    remove tool docs from system prompt. Used for synthesis/final passes to
    prevent the model from re-invoking tools.
    """
    if session_id is None:
        session_id = (await Database.get_active_session(user_id))["id"]

    resolved_provider, resolved_model = _resolve_provider(profile, provider, model)

    # FC9-C: Check if provider supports native FC for prompt construction
    ai_manager = await get_ai_manager()
    provider_supports_fc = ai_manager.provider_supports_tools(resolved_provider)

    messages = await build_messages(
        profile,
        session_id,
        interface,
        user_message,
        user_id,
        include_image_paths=True,
        suppress_tools=suppress_tools,
        provider_supports_fc=provider_supports_fc,
    )

    if ephemeral_context:
        messages.extend(ephemeral_context)

    async for chunk in _stream_from_provider(
        resolved_provider,
        resolved_model,
        messages,
        source="chat",
        suppress_tools=suppress_tools,
    ):
        yield chunk
