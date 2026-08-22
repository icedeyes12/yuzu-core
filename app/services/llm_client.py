"""(｡•̀ᴗ-)✧"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from typing import Any

from app.core.capabilities import (
    ModelCapabilities,
    RequestRequirements,
    omit_images,
    request_needs_vision,
    resolve_effective_capabilities,
)
from app.core.llm_context import LLMContext
from app.core.logging_config import get_logger
from app.core.request_context import ClientContext
from app.db import Database
from app.providers import get_ai_manager
from app.providers.openai_protocol import validate_chat_completion_response
from app.services.prompt_service import build_messages
from app.tools.registry import get_tool_schemas_for_user
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


async def _unique_tool_schemas(user_id: str) -> list[dict[str, Any]]:
    """Get tool schemas scoped to the authenticated user's sandbox."""
    return await get_tool_schemas_for_user(user_id)


async def _resolve_request_payload(
    messages: list[dict[str, Any]],
    model_info,
    provider_allows_tools: bool,
    user_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(｡•̀ᴗ-)✧"""
    tools = await _unique_tool_schemas(user_id)
    requirements = RequestRequirements(
        needs_vision=request_needs_vision(messages),
        needs_function_call=bool(tools),
    )
    capabilities = resolve_effective_capabilities(
        model_info.capabilities if model_info else ModelCapabilities(),
        requirements,
        provider_allows_tools=provider_allows_tools,
    )
    if not capabilities.tools_included:
        tools = []
    if not capabilities.images_included:
        messages = omit_images(messages)
    return messages, tools


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
    user_id: str,
    source: str = "chat",
) -> tuple[str | None, dict[str, Any] | None]:
    """Single LLM dispatch with timing log. Returns (text, raw_response)."""
    _ = ctx.require_configured()
    ai_manager = await get_ai_manager()
    model_info = ai_manager.get_model_info(ctx.provider or "", ctx.model or "")
    provider_allows_tools = ai_manager.provider_supports_tools(ctx.provider or "")
    messages, schemas = await _resolve_request_payload(
        messages, model_info, provider_allows_tools, user_id
    )

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
    client_context: ClientContext | None = None,
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
        client_context,
    )

    text, raw = await _send_to_provider(
        ctx,
        messages,
        user_id=user_id,
        source="chat",
    )
    return text, raw


async def _stream_from_provider(
    ctx: LLMContext,
    messages: list[dict[str, Any]],
    *,
    user_id: str,
    source: str = "chat",
) -> AsyncGenerator[str | StreamToolEvent, None]:
    """Yield raw chunks from the provider's streaming API."""
    _ = ctx.require_configured()
    ai_manager = await get_ai_manager()

    # Generate tool schemas
    model_info = ai_manager.get_model_info(ctx.provider or "", ctx.model or "")
    provider_allows_tools = ai_manager.provider_supports_tools(ctx.provider or "")
    messages, tools = await _resolve_request_payload(
        messages, model_info, provider_allows_tools, user_id
    )

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
    client_context: ClientContext | None = None,
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
        client_context,
    )

    async for chunk in _stream_from_provider(
        ctx,
        messages,
        user_id=user_id,
        source="chat",
    ):
        yield chunk
