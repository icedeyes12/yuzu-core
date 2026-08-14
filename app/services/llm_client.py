"""(｡•̀ᴗ-)✧"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from typing import Any

from app.core.capabilities import omit_images, request_needs_vision
from app.core.llm_context import LLMContext
from app.core.logging_config import get_logger
from app.db import Database
from app.providers import get_ai_manager
from app.providers.openai_protocol import validate_chat_completion_response
from app.services.prompt_service import build_messages
from app.tools.registry import get_tool_schemas
from app.tools.schemas import StreamToolEvent

log = get_logger(__name__)


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


async def _send_to_provider(
    ctx: LLMContext,
    messages: list[dict[str, Any]],
    *,
    source: str = "chat",
) -> tuple[str | None, dict[str, Any] | None]:
    """Single LLM dispatch with timing log. Returns (text, raw_response)."""
    _ = ctx.require_configured()
    ai_manager = await get_ai_manager()
    model_info = ai_manager.get_model_info(ctx.provider or "", ctx.model or "")
    schemas = (
        _unique_tool_schemas()
        if model_info is None or model_info.capabilities.function_call != "unsupported"
        else []
    )
    if (
        model_info
        and model_info.capabilities.vision == "unsupported"
        and request_needs_vision(messages)
    ):
        messages = omit_images(messages)

    # Phase 1: structured payload audit log (non-stream path)
    if any(
        isinstance(m.get("content"), list) and m.get("role") == "system"
        for m in messages
    ):
        sys_count = sum(1 for m in messages if m.get("role") == "system")
        log.info(
            "[LLMClient] structured payload: %d system message(s), %d total messages, params=%s",
            sys_count,
            len(messages),
            sorted(ctx.parameters.keys()),
        )

    started = time.time()
    raw_response: dict[str, Any] | None = None
    try:
        raw_response = await ai_manager.send_message_raw(
            ctx, messages, source=source, timeout=180, tools=schemas, **ctx.parameters
        )
    except Exception as e:  # noqa: BLE001
        log.error("send_message exception (%s/%s): %s", ctx.provider, ctx.model, e)
        return None, None

    duration = time.time() - started
    if raw_response is None:
        log.warning(
            "chat %s/%s returned empty (%.1fs)", ctx.provider, ctx.model, duration
        )
        return None, None

    response_errors, response_warnings = validate_chat_completion_response(raw_response)
    for warning in response_warnings:
        log.warning("[LLMClient] invalid tool response warning: %s", warning)
    if response_errors:
        log.error("[LLMClient] invalid Chat Completions response: %s", response_errors)
        return None, None

    try:
        text = raw_response["choices"][0]["message"].get("content") or ""
        text = text.strip()
    except (KeyError, IndexError):
        text = ""

    if text:
        log.info(
            "chat %s/%s | tools=%d | %.1fs ok",
            ctx.provider,
            ctx.model,
            len(schemas),
            duration,
        )
        return text, raw_response

    log.warning("chat %s/%s returned empty (%.1fs)", ctx.provider, ctx.model, duration)
    return text, raw_response


async def generate_ai_response(
    profile: dict[str, Any],
    user_message: str,
    interface: str = "terminal",
    session_id: str | None = None,
    *,
    user_id: str,
) -> tuple[str | None, dict[str, Any] | None]:
    """Single (text, raw_response) AI generation pass.

    raw_response is the full API response dict, used for tool-call parsing.
    """
    if session_id is None:
        session_id = (await Database.get_active_session(user_id))["id"]

    assert session_id is not None

    ctx = LLMContext.from_profile(profile).require_configured()
    assert ctx.provider is not None and ctx.model is not None
    ctx.chat_session_id = session_id

    messages = await build_messages(
        profile,
        session_id,
        interface,
        user_message,
        user_id,
    )

    text, raw = await _send_to_provider(
        ctx,
        messages,
        source="chat",
    )
    return text, raw


async def _stream_from_provider(
    ctx: LLMContext,
    messages: list[dict[str, Any]],
    *,
    source: str = "chat",
) -> AsyncGenerator[str | StreamToolEvent, None]:
    """Yield raw chunks from the provider's streaming API."""
    _ = ctx.require_configured()
    ai_manager = await get_ai_manager()

    # Generate tool schemas
    model_info = ai_manager.get_model_info(ctx.provider or "", ctx.model or "")
    tools = (
        _unique_tool_schemas()
        if model_info is None or model_info.capabilities.function_call != "unsupported"
        else []
    )
    if (
        model_info
        and model_info.capabilities.vision == "unsupported"
        and request_needs_vision(messages)
    ):
        messages = omit_images(messages)

    # Phase 1: structured payload audit log (stream path)
    if any(
        isinstance(m.get("content"), list) and m.get("role") == "system"
        for m in messages
    ):
        sys_count = sum(1 for m in messages if m.get("role") == "system")
        log.info(
            "[LLMClient] structured payload: %d system message(s), %d total messages, params=%s",
            sys_count,
            len(messages),
            sorted(ctx.parameters.keys()),
        )

    received = 0
    try:
        async for chunk in ai_manager.send_message_streaming(
            ctx,
            messages,
            source=source,
            timeout=180,
            tools=tools,
            **ctx.parameters,
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
        log.error("streaming exception (%s/%s): %s", ctx.provider, ctx.model, e)
        return


async def generate_ai_response_streaming(
    profile: dict[str, Any],
    user_message: str,
    interface: str = "terminal",
    session_id: str | None = None,
    *,
    user_id: str,
) -> AsyncGenerator[str | StreamToolEvent, None]:
    """Stream a response from the configured provider chunk by chunk.

    Yields either plain text chunks (str) or StreamToolEvent objects
    when the provider emits tool calls in streaming mode.
    """
    if session_id is None:
        session_id = (await Database.get_active_session(user_id))["id"]

    assert session_id is not None

    ctx = LLMContext.from_profile(profile).require_configured()
    assert ctx.provider is not None and ctx.model is not None
    ctx.chat_session_id = session_id

    messages = await build_messages(
        profile,
        session_id,
        interface,
        user_message,
        user_id,
    )

    async for chunk in _stream_from_provider(
        ctx,
        messages,
        source="chat",
    ):
        yield chunk
