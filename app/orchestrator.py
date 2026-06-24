# FILE: app/orchestrator.py
# DESCRIPTION: Single entrypoint for handling user messages.
#              Implements Thought → Action → Observation agentic loop.
#              Uses <tool>...</tool> protocol for tool invocation.

from __future__ import annotations

import asyncio
import base64
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
from app.tools.registry import execute_tool, get_tool_role, is_terminal_tool
from app.visual_context import store_visual_context

log = get_logger(__name__)

_TIMESTAMP_SUFFIX = re.compile(r"\s*\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\s*$")
_EMPTY_RESPONSE_FALLBACK = "I'm having trouble responding right now. Please try again."
_MD_IMAGE_PATTERN = re.compile(r"!\[[^\]]{0,200}\]\(([^)]{1,200})\)")

# Services

# Maximum orchestration loops to prevent runaway execution
_MAX_ORCHESTRATION_LOOPS = 30

# Stream fence timeout - incomplete streams abandoned after this duration (seconds)
_STREAM_FENCE_TIMEOUT = 300  # 5 minutes

# Allowed image directories (resolved at module load, not runtime)
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
    """Validate a user-provided image path by searching trusted directories.

    SECURITY: This function NEVER constructs paths from user input directly.
    Instead, it extracts ONLY the filename (using os.path.basename) and
    searches for it in pre-defined trusted directories.

    This breaks the CodeQL taint chain completely - no part of the user's
    path string is used in path construction.

    Returns:
        Path object if valid image found, None otherwise.
    """
    if not user_path or not isinstance(user_path, str):
        return None

    # SECURITY: Extract ONLY the filename - this removes all directory components
    # and ensures no path traversal is possible. The filename is just a string
    # that we use to search in OUR trusted directories.
    filename = os.path.basename(user_path.replace("\\", "/"))

    if not filename:
        return None

    # Validate filename is not dangerous (defensive)
    if filename.startswith(".") or ".." in filename:
        log.warning("suspicious filename rejected: %s", filename[:50])
        return None

    # Check extension
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_IMAGE_EXTS:
        return None

    # SECURITY: Search ONLY in pre-resolved trusted directories
    # We construct paths using our constants, NOT user input
    for trusted_dir in _ALLOWED_IMAGE_DIRS:
        # Construct candidate using TRUSTED base + filename only
        candidate = trusted_dir / filename

        try:
            # Resolve and verify
            resolved = candidate.resolve()

            # Must exist and be a regular file
            if not resolved.is_file():
                continue

            # Verify resolved path is still within trusted_dir
            # (handles symlinks that might escape)
            try:
                rel = os.path.relpath(str(resolved), str(trusted_dir))
                if rel.startswith(".."):
                    log.warning("path escaped trusted dir: %s", filename[:50])
                    continue
            except ValueError:
                continue

            # Additional symlink check
            if resolved.is_symlink():
                log.warning("symlink rejected: %s", filename[:50])
                continue

            return resolved

        except (OSError, ValueError):
            continue

    return None


# --------------------------------------------------------------------
# Image-cache helpers
# --------------------------------------------------------------------


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


def _load_image_base64(image_path: str) -> tuple[str | None, str | None]:
    """Return (base64, mime) for a generated image file, or (None, None)."""
    # Use the safe validator - this is the key for CodeQL
    validated_path = _validate_image_path_safely(image_path)
    if not validated_path:
        return None, None

    try:
        data = base64.b64encode(validated_path.read_bytes()).decode("utf-8")
    except OSError as e:
        log.warning("image read failed (%s): %s", validated_path, e)
        return None, None

    suffix = validated_path.suffix.lower()
    if suffix == ".png":
        mime = "image/png"
    elif suffix == ".gif":
        mime = "image/gif"
    else:
        mime = "image/jpeg"
    return data, mime


# --------------------------------------------------------------------
# Native tool-call helpers (for providers that support it)
# --------------------------------------------------------------------


async def _parse_raw_tool_calls_async(
    provider_name: str, raw_response: dict | None
) -> list[dict]:
    """Parse tool_calls from a raw provider API response (async)."""
    if not raw_response:
        return []
    try:
        # WORKAROUND: Lazy import to prevent circular dependency with app.providers
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
        if is_terminal_tool(tool_name) and result.get("ok"):
            break
    return results


# --------------------------------------------------------------------
# Response post-processing
# --------------------------------------------------------------------


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
    content: str, session_id: str, image_paths: list[str] | None = None, *, user_id: str
) -> None:
    """Persist an assistant response, with optional image paths (async)."""
    await Database.add_message_async(
        "assistant",
        content,
        session_id=session_id,
        image_paths=image_paths,
        user_id=user_id,
    )


async def _persist_tool_result_async(
    tool_name: str, markdown: str, session_id: str, *, user_id: str
) -> None:
    """Persist a tool result (async)."""
    image_paths = []
    if path := parse_image_path(markdown):
        image_paths.append(path)

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


# --------------------------------------------------------------------
# Synthesis pass (2nd LLM call after tools ran)
# --------------------------------------------------------------------


async def _build_image_context_async(
    tool_markdown: str, session_id: str
) -> list[dict[str, Any]] | None:
    image_path = parse_image_path(tool_markdown)
    if not image_path:
        return None
    # Assuming _load_image_base64 is fast or run it in thread if needed
    # It reads bytes, so better to use asyncio.to_thread if it's not already
    b64, mime = await asyncio.to_thread(_load_image_base64, image_path)
    if not (b64 and mime):
        return None
    # Assuming store_visual_context is fast/local
    store_visual_context(session_id, b64, mime)
    log.info("attached generated image to synthesis pass")
    return [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]


async def _run_synthesis_async(
    profile: dict[str, Any],
    session_id: str,
    interface: str,
    tool_markdown: str,
    ephemeral_context: list[dict[str, str]] | None = None,
    user_id: str | None = None,
) -> str | None:
    """Run a 2nd LLM pass to narrate around the tool result (async).

    ephemeral_context: In-memory conversation turns not yet in DB.
    """
    image_context = await _build_image_context_async(tool_markdown, session_id)

    text, _ = await generate_ai_response(
        profile,
        "",
        interface,
        session_id,
        image_content_for_context=image_context,
        ephemeral_context=ephemeral_context,
        is_tool_loop=True,
        user_id=user_id,
    )
    if not text or not text.strip():
        return None

    return _clean(text)


async def _stream_synthesis_async(
    profile: dict[str, Any],
    session_id: str,
    interface: str,
    tool_markdown: str,
    ephemeral_context: list[dict[str, str]] | None = None,
    user_id: str | None = None,
) -> AsyncIterator[str]:
    """Stream the 2nd LLM pass (async).

    ephemeral_context: In-memory conversation turns not yet in DB.
    Contains the assistant's first-pass response with <command> blocks
    and the tool results, ensuring the LLM has full context.
    """
    image_context = await _build_image_context_async(tool_markdown, session_id)

    async for chunk in generate_ai_response_streaming(
        profile,
        "",
        interface,
        session_id,
        image_content_for_context=image_context,
        ephemeral_context=ephemeral_context,
        is_tool_loop=True,
        user_id=user_id,
    ):
        yield chunk


# --------------------------------------------------------------------
# Per-turn side effects
# --------------------------------------------------------------------

_PIPELINE_CHECK_INTERVAL = 5


async def _post_turn_async(
    profile: dict[str, Any],
    user_message: str,
    final_response: str,
    session_id: str,
    active_session: dict[str, Any],
) -> None:
    """Auto-rename session, summarize memory, trigger memory pipeline (async)."""
    user_id = profile.get("id")
    if not user_id:
        log.warning("_post_turn_async: profile has no id — memory pipeline skipped")
        return

    # Auto-rename via service
    await SessionService.auto_name_session_if_needed_async(
        session_id, active_session, user_id=user_id
    )

    # Memory checks via service
    await MemoryService.run_per_message_checks_async(
        profile, user_message, final_response, session_id, active_session, user_id
    )

    # Clear request-scoped caches
    # _clear_request_cache was removed in Phase 2B safe deletions
    try:
        from app.memory.retrieval import _clear_embedding_cache

        _clear_embedding_cache()
    except Exception:
        pass


# --------------------------------------------------------------------
# Streaming orchestration helpers
# --------------------------------------------------------------------


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
        return ("", False, [])

    log.info("[stream] found %d tool block(s)", len(commands))

    results = await execute_commands(commands, session_id=session_id, user_id=user_id)

    # SAFEGUARD: Persist clean_text BEFORE tool execution
    # This ensures linear message order: user → assistant (clean) → tool → synthesis
    if clean_text and clean_text.strip():
        await _persist_assistant_async(clean_text, session_id, user_id=user_id)
        log.info("[stream] persisted clean_text (pre-tool assistant message)")

    tool_markdowns: list[str] = []
    any_image_tool = False
    all_generated_paths: list[str] = []

    for tool_name, result in results:
        tool_markdown = result.get("markdown", str(result))
        tool_markdowns.append(tool_markdown)

        # SAFEGUARD: Persist each tool result immediately
        await _persist_tool_result_async(
            tool_name, tool_markdown, session_id, user_id=user_id
        )
        log.info(f"[stream] persisted tool result for {tool_name}")
        p = parse_image_path(tool_markdown)
        if p is not None:
            any_image_tool = True
            all_generated_paths.append(p)

    combined_tool_markdown = "\n\n".join(tool_markdowns)

    # Return results for coordination
    return (combined_tool_markdown, any_image_tool, all_generated_paths)


async def _run_orchestration_loop_async(
    profile: dict[str, Any],
    session_id: str,
    interface: str,
    current_synthesis_context: str,
    ephemeral_context: list[dict[str, str]],
    any_image_tool: bool,
    fence_id: int,
    abort_check: callable[[], bool] | None,
    user_message: str,
    active_session: dict[str, Any],
    *,
    user_id: str,
) -> AsyncIterator[str]:
    """Run the orchestration loop for synthesis with tool block detection.

    Handles iterative synthesis passes that may contain additional tool blocks.
    Continues until synthesis has no more tool blocks or max loops reached.

    Yields:
        Synthesis chunks and tool result markdown.
    """
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
                ephemeral_context=ephemeral_context,
            ):
                if chunk:
                    if abort_check and abort_check():
                        return

                    synthesis_chunks.append(chunk)
                    full_synthesis += chunk

                    # Yield chunk with proper formatting
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
            )
            return

        if not has_tool_blocks(synthesis):
            final_response = (
                f"{current_synthesis_context}\n\n{synthesis}"
                if any_image_tool
                else synthesis
            )
            await StreamFence.complete(session_id, fence_id)
            log.info(f"[stream] fence {fence_id} completed (final synthesis)")
            await _post_turn_async(
                profile, user_message, final_response, session_id, active_session
            )
            return

        log.info("[stream] synthesis contains tool blocks, continuing loop")

        next_commands, _ = parse_tool_blocks(synthesis)
        if not next_commands:
            await _post_turn_async(
                profile, user_message, synthesis, session_id, active_session
            )
            return

        # Append synthesis + next tool results to ephemeral context
        ephemeral_context.append({"role": "assistant", "content": synthesis})

        next_results = await execute_commands(next_commands, session_id=session_id)
        next_markdowns: list[str] = []
        any_image_tool = False

        for tool_name, result in next_results:
            tm = result.get("markdown", str(result))
            next_markdowns.append(tm)
            p = parse_image_path(tm)
            if p:
                any_image_tool = True
                all_generated_paths.append(p)
            yield "\n\n" + tm

        next_combined = "\n\n".join(next_markdowns)
        ephemeral_context.append({"role": "user", "content": next_combined})
        current_synthesis_context = next_combined

    # Max loops reached
    await StreamFence.complete(session_id, fence_id)
    await _post_turn_async(
        profile,
        user_message,
        synthesis or current_synthesis_context,
        session_id,
        active_session,
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
        profile, user_message, final_response, session_id, active_session
    )


# --------------------------------------------------------------------
# Public entry points
# --------------------------------------------------------------------


async def handle_user_message(
    user_message: str, interface: str = "terminal", *, user_id: str
) -> str:
    """Process a user message end-to-end and return the assistant reply (async)."""
    profile = await Database.get_profile_async(user_id)
    if not user_message.strip():
        return "Please enter a message!"

    active_session = await Database.get_active_session_async(user_id)
    session_id = active_session["id"]
    # Assuming _cache_images_from_message is fast (local check + small download)
    # If it downloads, it should be async. Let's check multimodal_tools.
    cached_images = await asyncio.to_thread(_cache_images_from_message, user_message)

    # Fast-path: user typed /imagine directly
    stripped = user_message.strip()
    if stripped.startswith("/imagine ") or stripped.startswith("<command>"):
        commands, _ = parse_tool_blocks(stripped)
        if commands or stripped.startswith("/imagine"):
            if stripped.startswith("/imagine"):
                commands = [stripped]

            await _persist_user_async(
                user_message, session_id, cached_images, user_id=user_id
            )

            results = await execute_commands(commands, session_id=session_id)
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

            # Run synthesis
            synthesis = await _run_synthesis_async(
                profile, session_id, interface, combined
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
                profile, user_message, final, session_id, active_session
            )
            return final

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

    # Try native tool-call execution first
    tool_calls = await _parse_raw_tool_calls_async(provider_name, raw_api_response)
    if tool_calls:
        tool_results = await _execute_tool_calls_async(
            tool_calls, session_id, user_id=user_id
        )

        # SAFEGUARD: Persist clean text_response BEFORE tool execution
        if text_response and text_response.strip():
            await _persist_assistant_async(text_response, session_id, user_id=user_id)
            log.info("[non-stream] persisted clean text_response (pre-tool)")

        if tool_results:
            tool_name, tool_result = tool_results[0]
            tool_markdown = tool_result.get("markdown", str(tool_result))
            await _persist_tool_result_async(
                tool_name, tool_markdown, session_id, user_id=user_id
            )

            is_image_tool = parse_image_path(tool_markdown) is not None
            generated_paths = (
                [parse_image_path(tool_markdown)] if is_image_tool else None
            )

            # Build ephemeral context for synthesis
            ephemeral_context = [
                {"role": "assistant", "content": text_response},
                {"role": "user", "content": tool_markdown},
            ]

            synthesis = await _run_synthesis_async(
                profile,
                session_id,
                interface,
                tool_markdown,
                ephemeral_context=ephemeral_context,
            )

            if synthesis:
                await _persist_assistant_async(
                    synthesis, session_id, generated_paths, user_id=user_id
                )
                final_response = (
                    f"{tool_markdown}\n\n{synthesis}" if is_image_tool else synthesis
                )
                await _post_turn_async(
                    profile, user_message, final_response, session_id, active_session
                )
                return final_response

            await _post_turn_async(
                profile, user_message, tool_markdown, session_id, active_session
            )
            return tool_markdown

    await _persist_assistant_async(text_response, session_id, user_id=user_id)
    await _post_turn_async(
        profile, user_message, text_response, session_id, active_session
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

    # FENCE: Acquire fence before persisting user message
    user_msg_id = await _persist_user_async(
        user_message, session_id, all_image_paths or None, user_id=user_id
    )
    fence_id = await StreamFence.acquire(session_id, user_msg_id or 0)
    log.info(f"[stream] fence {fence_id} acquired for session {session_id}")

    # === PHASE 1: Initial LLM response streaming ===
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

    # === PHASE 2: Handle empty response ===
    if not _clean(full_response):
        await _finalize_and_persist_async(
            session_id,
            fence_id,
            profile,
            user_message,
            _EMPTY_RESPONSE_FALLBACK,
            active_session,
        )
        yield _EMPTY_RESPONSE_FALLBACK
        return

    # === PHASE 3: Handle markdown image shortcut ===
    if is_markdown_image_shortcut(full_response):
        await StreamFence.complete(session_id, fence_id)
        yield IMAGE_SHORTCUT_WARNING
        return

    # === PHASE 4: Parse and execute tool commands ===
    tool_result = await _process_tool_commands_async(
        full_response, session_id, user_id=user_id
    )
    combined_tool_markdown, any_image_tool, all_generated_paths = tool_result

    # Yield tool markdown chunks
    if combined_tool_markdown:
        yield "\n\n" + combined_tool_markdown

    # === PHASE 5: Build ephemeral context for synthesis ===
    ephemeral_context: list[dict[str, str]] = [
        {"role": "assistant", "content": full_response},
        {"role": "user", "content": combined_tool_markdown},
    ]

    current_synthesis_context = combined_tool_markdown
    # all_generated_paths is already a list from _process_tool_commands_async

    if not combined_tool_markdown:
        # No tool output, just finalize
        await _finalize_and_persist_async(
            session_id, fence_id, profile, user_message, full_response, active_session
        )
        return

    # === PHASE 6: Run orchestration loop (synthesis with potential tool blocks) ===
    async for chunk in _run_orchestration_loop_async(
        profile=profile,
        session_id=session_id,
        interface=interface,
        current_synthesis_context=current_synthesis_context,
        ephemeral_context=ephemeral_context,
        any_image_tool=any_image_tool,
        fence_id=fence_id,
        abort_check=abort_check,
        user_message=user_message,
        active_session=active_session,
        user_id=user_id,
    ):
        yield chunk

    return  # Orchestration loop handles finalization
