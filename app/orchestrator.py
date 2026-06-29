"""Single entrypoint for user messages — implements Thought → Action → Observation loop."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, AsyncIterator

from app.commands import (
    IMAGE_SHORTCUT_WARNING,
    TOOL_ALIASES,
    execute_commands,
    has_tool_blocks,
    is_markdown_image_shortcut,
    parse_image_path,
    parse_tool_blocks,
)
from app.db import Database
from app.llm_client import (
    generate_ai_response,
    generate_ai_response_streaming,
)
from app.logging_config import get_logger
from app.services.session_service import SessionService
from app.services.memory_service import MemoryService
from app.tools import multimodal_tools
from app.tools.registry import execute_tool, get_tool_role

log = get_logger(__name__)

_TIMESTAMP_SUFFIX = re.compile(r"\s*\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\s*$")
_EMPTY_RESPONSE_FALLBACK = "I'm having trouble responding right now. Please try again."
_MD_IMAGE_PATTERN = re.compile(r"!\[[^\]]{0,200}\]\(([^)]{1,200})\)")

_MAX_ORCHESTRATION_LOOPS = 4
_STREAM_FENCE_TIMEOUT = 300

_BASE_DIR = Path(__file__).resolve().parent.parent
_ALLOWED_IMAGE_DIRS = [
    (_BASE_DIR / "static").resolve(),
    (_BASE_DIR / "static" / "uploads").resolve(),
    (_BASE_DIR / "static" / "generated_images").resolve(),
    (_BASE_DIR / "uploads").resolve(),
    (_BASE_DIR / "generated_images").resolve(),
]
_ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


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

            if resolved.is_symlink():
                log.warning("symlink rejected: %s", filename[:50])
                continue

            return resolved

        except (OSError, ValueError):
            continue

    return None


def _cache_uploaded_images(message: str) -> list[str]:
    """Extract image paths from uploaded-images marker, with path validation."""
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


async def _parse_raw_tool_calls_async(
    provider_name: str, raw_response: dict | None
) -> list[dict]:
    """Parse tool_calls from a raw provider API response (async)."""
    if not raw_response:
        return []
    try:
        # WORKAROUND: Lazy import to prevent circular dependency
        from app.providers import get_ai_manager

        manager = await get_ai_manager()
        provider = manager.providers.get(provider_name)
        if not provider:
            return []
        calls = provider.parse_tool_calls(raw_response)
        return [
            {"name": c["name"], "arguments": c["arguments"]}
            for c in calls
            if c.get("name")
        ]
    except Exception:
        return []


async def _execute_tool_calls_async(
    tool_calls: list[dict], session_id: str, user_id: str | None = None
) -> list[tuple[str, dict]]:
    """Execute a list of tool calls and return results (async)."""
    results: list[tuple[str, dict]] = []
    for tc in tool_calls:
        raw_name = tc["name"]
        tool_name = TOOL_ALIASES.get(raw_name, raw_name)
        arguments = tc.get("arguments", {})
        log.info("native tool_call: %s %s", tool_name, arguments)
        result = await execute_tool(
            tool_name, arguments, session_id=session_id, user_id=user_id
        )
        results.append((tool_name, result))
    return results


def _build_ephemeral_context(
    assistant_text: str | None,
    tool_results: list[tuple[str, dict]],
    tool_calls: list[dict] | None = None,
) -> list[dict[str, Any]]:
    """Build ephemeral messages representing assistant tool_calls + tool results.

    These messages are appended to the LLM payload during synthesis so the
    model sees the full conversation including what was just executed.
    They are NOT persisted to DB — only used for the current turn.
    """
    messages: list[dict[str, Any]] = []

    if not tool_calls and not tool_results:
        return messages

    # Build assistant message with tool_calls
    if tool_calls:
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": assistant_text or None,
            "tool_calls": [
                {
                    "id": tc.get("id", f"call_{i}"),
                    "type": "function",
                    "function": {
                        "name": bc["name"],
                        "arguments": json.dumps(bc.get("arguments", {})),
                    },
                }
                for i, bc in enumerate(tool_calls)
            ],
        }
        messages.append(assistant_msg)

    # Build tool result messages
    if tool_calls:
        # Match results to tool_calls by index
        for i, tc in enumerate(tool_calls):
            tc_id = tc.get("id", f"call_{i}")
            result_text = ""
            if i < len(tool_results):
                _, result = tool_results[i]
                result_text = result.get("markdown", str(result))
            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": result_text,
            })
    else:
        # Fallback: no tool_calls info, just add results as tool role
        for tool_name, result in tool_results:
            result_text = result.get("markdown", str(result))
            messages.append({
                "role": "tool",
                "content": result_text,
            })

    return messages


def _build_streaming_ephemeral_context(
    clean_text: str,
    combined_tool_markdown: str,
) -> list[dict[str, Any]]:
    """Build ephemeral context for the streaming path.

    The streaming path parses <command> blocks from text (no native tool_calls).
    We reconstruct a minimal conversation snippet so the LLM synthesis sees:
    - assistant text (clean text with tool blocks stripped)
    - observation (tool results as a user message)

    This is a simplified version of _build_ephemeral_context for the streaming
    path where we don't have structured tool_calls.
    """
    messages: list[dict[str, Any]] = []

    # Assistant message (clean text without tool blocks)
    if clean_text and clean_text.strip():
        messages.append({
            "role": "assistant",
            "content": clean_text.strip(),
        })

    # Tool results as a synthetic user message
    if combined_tool_markdown and combined_tool_markdown.strip():
        messages.append({
            "role": "user",
            "content": f"[Tool execution result]\n{combined_tool_markdown.strip()}",
        })

    return messages


def _clean(text: str) -> str:
    return _TIMESTAMP_SUFFIX.sub("", text).strip()


async def _persist_user_async(
    message: str, session_id: str, image_paths: list[str] | None, *, user_id: str
) -> int | None:
    return await Database.add_message_async(
        "user",
        message,
        session_id=session_id,
        image_paths=image_paths or None,
        user_id=user_id,
    )


async def _persist_assistant_async(
    content: str,
    session_id: str,
    image_paths: list[str] | None = None,
    *,
    user_id: str,
    tool_calls: list[dict[str, Any]] | None = None,
) -> None:
    """Persist an assistant response, with optional image paths and tool_calls (async)."""
    await Database.add_message_async(
        "assistant",
        content,
        session_id=session_id,
        image_paths=image_paths,
        user_id=user_id,
        tool_calls=tool_calls,
    )


async def _persist_tool_result_async(
    tool_name: str,
    markdown: str,
    session_id: str,
    *,
    user_id: str,
    tool_call_id: str | None = None,
) -> None:
    """Persist a tool result (async).

    If tool_call_id is provided, the role is normalized to "tool" (OpenAI format)
    and the message is linked to the assistant's tool_call.
    Without tool_call_id (legacy path), falls back to tool-specific role.
    """
    image_paths = []
    if path := parse_image_path(markdown):
        image_paths.append(path)

    if tool_call_id:
        # OpenAI format: role="tool", link via tool_call_id
        await Database.add_message_async(
            "tool",
            markdown,
            session_id=session_id,
            image_paths=image_paths or None,
            user_id=user_id,
            tool_call_id=tool_call_id,
        )
    else:
        # Legacy fallback
        await Database.add_message_async(
            get_tool_role(tool_name),
            markdown,
            session_id=session_id,
            image_paths=image_paths or None,
            user_id=user_id,
        )


async def _persist_observation_async(
    observation: str, session_id: str, *, user_id: str
) -> None:
    """Persist a system observation as an internal message (async)."""
    await Database.add_message_async(
        "system_observation", observation, session_id=session_id, user_id=user_id
    )


async def _run_synthesis_async(
    profile: dict[str, Any],
    session_id: str,
    interface: str,
    tool_markdown: str,
    user_id: str | None = None,
    ephemeral_context: list[dict[str, Any]] | None = None,
) -> str | None:
    """Run a 2nd LLM pass to narrate around the tool result.

    ephemeral_context: in-memory messages (assistant tool_calls + tool results)
    not yet persisted to DB. Appended to build_messages() output so the LLM
    sees the full conversation including the tool that was just executed.
    """
    text, _ = await generate_ai_response(
        profile,
        "",
        interface,
        session_id,
        is_tool_loop=True,
        suppress_tools=True,
        user_id=user_id,
        ephemeral_context=ephemeral_context,
    )
    if not text or not text.strip():
        return None

    return _clean(text)


async def _stream_synthesis_async(
    profile: dict[str, Any],
    session_id: str,
    interface: str,
    tool_markdown: str,
    user_id: str | None = None,
    ephemeral_context: list[dict[str, Any]] | None = None,
) -> AsyncIterator[str]:
    """Stream the 2nd LLM pass.

    ephemeral_context: in-memory messages (assistant tool_calls + tool results)
    not yet persisted to DB. Appended to build_messages() output so the LLM
    sees the full conversation including the tool that was just executed.
    """
    async for chunk in generate_ai_response_streaming(
        profile,
        "",
        interface,
        session_id,
        is_tool_loop=True,
        suppress_tools=True,
        user_id=user_id,
        ephemeral_context=ephemeral_context,
    ):
        yield chunk


_PIPELINE_CHECK_INTERVAL = 5


async def _post_turn_async(
    profile: dict[str, Any],
    user_message: str,
    final_response: str,
    session_id: str,
    active_session: dict[str, Any],
    *,
    user_id: str,
) -> None:
    """Auto-rename session, summarize memory, trigger memory pipeline (async)."""
    # Auto-rename via service
    await SessionService.auto_name_session_if_needed_async(
        session_id, active_session, user_id=user_id
    )

    # Memory checks via service
    await MemoryService.run_per_message_checks_async(
        profile, user_message, final_response, session_id, active_session, user_id
    )

    # Clear request-scoped caches
    # _clear_request_cache was removed
    try:
        from app.memory.retrieval import _clear_embedding_cache

        _clear_embedding_cache()
    except Exception:
        pass


async def _process_tool_commands_async(
    full_response: str,
    session_id: str,
    *,
    user_id: str,
) -> tuple[str, bool, list[str]]:
    """Parse and execute tool commands, yielding tool markdown chunks.

    Yields:
        tuple of (tool_markdown, is_image_tool, generated_paths)

    Returns:
        Combined tool markdown string and list of all generated image paths.
    """
    commands, clean_text = parse_tool_blocks(full_response)

    if not commands:
        return ("", "", False, [])

    log.info("[stream] found %d tool block(s)", len(commands))

    results = await execute_commands(commands, session_id=session_id, user_id=user_id)

    if clean_text and clean_text.strip():
        await _persist_assistant_async(clean_text, session_id, user_id=user_id)
        log.info("[stream] persisted clean_text (pre-tool assistant message)")

    tool_markdowns: list[str] = []
    any_image_tool = False
    all_generated_paths: list[str] = []

    for tool_name, result in results:
        tool_markdown = result.get("markdown", str(result))
        tool_markdowns.append(tool_markdown)

        await _persist_tool_result_async(
            tool_name, tool_markdown, session_id, user_id=user_id
        )
        log.info(f"[stream] persisted tool result for {tool_name}")
        p = parse_image_path(tool_markdown)
        if p is not None:
            any_image_tool = True
            all_generated_paths.append(p)

    combined_tool_markdown = "\n\n".join(tool_markdowns)

    return (clean_text, combined_tool_markdown, any_image_tool, all_generated_paths)


async def _run_orchestration_loop_async(
    profile: dict[str, Any],
    session_id: str,
    interface: str,
    current_synthesis_context: str,
    any_image_tool: bool,
    fence_id: int,
    abort_check: callable[[], bool] | None,
    user_message: str,
    active_session: dict[str, Any],
    *,
    user_id: str,
    ephemeral_context: list[dict[str, Any]] | None = None,
) -> AsyncIterator[str]:
    """Run the orchestration loop for synthesis with tool block detection."""
    loop_count = 0
    all_generated_paths: list[str] = []

    while loop_count < _MAX_ORCHESTRATION_LOOPS:
        loop_count += 1
        log.info("[stream] orchestration loop %d", loop_count)

        if abort_check and abort_check():
            return

        synthesis_chunks: list[str] = []
        full_synthesis = ""

        try:
            async for chunk in _stream_synthesis_async(
                profile,
                session_id,
                interface,
                current_synthesis_context,
                user_id=user_id,
                ephemeral_context=ephemeral_context,
            ):
                if chunk:
                    if abort_check and abort_check():
                        return

                    synthesis_chunks.append(chunk)
                    full_synthesis += chunk
                    yield (
                        "\n\n" + chunk
                        if any_image_tool and not synthesis_chunks[:-1]
                        else chunk
                    )
        except asyncio.CancelledError:
            log.info(
                "[stream] cancelled in synthesis loop - propagating to StreamBuffer"
            )
            raise
        except Exception as e:
            log.error("[stream] error in synthesis loop: %s", e)
            raise

        synthesis = _clean(full_synthesis) if full_synthesis else None

        if not synthesis:
            await StreamFence.complete(session_id, fence_id)
            await _post_turn_async(
                profile,
                user_message,
                current_synthesis_context,
                session_id,
                active_session,
                user_id=user_id,
            )
            return

        if not has_tool_blocks(synthesis):
            # No tool blocks in synthesis — this is the final response.
            await _persist_assistant_async(synthesis, session_id, user_id=user_id)
            await StreamFence.complete(session_id, fence_id)
            log.info("[stream] fence %s completed (final synthesis)", fence_id)
            await _post_turn_async(
                profile,
                user_message,
                synthesis,
                session_id,
                active_session,
                user_id=user_id,
            )
            return

        # Synthesis contains tool blocks — model is retrying / doing multi-step.
        # Execute the tools and loop (up to _MAX_ORCHESTRATION_LOOPS).
        log.info("[stream] synthesis contains tool blocks — continuing loop (%d/%d)", loop_count, _MAX_ORCHESTRATION_LOOPS)

        next_commands, clean_synth = parse_tool_blocks(synthesis)
        if not next_commands:
            await _persist_assistant_async(
                clean_synth or synthesis, session_id, user_id=user_id
            )
            await _post_turn_async(
                profile,
                user_message,
                clean_synth or synthesis,
                session_id,
                active_session,
                user_id=user_id,
            )
            return

        # Persist intermediate synthesis (clean)
        if clean_synth and clean_synth.strip():
            await _persist_assistant_async(clean_synth, session_id, user_id=user_id)
            log.info("[stream] persisted intermediate synthesis (clean)")

        # Execute tools
        next_results = await execute_commands(
            next_commands, session_id=session_id, user_id=user_id
        )
        next_markdowns: list[str] = []

        for tool_name, result in next_results:
            tm = result.get("markdown", str(result))
            next_markdowns.append(tm)
            await _persist_tool_result_async(tool_name, tm, session_id, user_id=user_id)
            p = parse_image_path(tm)
            if p:
                any_image_tool = True
                all_generated_paths.append(p)
            yield "\n\n" + tm

        current_synthesis_context = "\n\n".join(next_markdowns)

    # Fallback: should not reach here normally
    await StreamFence.complete(session_id, fence_id)
    await _post_turn_async(
        profile,
        user_message,
        current_synthesis_context,
        session_id,
        active_session,
        user_id=user_id,
    )


async def _finalize_and_persist_async(
    session_id: str,
    fence_id: int,
    profile: dict[str, Any],
    user_message: str,
    final_response: str,
    active_session: dict[str, Any],
    *,
    user_id: str,
) -> None:
    """Complete the stream fence and persist final state.

    This is the final cleanup step for a completed stream.
    """
    await StreamFence.complete(session_id, fence_id)
    log.info(f"[stream] fence {fence_id} completed")
    await _post_turn_async(
        profile,
        user_message,
        final_response,
        session_id,
        active_session,
        user_id=user_id,
    )


async def handle_user_message(
    user_message: str, interface: str = "terminal", *, user_id: str
) -> str:
    """Process a user message end-to-end and return the assistant reply (async)."""
    profile = await Database.get_profile_async(user_id)
    if not user_message.strip():
        return "Please enter a message!"

    active_session = await Database.get_active_session_async(user_id)
    session_id = active_session["id"]
    cached_images = await asyncio.to_thread(_cache_images_from_message, user_message)

    stripped = user_message.strip()
    if stripped.startswith("/imagine ") or stripped.startswith("<command>"):
        commands, _ = parse_tool_blocks(stripped)
        if commands or stripped.startswith("/imagine"):
            if stripped.startswith("/imagine"):
                commands = [stripped]

            await _persist_user_async(
                user_message, session_id, cached_images, user_id=user_id
            )

            results = await execute_commands(
                commands, session_id=session_id, user_id=user_id
            )
            tool_markdowns = []

            for tool_name, result in results:
                tool_markdown = result.get("markdown", str(result))
                tool_markdowns.append(tool_markdown)
                await _persist_tool_result_async(
                    tool_name, tool_markdown, session_id, user_id=user_id
                )

            combined = "\n\n".join(tool_markdowns)

            generated_paths = []
            for tm in tool_markdowns:
                path = parse_image_path(tm)
                if path:
                    generated_paths.append(path)

            # Run synthesis — single source of truth from DB history
            synthesis = await _run_synthesis_async(
                profile, session_id, interface, combined, user_id=user_id,
            )
            if synthesis:
                await _persist_assistant_async(
                    synthesis, session_id, generated_paths, user_id=user_id
                )
                final = (
                    f"{combined}\n\n{synthesis}"
                    if parse_image_path(combined)
                    else synthesis
                )
            else:
                final = combined

            await _post_turn_async(
                profile,
                user_message,
                synthesis or combined,
                session_id,
                active_session,
                user_id=user_id,
            )
            return final  # CLI display value; DB has discrete messages

    provider_name = (profile.get("providers_config") or {}).get(
        "preferred_provider", "ollama"
    )

    try:
        text_response, raw_api_response = await generate_ai_response(
            profile, user_message, interface, session_id, user_id=user_id
        )
    except Exception:
        await _persist_user_async(
            user_message, session_id, cached_images, user_id=user_id
        )
        raise

    await _persist_user_async(user_message, session_id, cached_images, user_id=user_id)

    if text_response is None:
        log.error("AI provider returned None")
        return ""

    text_response = _clean(text_response) or _EMPTY_RESPONSE_FALLBACK

    if is_markdown_image_shortcut(text_response):
        return IMAGE_SHORTCUT_WARNING

    tool_calls = await _parse_raw_tool_calls_async(provider_name, raw_api_response)
    if tool_calls:
        tool_results = await _execute_tool_calls_async(
            tool_calls, session_id, user_id=user_id
        )

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
            text_response, session_id, user_id=user_id,
            tool_calls=tool_calls_json,
        )

        # Persist tool results WITH tool_call_id
        all_generated_paths: list[str] = []
        for i, (tool_name, tool_result) in enumerate(tool_results):
            tc_id = tool_calls[i].get("id", f"call_{i}")
            tool_markdown = tool_result.get("markdown", str(tool_result))
            if p := parse_image_path(tool_markdown):
                all_generated_paths.append(p)
            await _persist_tool_result_async(
                tool_name, tool_markdown, session_id,
                user_id=user_id, tool_call_id=tc_id,
            )

        # Now synthesis — single source of truth from DB history
        # No ephemeral context needed since history is correct
        synthesis = await _run_synthesis_async(
            profile, session_id, interface, "", user_id=user_id,
        )

        if synthesis:
            await _persist_assistant_async(
                synthesis, session_id, all_generated_paths or None, user_id=user_id
            )
            final_response = synthesis
            await _post_turn_async(
                profile,
                user_message,
                synthesis,
                session_id,
                active_session,
                user_id=user_id,
            )
            return final_response

        await _post_turn_async(
            profile,
            user_message,
            "",
            session_id,
            active_session,
            user_id=user_id,
        )
        return ""

    await _persist_assistant_async(text_response, session_id, user_id=user_id)
    await _post_turn_async(
        profile,
        user_message,
        text_response,
        session_id,
        active_session,
        user_id=user_id,
    )
    return text_response


class StreamFence:
    """Prevents race conditions between user message persistence and stream completion.

    Each stream gets a unique fence ID that must be cleared after successful completion.
    Abandoned fences expire after timeout to prevent deadlocks.
    """

    _fences: dict[int, dict[str, Any]] = {}  # session_id -> fence_info
    _lock = asyncio.Lock()

    @classmethod
    async def acquire(cls, session_id: str, user_msg_id: int) -> str:
        """Acquire a fence for a streaming session. Returns fence_id.

        Proactively runs cleanup_expired() to evict any stale fences from
        prior sessions before claiming a new one. Without this, abandoned
        fences can pin session memory for up to _STREAM_FENCE_TIMEOUT.
        """
        import uuid

        await cls.cleanup_expired()

        fence_id = str(uuid.uuid4())[:8]
        async with cls._lock:
            # If a previous fence is still pinned for this session, log and
            # overwrite rather than silently keep the stale one.
            if session_id in cls._fences:
                prior = cls._fences[session_id]
                if not prior.get("completed"):
                    log.warning(
                        "stream fence for session %s was not completed "
                        "(prior fence_id=%s); replacing with %s",
                        session_id,
                        prior.get("fence_id"),
                        fence_id,
                    )
            cls._fences[session_id] = {
                "fence_id": fence_id,
                "user_msg_id": user_msg_id,
                "acquired_at": asyncio.get_event_loop().time(),
                "completed": False,
            }
        return fence_id

    @classmethod
    async def complete(cls, session_id: str, fence_id: str) -> bool:
        """Mark fence as completed, allowing persistence.

        Returns True on a successful transition, False if the fence was
        missing or owned by a different fence_id (i.e. already evicted or
        replaced). Callers should log accordingly; the return value is the
        source of truth for whether the fence was safely retired.
        """
        async with cls._lock:
            if session_id not in cls._fences:
                log.warning(
                    "stream fence complete() called for session %s but no "
                    "fence is registered (fence_id=%s)",
                    session_id,
                    fence_id,
                )
                return False
            fence = cls._fences[session_id]
            if fence["fence_id"] != fence_id:
                log.warning(
                    "stream fence id mismatch for session %s: expected %s, "
                    "got %s — likely already replaced",
                    session_id,
                    fence.get("fence_id"),
                    fence_id,
                )
                return False
            fence["completed"] = True
        return True

    @classmethod
    async def is_completed(cls, session_id: str) -> bool:
        """Check if fence is completed or expired. Logs when it self-clears."""
        async with cls._lock:
            if session_id not in cls._fences:
                return True  # No fence = already cleared

            fence = cls._fences[session_id]
            elapsed = asyncio.get_event_loop().time() - fence["acquired_at"]

            # If completed or expired, clear it
            if fence["completed"] or elapsed > _STREAM_FENCE_TIMEOUT:
                del cls._fences[session_id]
                if elapsed > _STREAM_FENCE_TIMEOUT:
                    log.warning(
                        "stream fence for session %s expired after %.0fs",
                        session_id,
                        elapsed,
                    )
                return True

            return False

    @classmethod
    async def cleanup_expired(cls) -> None:
        """Remove all expired fences."""
        async with cls._lock:
            now = asyncio.get_event_loop().time()
            expired = [
                sid
                for sid, fence in cls._fences.items()
                if now - fence["acquired_at"] > _STREAM_FENCE_TIMEOUT
            ]
            for sid in expired:
                del cls._fences[sid]


async def handle_user_message_streaming(
    user_message: str,
    interface: str = "terminal",
    session_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    abort_check: callable[[], bool] | None = None,
    image_paths: list[str] | None = None,
    *,
    user_id: str,
) -> AsyncIterator[str]:
    """Streaming entrypoint (async) with fence protection.

    FENCE PROTECTION: Wraps user message persistence in a fence to prevent
    ghost turns if stream is interrupted before completion.

    COORDINATOR: Delegates tool execution to _process_tool_commands_async,
    synthesis loops to _run_orchestration_loop_async, and finalization
    to _finalize_and_persist_async.
    """
    profile = await Database.get_profile_async(user_id)
    if not user_message.strip() and not image_paths:
        yield "Please enter a message!"
        return

    if abort_check and abort_check():
        return

    if session_id is None:
        active_session = await Database.get_active_session_async(user_id)
        session_id = active_session["id"]
    else:
        active_session = {"id": session_id}

    # Cache any images referenced in the message (URLs, etc.)
    cached_images = await asyncio.to_thread(_cache_images_from_message, user_message)

    # Merge with explicitly provided image_paths
    all_image_paths = list(cached_images) if cached_images else []
    if image_paths:
        all_image_paths.extend(image_paths)

    user_msg_id = await _persist_user_async(
        user_message, session_id, all_image_paths or None, user_id=user_id
    )
    fence_id = await StreamFence.acquire(session_id, user_msg_id or 0)
    log.info(f"[stream] fence {fence_id} acquired for session {session_id}")

    response_chunks: list[str] = []
    try:
        async for chunk in generate_ai_response_streaming(
            profile,
            user_message,
            interface,
            session_id,
            provider,
            model,
            user_id=user_id,
        ):
            if chunk:
                if abort_check and abort_check():
                    log.info(f"[stream] abort detected, fence {fence_id} not completed")
                    return

                response_chunks.append(chunk)
                yield chunk
    except asyncio.CancelledError:
        log.info("[stream] cancelled in first pass - propagating to StreamBuffer")
        log.warning(f"[stream] fence {fence_id} incomplete due to cancellation")
        raise
    except Exception as e:
        log.error("[stream] error in first pass: %s", e)
        log.warning(f"[stream] fence {fence_id} incomplete due to error: {e}")
        raise

    full_response = "".join(response_chunks)

    if not _clean(full_response):
        await _finalize_and_persist_async(
            session_id,
            fence_id,
            profile,
            user_message,
            _EMPTY_RESPONSE_FALLBACK,
            active_session,
            user_id=user_id,
        )
        yield _EMPTY_RESPONSE_FALLBACK
        return

    if is_markdown_image_shortcut(full_response):
        await StreamFence.complete(session_id, fence_id)
        yield IMAGE_SHORTCUT_WARNING
        return

    tool_result = await _process_tool_commands_async(
        full_response, session_id, user_id=user_id
    )
    clean_text, combined_tool_markdown, any_image_tool, all_generated_paths = (
        tool_result
    )

    # Yield tool markdown chunks
    if combined_tool_markdown:
        yield "\n\n" + combined_tool_markdown

    current_synthesis_context = combined_tool_markdown

    if not combined_tool_markdown:
        await _finalize_and_persist_async(
            session_id,
            fence_id,
            profile,
            user_message,
            clean_text or full_response,
            active_session,
            user_id=user_id,
        )
        return

    # Build ephemeral context for synthesis: assistant text + tool results
    # so the LLM sees what was just executed
    ephemeral_ctx = _build_streaming_ephemeral_context(
        clean_text, combined_tool_markdown
    )

    async for chunk in _run_orchestration_loop_async(
        profile=profile,
        session_id=session_id,
        interface=interface,
        current_synthesis_context=current_synthesis_context,
        any_image_tool=any_image_tool,
        fence_id=fence_id,
        abort_check=abort_check,
        user_message=user_message,
        active_session=active_session,
        user_id=user_id,
        ephemeral_context=ephemeral_ctx,
    ):
        yield chunk

    return  # orchestration loop handles finalization
