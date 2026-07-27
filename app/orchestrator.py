"""Single entrypoint for user messages — implements Thought → Action → Observation loop."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from app.core.llm_context import LLMContext
from app.core.stream_fence import StreamFence
from app.db import Database
from app.llm_client import (
    generate_ai_response,
    generate_ai_response_streaming,
)
from app.logging_config import get_logger
from app.memory.retrieval import _clear_embedding_cache
from app.providers import get_ai_manager
from app.providers.openai_protocol import normalize_tool_calls
from app.services.memory_service import MemoryService
from app.services.session_service import SessionService
from app.tools import multimodal_tools
from app.tools.registry import (
    execute_tool_event,
)
from app.tools.schemas import (
    StreamToolEvent,
    ToolResultEvent,
    make_tool_call_event,
    new_turn_id,
)

log = get_logger(__name__)

_TIMESTAMP_SUFFIX = re.compile(r"\s*\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\s*$")
_EMPTY_RESPONSE_FALLBACK = "I'm having trouble responding right now. Please try again."
_MD_IMAGE_PATTERN = re.compile(r"!\[[^\]]{0,200}\]\(([^)]{1,200})\)")

_MAX_ORCHESTRATION_LOOPS = 4

_BASE_DIR = Path(__file__).resolve().parent.parent
_ALLOWED_IMAGE_DIRS = [
    (_BASE_DIR / "static").resolve(),
    (_BASE_DIR / "static" / "uploads").resolve(),
    (_BASE_DIR / "static" / "generated_images").resolve(),
    (_BASE_DIR / "uploads").resolve(),
    (_BASE_DIR / "generated_images").resolve(),
]
_ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _dedupe_attachments(
    *sources: list[str] | None,
) -> list[str]:
    """Merge multiple image-path lists, deduping by realpath.

    Preserves first-occurrence order. Falls back to the literal path when
    os.path.realpath cannot resolve it (e.g. URL strings or non-existent
    files) so URL-based entries are still retained. Non-string / empty
    entries are skipped. Each source list is consumed in the order it is
    passed; subsequent sources may not reintroduce a path already seen.
    """
    seen: set[str] = set()
    out: list[str] = []
    for source in sources:
        if not source:
            continue
        for raw in source:
            if not raw or not isinstance(raw, str):
                continue
            try:
                key = os.path.realpath(raw)
            except (OSError, ValueError):
                key = raw
            if key in seen:
                continue
            seen.add(key)
            out.append(raw)
    return out


def _validate_image_path_safely(user_path: str) -> Path | None:
    """Validate a user-provided image path by searching trusted directories."""
    if not user_path or not isinstance(user_path, str):
        return None

    filename = os.path.basename(user_path.replace("\\", "/"))

    if not filename:
        return None

    if filename.startswith(".") or ".." in filename:
        log.warning("suspicious filename rejected: %s", filename[:50])
        return None

    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_IMAGE_EXTS:
        return None

    for trusted_dir in _ALLOWED_IMAGE_DIRS:
        candidate = trusted_dir / filename

        try:
            resolved = candidate.resolve()

            if not resolved.is_file():
                continue

            # Verify resolved path is still within trusted_dir (handles symlinks)
            try:
                rel = os.path.relpath(str(resolved), str(trusted_dir))
                if rel.startswith(".."):
                    log.warning("path escaped trusted dir: %s", filename[:50])
                    continue
            except ValueError:
                continue

            return resolved
        except OSError:
            continue

    return None


def _parse_image_path(tool_json_str: str) -> str | None:
    """Extract image path from tool result JSON."""
    try:
        data = json.loads(tool_json_str)
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
            return data["data"].get("image_path")
    except Exception:
        pass
    return None


def _cache_uploaded_images(message: str) -> list[str]:
    """Find [local_image] shortcuts in message, return valid absolute paths."""
    if "UPLOADED_IMAGES:" not in message or "IMAGE_UPLOAD:" not in message:
        return []

    paths: list[str] = []

    for line in message.split("\n"):
        if line.startswith("IMAGE_UPLOAD:"):
            user_path = line[len("IMAGE_UPLOAD:") :].strip()

            # Use the safe validator
            validated = _validate_image_path_safely(user_path)
            if validated:
                paths.append(str(validated))

    return paths


def _cache_images_from_message(message: str) -> list[str]:
    """Resolve image references in message to local cache paths, with validation."""
    uploaded = _cache_uploaded_images(message)
    if uploaded:
        return uploaded

    cached: list[str] = []
    for match in _MD_IMAGE_PATTERN.finditer(message):
        source = match.group(1)

        # Limit source length to prevent ReDoS
        if len(source) > 500:
            source = source[:500]

        if source.startswith(("static/", "uploads/", "generated_images/")):
            # Use the safe validator
            validated = _validate_image_path_safely(source)
            if validated:
                cached.append(str(validated))
        else:
            local = multimodal_tools.download_image_to_cache(source)
            if local:
                cached.append(local)

    if not cached:
        for url in multimodal_tools.extract_image_urls(message)[:3]:
            local = multimodal_tools.download_image_to_cache(url)
            if local:
                cached.append(local)
    return cached


def _normalise_tool_calls(tool_calls: list[dict]) -> list[dict]:
    """Ensure every native tool call has a valid canonical shape."""
    canonical: list[dict] = []
    for index, tool_call in enumerate(tool_calls):
        if not isinstance(tool_call, dict):
            continue
        normalized = normalize_tool_calls([tool_call], message_index=index)
        if not normalized:
            continue
        call = normalized[0]
        canonical.append(
            {
                "id": call["id"],
                "name": call["function"]["name"],
                "arguments": json.loads(call["function"]["arguments"]),
            }
        )
    return canonical


async def _parse_raw_tool_calls_async(
    provider_name: str, raw_response: dict | None, turn_id: str = ""
) -> list[dict]:
    """Parse tool_calls from a raw provider API response (async).

    Uses the FC2 canonical AIProviderManager.parse_tool_calls() which routes
    through the provider's capability check. Returns a list of dicts with
    {id, name, arguments} — the canonical native FC shape.
    """
    if not raw_response:
        return []
    try:
        manager = await get_ai_manager()
        calls = manager.parse_tool_calls(provider_name, raw_response)
        return _normalise_tool_calls(
            [
                {
                    "id": c.get("id", ""),
                    "name": c["name"],
                    "arguments": c.get("arguments", {}),
                }
                for c in calls
                if c.get("name")
            ]
        )
    except Exception:
        return []


async def _execute_tool_calls_async(
    tool_calls: list[dict],
    session_id: str,
    user_id: str | None = None,
    turn_id: str = "",
) -> list[ToolResultEvent]:
    """Execute a list of tool calls and return results (async).

    Uses the canonical execute_tool_event() path.
    """
    results: list[ToolResultEvent] = []
    _normalise_tool_calls(tool_calls)
    for tc in tool_calls:
        raw_name: str = tc["name"]
        tool_name: str = raw_name
        arguments: dict[str, Any] = tc.get("arguments", {})
        log.info("native tool_call: %s %s [turn=%s]", tool_name, arguments, turn_id)

        call_event = make_tool_call_event(
            id=tc["id"],
            name=tool_name,
            arguments=arguments,
            turn_id=turn_id,
        )
        result_event = await execute_tool_event(
            call_event, session_id=session_id, user_id=user_id
        )
        results.append(result_event)
    return results


def _clean(text: str) -> str:
    return _TIMESTAMP_SUFFIX.sub("", text).strip()


async def _persist_user_async(
    message: str,
    session_id: str,
    attachments: list[str] | None,
    *,
    user_id: str,
    turn_id: str = "",
) -> int | None:
    return await Database.add_message(
        "user",
        message,
        session_id=session_id,
        attachments=attachments or None,
        user_id=user_id,
        turn_id=turn_id,
    )


async def _persist_assistant_async(
    content: str,
    session_id: str,
    attachments: list[str] | None = None,
    *,
    user_id: str,
    tool_calls: list[dict[str, Any]] | None = None,
    turn_id: str = "",
) -> None:
    """Persist an assistant response, with optional image paths and tool_calls (async)."""
    await Database.add_message(
        "assistant",
        content,
        session_id=session_id,
        attachments=attachments,
        user_id=user_id,
        tool_calls=tool_calls,
        turn_id=turn_id,
    )


async def _persist_tool_result_async(
    tool_name: str,
    content_json: str,
    session_id: str,
    *,
    user_id: str,
    tool_call_id: str,
    turn_id: str = "",
) -> None:
    """Persist a tool result as an OpenAI-format `tool` message (async)."""
    attachments = []
    if path := _parse_image_path(content_json):
        attachments.append(path)

    await Database.add_message(
        "tool",
        content_json,
        session_id=session_id,
        attachments=attachments,
        user_id=user_id,
        tool_call_id=tool_call_id,
        turn_id=turn_id,
    )


async def _persist_streaming_tool_results_async(
    tool_results: list[ToolResultEvent],
    tool_calls_data: list[dict],
    session_id: str,
    *,
    user_id: str,
    turn_id: str,
) -> tuple[list[str], list[str]]:
    """Persist streaming tool results while preserving the provider call ID."""
    tool_jsons: list[str] = []
    generated_paths: list[str] = []

    for i, result_event in enumerate(tool_results):
        tool_call_id: str | None = (
            tool_calls_data[i].get("id") if i < len(tool_calls_data) else None
        )
        tool_json_str = json.dumps(
            {
                "ok": result_event.ok,
                "name": result_event.name,
                "call_id": tool_call_id or "",
                "data": result_event.data,
                "error": result_event.error,
            },
            ensure_ascii=False,
        )
        tool_jsons.append(tool_json_str)
        await _persist_tool_result_async(
            result_event.name,
            tool_json_str,
            session_id,
            user_id=user_id,
            tool_call_id=tool_call_id or "",
            turn_id=turn_id,
        )
        if path := _parse_image_path(tool_json_str):
            generated_paths.append(path)

    return tool_jsons, generated_paths


async def _persist_observation_async(
    observation: str, session_id: str, *, user_id: str
) -> None:
    """Persist a system observation as an internal message (async)."""
    await Database.add_message(
        "system_observation", observation, session_id=session_id, user_id=user_id
    )


async def _post_turn_async(
    profile: dict[str, Any],
    user_message: str,
    final_response: str,
    session_id: str,
    active_session: dict[str, Any],
    *,
    user_id: str,
) -> None:
    """Run post-turn maintenance sequentially after the response completes."""
    try:
        await SessionService.auto_name_session_if_needed_async(
            session_id, active_session, user_id=user_id
        )
    except Exception as exc:
        log.info("[post-turn] session naming skipped: %s", type(exc).__name__)

    try:
        await MemoryService.run_per_message_checks_async(
            profile, user_message, final_response, session_id, active_session, user_id
        )
    except Exception as exc:
        log.info("[post-turn] memory maintenance skipped: %s", type(exc).__name__)

    try:
        _clear_embedding_cache()
    except Exception:
        pass


async def run_post_turn_after_stream_async(
    user_message: str,
    final_response: str,
    session_id: str,
    *,
    user_id: str,
) -> None:
    """Run post-stream maintenance without affecting the completed response."""
    try:
        profile = await Database.get_profile(user_id)
        active_session = await Database.get_active_session(user_id)
        await _post_turn_async(
            profile,
            user_message,
            final_response,
            session_id,
            active_session,
            user_id=user_id,
        )
    except Exception as exc:
        log.info("[post-stream] maintenance skipped: %s", type(exc).__name__)


async def _finalize_and_persist_async(
    session_id: str | None,
    fence_id: str,
    profile: dict[str, Any],
    user_message: str,
    final_response: str,
    active_session: dict[str, Any],
    *,
    user_id: str,
    turn_id: str = "",
) -> None:
    """Complete the stream fence and persist final state.

    This is the final cleanup step for a completed stream.
    """
    if final_response and session_id:
        await _persist_assistant_async(
            final_response, session_id, user_id=user_id, turn_id=turn_id
        )

    await StreamFence.complete(session_id or "", fence_id)
    log.info(f"[stream] fence {fence_id} completed")


async def handle_user_message(
    user_message: str, interface: str = "terminal", *, user_id: str
) -> str:
    """Process a user message end-to-end and return the assistant reply (async)."""
    profile = await Database.get_profile(user_id)
    if not user_message.strip():
        return "Please enter a message!"

    active_session = await Database.get_active_session(user_id)
    session_id = active_session["id"]
    cached_images = await asyncio.to_thread(_cache_images_from_message, user_message)

    ctx = LLMContext.from_profile(profile).require_configured()
    provider_name = ctx.provider
    turn_id = new_turn_id()

    await _persist_user_async(
        user_message, session_id, cached_images, user_id=user_id, turn_id=turn_id
    )

    text_response = ""
    loop_count = 0
    while loop_count < _MAX_ORCHESTRATION_LOOPS:
        loop_count += 1
        msg_for_pass = user_message if loop_count == 1 else ""

        generated_text, raw_api_response = await generate_ai_response(
            profile, msg_for_pass, interface, session_id, user_id=user_id
        )
        text_response = generated_text or ""

        if text_response is None:
            log.error("AI provider returned None")
            break

        text_response = _clean(text_response) or _EMPTY_RESPONSE_FALLBACK

        tool_calls = await _parse_raw_tool_calls_async(
            provider_name, raw_api_response, turn_id=turn_id
        )

        if not tool_calls:
            await _persist_assistant_async(
                text_response, session_id, user_id=user_id, turn_id=turn_id
            )
            break

        # Build OpenAI-format tool_calls JSON for persistence
        tool_calls_json = [
            {
                "id": tc.get("id", f"call_{i}"),
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": json.dumps(tc.get("arguments", {})),
                },
            }
            for i, tc in enumerate(tool_calls)
        ]

        # Persist assistant message WITH tool_calls
        await _persist_assistant_async(
            text_response,
            session_id,
            user_id=user_id,
            tool_calls=tool_calls_json,
            turn_id=turn_id,
        )

        tool_results = await _execute_tool_calls_async(
            tool_calls, session_id, user_id=user_id, turn_id=turn_id
        )

        await _persist_streaming_tool_results_async(
            tool_results, tool_calls, session_id, user_id=user_id, turn_id=turn_id
        )

    asyncio.create_task(
        _post_turn_async(
            profile,
            user_message,
            text_response or _EMPTY_RESPONSE_FALLBACK,
            session_id,
            active_session,
            user_id=user_id,
        )
    )
    return text_response or _EMPTY_RESPONSE_FALLBACK


async def handle_user_message_streaming(
    user_message: str,
    interface: str = "terminal",
    session_id: str | None = None,
    abort_check: Callable[[], bool] | None = None,
    attachments: list[str] | None = None,
    *,
    user_id: str,
) -> AsyncIterator[str | StreamToolEvent]:
    """Streaming entrypoint (async) with fence protection.

    FENCE PROTECTION: Wraps user message persistence in a fence to prevent
    ghost turns if stream is interrupted before completion.

    COORDINATOR: Drives the single execution loop delegating tool calls
    to native functions, returning responses to the stream.
    """
    profile = await Database.get_profile(user_id)
    if not user_message.strip() and not attachments:
        yield "Please enter a message!"
        return

    if abort_check and abort_check():
        return

    if session_id is None:
        active_session = await Database.get_active_session(user_id)
        session_id = active_session["id"]
    else:
        active_session = {"id": session_id}

    # Cache any images referenced in the message (URLs, etc.)
    cached_images = await asyncio.to_thread(_cache_images_from_message, user_message)

    # Merge with explicitly provided attachments, deduping by realpath so the
    # same file referenced via different forms (relative, absolute, with .., etc.)
    # is collapsed before persistence and downstream payload construction.
    all_attachments = _dedupe_attachments(cached_images, attachments)

    turn_id = new_turn_id()
    user_msg_id = await _persist_user_async(
        user_message,
        session_id,
        all_attachments or None,
        user_id=user_id,
        turn_id=turn_id,
    )
    fence_id = await StreamFence.acquire(session_id, user_msg_id or 0)
    log.info(f"[stream] fence {fence_id} acquired for session {session_id}")

    loop_count = 0
    while loop_count < _MAX_ORCHESTRATION_LOOPS:
        loop_count += 1
        response_chunks: list[str] = []
        tool_calls_data: list[dict] = []

        # Clear user message text after the first iteration so we just rebuild
        # the history and prompt for the next assistant turn.
        msg_for_pass = user_message if loop_count == 1 else ""

        try:
            async for chunk in generate_ai_response_streaming(
                profile,
                msg_for_pass,
                interface,
                session_id,
                user_id=user_id,
            ):
                if chunk:
                    if abort_check and abort_check():
                        log.info(
                            f"[stream] abort detected, fence {fence_id} not completed"
                        )
                        return

                    # FC9: Handle StreamToolEvent from provider streaming
                    if isinstance(chunk, StreamToolEvent):
                        if chunk.type == "tool_call" and isinstance(chunk.data, dict):
                            normalized_calls = _normalise_tool_calls([dict(chunk.data)])
                            if not normalized_calls:
                                log.error(
                                    "[stream] dropping invalid tool call event: %r",
                                    chunk.data,
                                )
                                continue
                            tool_call = normalized_calls[0]
                            tool_calls_data.append(tool_call)
                            log.info(
                                "[stream] received tool_call: %s [turn=%s]",
                                tool_call.get("name", "?"),
                                turn_id,
                            )
                            yield StreamToolEvent(
                                type="tool_call",
                                data={**tool_call, "turn_id": turn_id},
                            )
                        continue

                    response_chunks.append(chunk)
                    yield chunk
        except asyncio.CancelledError:
            log.info(
                "[stream] cancelled in generation loop - propagating to StreamBuffer"
            )
            log.warning(f"[stream] fence {fence_id} incomplete due to cancellation")
            raise
        except Exception as e:
            log.error("[stream] error in generation loop: %s", e)
            log.warning(f"[stream] fence {fence_id} incomplete due to error: {e}")
            raise

        full_response = "".join(response_chunks)

        if not _clean(full_response) and not tool_calls_data:
            await _finalize_and_persist_async(
                session_id,
                fence_id,
                profile,
                user_message,
                _EMPTY_RESPONSE_FALLBACK,
                active_session,
                user_id=user_id,
            )
            if loop_count == 1:
                yield _EMPTY_RESPONSE_FALLBACK
            return

        # Handle native function calls if provider returned them
        if tool_calls_data:
            # Build OpenAI-format tool_calls JSON for persistence
            tool_calls_json = [
                {
                    "id": tc.get("id", f"call_{i}"),
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc.get("arguments", {})),
                    },
                }
                for i, tc in enumerate(tool_calls_data)
            ]

            # Persist assistant message WITH tool_calls
            await _persist_assistant_async(
                full_response,
                session_id,
                user_id=user_id,
                tool_calls=tool_calls_json,
                turn_id=turn_id,
            )

            log.info(
                "[stream] executing %d native tool call(s) [turn=%s]",
                len(tool_calls_data),
                turn_id,
            )
            tool_results = await _execute_tool_calls_async(
                tool_calls_data, session_id, user_id=user_id, turn_id=turn_id
            )
            (
                tool_jsons,
                all_generated_paths,
            ) = await _persist_streaming_tool_results_async(
                tool_results,
                tool_calls_data,
                session_id,
                user_id=user_id,
                turn_id=turn_id,
            )

            for i, result_event in enumerate(tool_results):
                tc_id = result_event.call_id
                yield StreamToolEvent(
                    type="tool_result",
                    data={
                        "call_id": tc_id,
                        "name": result_event.name,
                        "ok": result_event.ok,
                        "data": result_event.data,
                        "error": result_event.error,
                        "turn_id": turn_id,
                    },
                )

            # Tools were executed and persisted. The loop will now continue to the next
            # iteration which will fetch the updated history including these tools.
            continue

        # No tool calls — finalize text response
        await _finalize_and_persist_async(
            session_id,
            fence_id,
            profile,
            user_message,
            full_response,
            active_session,
            user_id=user_id,
            turn_id=turn_id,
        )
        return

    # Hit max loops fallback
    await _finalize_and_persist_async(
        session_id,
        fence_id,
        profile,
        user_message,
        "",
        active_session,
        user_id=user_id,
        turn_id=turn_id,
    )
    return
