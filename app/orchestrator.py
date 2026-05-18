# FILE: app/orchestrator.py
# DESCRIPTION: Single entrypoint for handling user messages.
#              Implements Thought → Action → Observation agentic loop.
#              Uses <tool>...</tool> protocol for tool invocation.

from __future__ import annotations

import re
from typing import Any, Iterator

from app.commands import (
    IMAGE_SHORTCUT_WARNING,
    execute_commands,
    extract_markdown_image_path,
    format_observation,
    has_tool_blocks,
    is_markdown_image_shortcut,
    parse_image_path,
    parse_tool_blocks,
)
from app.database import Database
from app.llm_client import (
    generate_ai_response,
    generate_ai_response_streaming,
)
from app.logging_config import get_logger
from app.tools import multimodal_tools
from app.tools.registry import get_tool_role
from app.visual_context import store_visual_context

log = get_logger(__name__)

_TIMESTAMP_SUFFIX = re.compile(r"\s*\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\s*$")
_EMPTY_RESPONSE_FALLBACK = "I'm having trouble responding right now. Please try again."
_MD_IMAGE_PATTERN = re.compile(r"!\[[^\]]{0,200}\]\(([^)]{1,200})\)")

# Maximum orchestration loops to prevent runaway execution
_MAX_ORCHESTRATION_LOOPS = 5


# --------------------------------------------------------------------
# Image-cache helpers
# --------------------------------------------------------------------


def _cache_uploaded_images(message: str) -> list[str]:
    """Extract image paths from uploaded-images marker, with path validation."""
    if "UPLOADED_IMAGES:" not in message or "IMAGE_UPLOAD:" not in message:
        return []

    import os
    paths: list[str] = []

    # Allowed directories for image paths
    allowed_dirs = ("static/", "uploads/", "generated_images/")

    for line in message.split("\n"):
        if line.startswith("IMAGE_UPLOAD:"):
            candidate = line[len("IMAGE_UPLOAD:"):].strip()

            if not candidate:
                continue

            # Normalize path to prevent traversal
            candidate = os.path.normpath(candidate)

            # Check for path traversal attempts
            if candidate.startswith("..") or candidate.startswith("/"):
                log.warning("rejected path traversal attempt: %s", candidate[:50])
                continue

            # Verify path is within allowed directories
            if not any(candidate.startswith(d) for d in allowed_dirs):
                log.warning("rejected path outside allowed dirs: %s", candidate[:50])
                continue

            if os.path.isfile(candidate):
                paths.append(candidate)

    return paths


def _cache_images_from_message(message: str) -> list[str]:
    """Resolve any image references in *message* to local cache paths, with validation."""
    import os
    uploaded = _cache_uploaded_images(message)
    if uploaded:
        return uploaded

    # Allowed directories for image paths
    allowed_dirs = ("static/", "uploads/", "generated_images/")

    cached: list[str] = []
    for match in _MD_IMAGE_PATTERN.finditer(message):
        source = match.group(1)

        # Limit source length to prevent ReDoS
        if len(source) > 500:
            source = source[:500]

        if source.startswith(("static/", "uploads/", "generated_images/")):
            local = source if source.startswith("static/") else f"static/{source}"

            # Security: validate normalized path
            local = os.path.normpath(local)
            if not any(local.startswith(d) for d in allowed_dirs):
                continue
            if ".." in local or local.startswith("/"):
                continue

            if os.path.isfile(local):
                cached.append(local)
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


def _resolve_safe_image_path(image_path: str):
    """Resolve and validate an untrusted image path, returning a trusted Path or None."""
    from pathlib import Path

    def _has_symlink_ancestor(path: Path) -> bool:
        """True if any ancestor (including the file itself) is a symlink."""
        for parent in [path, *path.parents]:
            try:
                if parent.is_symlink():
                    return True
            except OSError:
                return True
        return False

    if not image_path:
        return None

    base_dir = Path(__file__).resolve().parent.parent
    allowed_root_names = {"static", "uploads"}
    allowed_dirs = [base_dir / root for root in allowed_root_names]
    allowed_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

    try:
        candidate = Path(image_path.strip())
        if candidate.is_absolute():
            log.warning("absolute path blocked: %s", image_path)
            return None

        parts = candidate.parts
        if not parts or any(part in ("", ".", "..") for part in parts):
            log.warning("invalid relative path blocked: %s", image_path)
            return None

        if parts[0] not in allowed_root_names:
            log.warning("path outside allowed roots: %s", image_path)
            return None

        resolved_path = (base_dir / candidate).resolve()

        is_allowed = False
        for allowed_dir in allowed_dirs:
            allowed_root = allowed_dir.resolve()
            try:
                resolved_path.relative_to(allowed_root)
                is_allowed = True
                break
            except ValueError:
                continue

        if not is_allowed:
            log.warning("path outside allowed dirs: %s", image_path)
            return None

        if resolved_path.suffix.lower() not in allowed_exts:
            log.warning("disallowed image extension blocked: %s", image_path)
            return None

        if not resolved_path.exists() or not resolved_path.is_file():
            log.warning("image not found or not a file: %s", image_path)
            return None

        if _has_symlink_ancestor(resolved_path):
            log.warning("symlink path blocked: %s", image_path)
            return None

        return resolved_path

    except (ValueError, OSError) as e:
        log.warning("invalid path: %s - %s", image_path, e)
        return None


def _load_image_base64(image_path: str) -> tuple[str | None, str | None]:
    """Return (base64, mime) for a generated image file, or (None, None)."""
    import base64

    resolved_path = _resolve_safe_image_path(image_path)
    if not resolved_path:
        return None, None

    try:
        data = base64.b64encode(resolved_path.read_bytes()).decode("utf-8")
    except OSError as e:
        log.warning("image read failed (%s): %s", resolved_path, e)
        return None, None

    suffix = resolved_path.suffix.lower()
    if suffix == ".png":
        mime = "image/png"
    elif suffix == ".webp":
        mime = "image/webp"
    elif suffix == ".gif":
        mime = "image/gif"
    else:
        mime = "image/jpeg"
    return data, mime


# --------------------------------------------------------------------
# Native tool-call helpers (for providers that support it)
# --------------------------------------------------------------------


def _parse_raw_tool_calls(
    provider_name: str, raw_response: dict | None
) -> list[dict]:
    """Parse tool_calls from a raw provider API response."""
    if not raw_response:
        return []
    try:
        from app.providers import get_ai_manager
        manager = get_ai_manager()
        provider = manager.providers.get(provider_name)
        if not provider:
            return []
        calls = provider.parse_tool_calls(raw_response)
        return [{"name": c["name"], "arguments": c["arguments"]} for c in calls if c.get("name")]
    except Exception:
        return []


def _execute_tool_calls(
    tool_calls: list[dict], session_id: int
) -> list[tuple[str, dict]]:
    """Execute a list of tool calls and return results."""
    from app.commands import _TOOL_ALIASES
    from app.tools.registry import execute_tool, is_terminal_tool

    results: list[tuple[str, dict]] = []
    for tc in tool_calls:
        raw_name = tc["name"]
        tool_name = _TOOL_ALIASES.get(raw_name, raw_name)
        arguments = tc.get("arguments", {})
        log.info("native tool_call: %s %s", tool_name, arguments)
        result = execute_tool(tool_name, arguments, session_id=session_id)
        results.append((tool_name, result))
        if is_terminal_tool(tool_name) and result.get("ok"):
            break
    return results


# --------------------------------------------------------------------
# Response post-processing
# --------------------------------------------------------------------


def _clean(text: str) -> str:
    return _TIMESTAMP_SUFFIX.sub("", text).strip()


def _persist_user(
    message: str, session_id: int, image_paths: list[str] | None
) -> None:
    Database.add_message(
        "user", message, session_id=session_id, image_paths=image_paths or None
    )


def _persist_tool_result(
    tool_name: str, markdown: str, session_id: int
) -> None:
    Database.add_message(get_tool_role(tool_name), markdown, session_id=session_id)


def _persist_observation(observation: str, session_id: int) -> None:
    """Persist a system observation as an internal message."""
    Database.add_message("system_observation", observation, session_id=session_id)


# --------------------------------------------------------------------
# Synthesis pass (2nd LLM call after tools ran)
# --------------------------------------------------------------------


def _build_image_context(
    tool_markdown: str, session_id: int
) -> list[dict[str, Any]] | None:
    image_path = parse_image_path(tool_markdown)
    if not image_path:
        return None
    b64, mime = _load_image_base64(image_path)
    if not (b64 and mime):
        return None
    store_visual_context(session_id, b64, mime)
    log.info("attached generated image to synthesis pass")
    return [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]


def _run_synthesis(
    profile: dict[str, Any],
    session_id: int,
    interface: str,
    tool_markdown: str,
) -> str | None:
    """Run a 2nd LLM pass to narrate around the tool result."""
    image_context = _build_image_context(tool_markdown, session_id)

    text, _ = generate_ai_response(
        profile, "", interface, session_id, image_content_for_context=image_context
    )
    if not text or not text.strip():
        return None

    return _clean(text)


def _stream_synthesis(
    profile: dict[str, Any],
    session_id: int,
    interface: str,
    tool_markdown: str,
) -> Iterator[str]:
    """Stream the 2nd LLM pass."""
    image_context = _build_image_context(tool_markdown, session_id)

    for chunk in generate_ai_response_streaming(
        profile, "", interface, session_id,
        image_content_for_context=image_context,
    ):
        yield chunk


# --------------------------------------------------------------------
# Per-turn side effects
# --------------------------------------------------------------------

_PIPELINE_CHECK_INTERVAL = 5


def _post_turn(
    profile: dict[str, Any],
    user_message: str,
    final_response: str,
    session_id: int,
    active_session: dict[str, Any],
) -> None:
    """Auto-rename session, summarize memory, trigger memory pipeline."""
    from app.session_lifecycle import auto_name_session_if_needed
    from app.profile_analysis import (
        should_summarize_memory,
        summarize_memory,
    )

    auto_name_session_if_needed(session_id, active_session)
    if should_summarize_memory(profile, user_message, session_id):
        summarize_memory(profile, user_message, final_response, session_id)

    # Throttle: only check pipeline every Nth message
    msg_count = Database.get_session_messages_count(session_id)
    if msg_count % _PIPELINE_CHECK_INTERVAL == 0:
        _trigger_memory_pipeline(session_id)

    # Clear request-scoped caches
    try:
        from app.memory.memory import _clear_request_cache
        _clear_request_cache(session_id)
    except Exception:
        pass
    try:
        from app.memory.retrieval import _clear_embedding_cache
        _clear_embedding_cache()
    except Exception:
        pass


def _trigger_memory_pipeline(session_id: int) -> None:
    try:
        from app.memory.memory import trigger_memory_pipeline_async
        count = Database.get_session_messages_count(session_id)
        if not trigger_memory_pipeline_async(session_id, count):
            log.info("memory pipeline skipped (count=%s)", count)
    except Exception as e:
        log.warning("memory pipeline trigger failed: %s", e)


# --------------------------------------------------------------------
# Agentic Loop: Thought → Action → Observation
# --------------------------------------------------------------------


def _run_agentic_loop(
    profile: dict[str, Any],
    user_message: str,
    interface: str,
    session_id: int,
    initial_response: str,
) -> str:
    """Run the agentic Thought → Action → Observation loop.

    This implements the core orchestration:
    1. Receive LLM response
    2. Parse tool blocks
    3. If no tool blocks: return response
    4. If tool blocks: execute tools, format observation, loop back to LLM
    5. Continue until no tool blocks or max loops reached
    """
    current_response = initial_response
    loop_count = 0

    while loop_count < _MAX_ORCHESTRATION_LOOPS:
        loop_count += 1
        log.info("orchestration loop %d", loop_count)

        # Parse tool blocks from current response
        commands, clean_text = parse_tool_blocks(current_response)

        if not commands:
            # No tool blocks - we're done
            log.info("no tool blocks found, ending orchestration")
            return current_response

        log.info("found %d tool block(s)", len(commands))

        # Persist the narration (clean text before tool execution)
        if clean_text:
            Database.add_message("assistant", clean_text, session_id=session_id)

        # Execute all commands sequentially
        results = execute_commands(commands, session_id=session_id)

        # Persist each tool result
        tool_markdowns: list[str] = []
        any_image_tool = False

        for tool_name, result in results:
            tool_markdown = result.get("markdown", str(result))
            tool_markdowns.append(tool_markdown)
            _persist_tool_result(tool_name, tool_markdown, session_id)

            if parse_image_path(tool_markdown) is not None:
                any_image_tool = True

        # Format and persist observation
        observation = format_observation(results)
        if observation:
            _persist_observation(observation, session_id)

        # Combine tool markdowns for synthesis
        combined_tool_markdown = "\n\n".join(tool_markdowns)

        # Run synthesis pass to get next response
        synthesis = _run_synthesis(
            profile, session_id, interface, combined_tool_markdown
        )

        if not synthesis:
            # No synthesis - return tool results
            log.info("no synthesis generated, returning tool results")
            return combined_tool_markdown

        # Check if synthesis contains more tool blocks
        if has_tool_blocks(synthesis):
            log.info("synthesis contains tool blocks, continuing loop")
            current_response = synthesis
            # Don't persist synthesis yet - it will be processed in next iteration
            continue

        # No more tool blocks - persist and return synthesis
        Database.add_message("assistant", synthesis, session_id=session_id)

        if any_image_tool:
            return f"{combined_tool_markdown}\n\n{synthesis}"
        return synthesis

    # Max loops reached
    log.warning("max orchestration loops reached (%d)", _MAX_ORCHESTRATION_LOOPS)
    return current_response


# --------------------------------------------------------------------
# Public entry points
# --------------------------------------------------------------------


def handle_user_message(user_message: str, interface: str = "terminal") -> str:
    """Process a user message end-to-end and return the assistant reply.

    Implements the agentic Thought → Action → Observation loop using
    the <tool>...</tool> protocol for tool invocation.
    """
    profile = Database.get_profile()
    if not user_message.strip():
        return "Please enter a message!"

    active_session = Database.get_active_session()
    session_id = active_session["id"]
    cached_images = _cache_images_from_message(user_message)

    # Fast-path: user typed /imagine directly
    stripped = user_message.strip()
    if stripped.startswith("/imagine ") or stripped.startswith("<tool>"):
        # Check if it's a direct tool invocation
        commands, _ = parse_tool_blocks(stripped)
        if commands or stripped.startswith("/imagine"):
            if stripped.startswith("/imagine"):
                commands = [stripped]

            _persist_user(user_message, session_id, cached_images)

            results = execute_commands(commands, session_id=session_id)
            tool_markdowns = []

            for tool_name, result in results:
                tool_markdown = result.get("markdown", str(result))
                tool_markdowns.append(tool_markdown)
                _persist_tool_result(tool_name, tool_markdown, session_id)

            combined = "\n\n".join(tool_markdowns)

            # Run synthesis
            synthesis = _run_synthesis(profile, session_id, interface, combined)
            if synthesis:
                Database.add_message("assistant", synthesis, session_id=session_id)
                final = f"{combined}\n\n{synthesis}" if parse_image_path(combined) else synthesis
            else:
                final = combined

            _post_turn(profile, user_message, final, session_id, active_session)
            return final

    provider_name = (profile.get("providers_config") or {}).get("preferred_provider", "ollama")

    try:
        text_response, raw_api_response = generate_ai_response(
            profile, user_message, interface, session_id
        )
    except Exception:
        _persist_user(user_message, session_id, cached_images)
        raise

    _persist_user(user_message, session_id, cached_images)

    if text_response is None:
        log.error("AI provider returned None")
        return ""

    text_response = _clean(text_response) or _EMPTY_RESPONSE_FALLBACK

    if is_markdown_image_shortcut(text_response):
        log.warning(
            "intercepted markdown image shortcut: %s",
            extract_markdown_image_path(text_response),
        )
        return IMAGE_SHORTCUT_WARNING

    # Try native tool-call execution first (for providers that support it)
    native_tool_executed = False
    tool_results: list[tuple[str, dict]] = []
    tool_calls = _parse_raw_tool_calls(provider_name, raw_api_response)
    if tool_calls:
        tool_results = _execute_tool_calls(tool_calls, session_id)
        if tool_results:
            native_tool_executed = True
            tool_name, tool_result = tool_results[0]
            tool_markdown = tool_result.get("markdown", str(tool_result))
            _persist_tool_result(tool_name, tool_markdown, session_id)

            is_image_tool = parse_image_path(tool_markdown) is not None
            synthesis = _run_synthesis(
                profile, session_id, interface, tool_markdown
            )

            if synthesis:
                Database.add_message("assistant", synthesis, session_id=session_id)
                final_response = (
                    f"{tool_markdown}\n\n{synthesis}" if is_image_tool else synthesis
                )
                _post_turn(profile, user_message, final_response, session_id, active_session)
                return final_response

            _post_turn(profile, user_message, tool_markdown, session_id, active_session)
            return tool_markdown

    if not native_tool_executed:
        # Run agentic loop with <tool> block protocol
        final_response = _run_agentic_loop(
            profile, user_message, interface, session_id, text_response
        )
        _post_turn(profile, user_message, final_response, session_id, active_session)
        return final_response

    return text_response


def handle_user_message_streaming(
    user_message: str,
    interface: str = "terminal",
    provider: str | None = None,
    model: str | None = None,
) -> Iterator[str]:
    """Streaming entrypoint with true incremental chunk delivery.

    Implements the agentic loop:
    1. Stream LLM response
    2. Parse tool blocks
    3. If no tool blocks: done
    4. If tool blocks: stream narration, execute tools, stream synthesis
    5. Loop until no tool blocks
    """
    profile = Database.get_profile()
    if not user_message.strip():
        yield "Please enter a message!"
        return

    active_session = Database.get_active_session()
    session_id = active_session["id"]
    cached_images = _cache_images_from_message(user_message)

    # Fast-path: user typed /imagine directly
    stripped = user_message.strip()
    if stripped.startswith("/imagine ") or stripped.startswith("<tool>"):
        commands, _ = parse_tool_blocks(stripped)
        if commands or stripped.startswith("/imagine"):
            if stripped.startswith("/imagine"):
                commands = [stripped]

            _persist_user(user_message, session_id, cached_images)

            results = execute_commands(commands, session_id=session_id)

            for tool_name, result in results:
                tool_markdown = result.get("markdown", str(result))
                _persist_tool_result(tool_name, tool_markdown, session_id)
                yield tool_markdown

            _post_turn(profile, user_message, tool_markdown, session_id, active_session)
            return

    # Collect streamed response
    response_chunks: list[str] = []
    try:
        for chunk in generate_ai_response_streaming(
            profile, user_message, interface, session_id, provider, model
        ):
            response_chunks.append(chunk)
            yield chunk
    except Exception:
        _persist_user(user_message, session_id, cached_images)
        raise

    _persist_user(user_message, session_id, cached_images)

    full_response = _clean("".join(response_chunks)) or _EMPTY_RESPONSE_FALLBACK

    if is_markdown_image_shortcut(full_response):
        log.warning(
            "intercepted markdown image shortcut (stream): %s",
            extract_markdown_image_path(full_response),
        )
        yield IMAGE_SHORTCUT_WARNING
        return

    # Parse tool blocks
    commands, clean_text = parse_tool_blocks(full_response)

    if not commands:
        # Plain response - already streamed. Persist and finish.
        Database.add_message("assistant", full_response, session_id=session_id)
        _post_turn(profile, user_message, full_response, session_id, active_session)
        return

    log.info("[stream] found %d tool block(s)", len(commands))

    # Persist narration before tool execution
    if clean_text:
        Database.add_message("assistant", clean_text, session_id=session_id)

    # Execute all commands
    results = execute_commands(commands, session_id=session_id)

    # Yield each tool result
    tool_markdowns: list[str] = []
    any_image_tool = False

    for tool_name, result in results:
        tool_markdown = result.get("markdown", str(result))
        tool_markdowns.append(tool_markdown)
        _persist_tool_result(tool_name, tool_markdown, session_id)

        if parse_image_path(tool_markdown) is not None:
            any_image_tool = True

        yield "\n\n" + tool_markdown

    combined_tool_markdown = "\n\n".join(tool_markdowns)

    # Stream synthesis
    synthesis_chunks: list[str] = []
    full_synthesis = ""

    for chunk in _stream_synthesis(
        profile, session_id, interface, combined_tool_markdown
    ):
        synthesis_chunks.append(chunk)
        full_synthesis += chunk
        yield "\n\n" + chunk if any_image_tool and not synthesis_chunks[:-1] else chunk

    synthesis = _clean(full_synthesis) if full_synthesis else None

    if synthesis:
        Database.add_message("assistant", synthesis, session_id=session_id)
        final_response = (
            f"{combined_tool_markdown}\n\n{synthesis}" if any_image_tool else synthesis
        )
        _post_turn(profile, user_message, final_response, session_id, active_session)
    else:
        _post_turn(profile, user_message, combined_tool_markdown, session_id, active_session)
