# FILE: app/orchestrator.py
# DESCRIPTION: Single entrypoint for handling user messages.
#              Coordinates: LLM call -> tool detection -> tool exec -> synthesis.

from __future__ import annotations

import re
from typing import Any, Iterator

from app.commands import (
    IMAGE_SHORTCUT_WARNING,
    StreamFilter,
    detect_command,
    execute_command,
    extract_markdown_image_path,
    is_markdown_image_shortcut,
    parse_image_path,
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
_NESTED_COMMAND_PREFIXES = ("/request", "/imagine")
_EMPTY_RESPONSE_FALLBACK = "I'm having trouble responding right now. Please try again."
_MD_IMAGE_PATTERN = re.compile(r"!\[[^\]]{0,200}\]\(([^)]{1,200})\)")


# ---------------------------------------------------------------------------
# Image-cache helpers (used to attach uploaded/markdown images to user msgs)
# ---------------------------------------------------------------------------


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
            
            # Security: validate path is within allowed directories
            # Prevent path traversal attacks
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


# ---------------------------------------------------------------------------
# Native tool-call helpers
# ---------------------------------------------------------------------------

def _parse_raw_tool_calls(
    provider_name: str, raw_response: dict | None
) -> list[dict]:
    """Parse tool_calls from a raw provider API response.

    Returns list of {"name": str, "arguments": dict} for each tool call.
    """
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
            break  # terminal tool succeeded, stop processing
    return results


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


def _load_image_base64(image_path: str) -> tuple[str | None, str | None]:
    """Return (base64, mime) for a generated image file, or (None, None)."""
    import base64
    from pathlib import Path

    # Resolve base directory (where the app runs from)
    BASE_DIR = Path(__file__).resolve().parent.parent

    if not image_path:
        return None, None
    
    # Resolve absolute path
    abs_path = BASE_DIR / image_path
    if not abs_path.exists():
        log.warning("image not found: %s (resolved: %s)", image_path, abs_path)
        return None, None
    
    try:
        data = base64.b64encode(abs_path.read_bytes()).decode("utf-8")
    except OSError as e:
        log.warning("image read failed (%s): %s", abs_path, e)
        return None, None
    
    mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
    return data, mime


# ---------------------------------------------------------------------------
# Response post-processing
# ---------------------------------------------------------------------------


def _strip_command_line(text: str, cmd_info: dict[str, str]) -> str:
    """Remove the first /command line from response, return narration text.
    
    Used to separate the LLM's narration/acknowledgment from its tool invocation.
    """
    if not text or not cmd_info:
        return text or ""
    
    lines = text.split("\n")
    full_cmd = cmd_info.get("full_command", "")
    
    # Remove first line if it matches the command
    if lines and lines[0].strip() == full_cmd:
        lines = lines[1:]
    
    return "\n".join(lines).strip()


def _strip_all_command_lines(text: str, commands: list[dict[str, str]]) -> str:
    """Remove all /command lines from response, return narration text.
    
    Used for batch command execution to extract narration before commands.
    """
    if not text or not commands:
        return text or ""
    
    # Collect all full_command strings to remove
    full_cmds = {cmd.get("full_command", "") for cmd in commands if cmd.get("full_command")}
    
    # Filter out lines that match any command
    lines = text.split("\n")
    filtered = [line for line in lines if line.strip() not in full_cmds]
    
    return "\n".join(filtered).strip()


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


def _strip_nested_commands(text: str) -> str:
    """Remove leading-slash command lines from a synthesis response."""
    return "\n".join(
        line
        for line in text.split("\n")
        if not line.strip().startswith(_NESTED_COMMAND_PREFIXES)
    )


# ---------------------------------------------------------------------------
# Synthesis pass (2nd LLM call after a tool ran)
# ---------------------------------------------------------------------------


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
    """Run a 2nd LLM pass to narrate around the tool result.

    Returns the cleaned synthesis text, or None when the LLM returned nothing.
    """
    # Build image context from tool output (e.g., /imagine results)
    image_context = _build_image_context(tool_markdown, session_id)
    
    text, _ = generate_ai_response(
        profile, "", interface, session_id, image_content_for_context=image_context
    )
    if not text or not text.strip():
        return None

    cleaned = _clean(text)
    nested = detect_command(cleaned)
    if nested:
        log.info("executing nested command: /%s", nested["command"])
        tool_name, nested_result = execute_command(nested, session_id=session_id)
        nested_md = nested_result.get("markdown", str(nested_result))
        _persist_tool_result(tool_name, nested_md, session_id)
        cleaned = nested_md
    return cleaned


def _stream_synthesis(
    profile: dict[str, Any],
    session_id: int,
    interface: str,
    tool_markdown: str,
) -> Iterator[tuple[str, str]]:
    """Stream the 2nd LLM pass.

    Yields (chunk, full_so_far) tuples. The orchestrator can pass `chunk`
    straight to the consumer and persist `full_so_far` once the stream ends.
    On nested-command detection we fall back to the non-streaming
    _run_synthesis path because nested execution is structural, not a
    streaming concern.
    """
    # Build image context from tool output (e.g., /imagine results)
    image_context = _build_image_context(tool_markdown, session_id)
    
    sf = StreamFilter()
    accumulated: list[str] = []
    for chunk in generate_ai_response_streaming(
        profile, "", interface, session_id,
        image_content_for_context=image_context,
    ):
        for safe in sf.feed(chunk):
            accumulated.append(safe)
            yield safe, "".join(accumulated)
    for safe in sf.flush():
        accumulated.append(safe)
        yield safe, "".join(accumulated)


# ---------------------------------------------------------------------------
# Per-turn side effects
# ---------------------------------------------------------------------------

# Throttle: only check pipeline every Nth message (reduces gate checks by 80%)
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
    except Exception as e:  # noqa: BLE001
        log.warning("memory pipeline trigger failed: %s", e)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def handle_user_message(user_message: str, interface: str = "terminal") -> str:
    """Process a user message end-to-end and return the assistant reply.

    Guarantees:
      - Exactly ONE primary LLM call per turn (plus optional synthesis pass).
      - At most ONE tool execution per turn.
      - At most ONE synthesis pass (with one level of nested-command recursion).
      - Final response is never empty.
      - Image tools are terminal: no plain-text synthesis without the image.
    """
    profile = Database.get_profile()
    if not user_message.strip():
        return "Please enter a message!"

    active_session = Database.get_active_session()
    session_id = active_session["id"]
    cached_images = _cache_images_from_message(user_message)

    # Fast-path: user typed /imagine directly — execute tool without LLM round-trip
    stripped = user_message.strip()
    if stripped.startswith("/imagine"):
        prompt = stripped[len("/imagine"):].strip()
        if prompt:
            from app.commands import _TOOL_ALIASES, _parse_args
            from app.tools.registry import execute_tool
            raw_name = "imagine"
            tool_name = _TOOL_ALIASES.get(raw_name, raw_name)
            args = _parse_args(raw_name, prompt)
            tool_result = execute_tool(tool_name, args, session_id=session_id)
            tool_markdown = tool_result.get("markdown", str(tool_result))
            _persist_tool_result(tool_name, tool_markdown, session_id)
            _post_turn(profile, user_message, tool_markdown, session_id, active_session)
            return tool_markdown
        else:
            return "Please provide a prompt after /imagine. Example: /imagine a cute anime cat"

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
        # Detect commands with full-text scan for naked commands
        cmd_info = detect_command(text_response, scan_mode="all_naked")
        if not cmd_info:
            Database.add_message("assistant", text_response, session_id=session_id)
            _post_turn(profile, user_message, text_response, session_id, active_session)
            return text_response

        # Check if batch (list) or single (dict)
        is_batch = isinstance(cmd_info, list)
        commands = cmd_info if is_batch else [cmd_info]

        # /command path - persist narration BEFORE tool execution
        narration = _strip_all_command_lines(text_response, commands) if is_batch else _strip_command_line(text_response, cmd_info)
        if narration:
            Database.add_message("assistant", narration, session_id=session_id)

        # Execute all commands in batch
        tool_results_raw = execute_command(cmd_info, session_id=session_id)
        
        # Normalize to list for consistent processing
        if not is_batch:
            tool_results_raw = [tool_results_raw]
        
        # Process all tool results
        tool_markdowns: list[str] = []
        any_image_tool = False
        for tool_name, tool_result in tool_results_raw:
            tool_markdown = tool_result.get("markdown", str(tool_result))
            tool_markdowns.append(tool_markdown)
            _persist_tool_result(tool_name, tool_markdown, session_id)
            if parse_image_path(tool_markdown) is not None:
                any_image_tool = True

        # Combine all tool markdowns
        combined_tool_markdown = "\n\n".join(tool_markdowns)

        # Single synthesis with all results combined
        synthesis = _run_synthesis(
            profile, session_id, interface, combined_tool_markdown
        )

        if synthesis:
            Database.add_message("assistant", synthesis, session_id=session_id)
            final_response = (
                f"{combined_tool_markdown}\n\n{synthesis}" if any_image_tool else synthesis
            )
            _post_turn(profile, user_message, final_response, session_id, active_session)
            return final_response

        _post_turn(profile, user_message, combined_tool_markdown, session_id, active_session)
        return combined_tool_markdown


def handle_user_message_streaming(
    user_message: str,
    interface: str = "terminal",
    provider: str | None = None,
    model: str | None = None,
) -> Iterator[str]:
    """Streaming entrypoint with true incremental chunk delivery.

    Behavior:
      - If user message starts with /imagine: execute tool directly, stream result.
      - Buffers chunks only until a leading /command on the first
        line can be confirmed or ruled out.
      - When NO command: streams every subsequent chunk live.
      - When a /command IS detected: suppresses the command line, executes
        the tool, emits the tool result, then streams the synthesis pass
        live.
    """
    profile = Database.get_profile()
    if not user_message.strip():
        yield "Please enter a message!"
        return

    active_session = Database.get_active_session()
    session_id = active_session["id"]
    cached_images = _cache_images_from_message(user_message)

    # Fast-path: user typed /imagine directly — execute tool without LLM round-trip
    stripped = user_message.strip()
    if stripped.startswith("/imagine"):
        prompt = stripped[len("/imagine"):].strip()
        if prompt:
            from app.commands import _TOOL_ALIASES, _parse_args
            from app.tools.registry import execute_tool
            raw_name = "imagine"
            tool_name = _TOOL_ALIASES.get(raw_name, raw_name)
            args = _parse_args(raw_name, prompt)
            tool_result = execute_tool(tool_name, args, session_id=session_id)
            tool_markdown = tool_result.get("markdown", str(tool_result))
            _persist_tool_result(tool_name, tool_markdown, session_id)
            yield tool_markdown
            _post_turn(profile, user_message, tool_markdown, session_id, active_session)
            return
        else:
            yield "Please provide a prompt after /imagine. Example: /imagine a cute anime cat"
            return

    sf = StreamFilter()
    visible_chunks: list[str] = []
    try:
        for chunk in generate_ai_response_streaming(
            profile, user_message, interface, session_id, provider, model
        ):
            for safe in sf.feed(chunk):
                visible_chunks.append(safe)
                yield safe
        for safe in sf.flush():
            visible_chunks.append(safe)
            yield safe
    except Exception:
        _persist_user(user_message, session_id, cached_images)
        raise

    _persist_user(user_message, session_id, cached_images)

    full_response = _clean(sf.full_text) or _EMPTY_RESPONSE_FALLBACK
    visible_response = _clean("".join(visible_chunks))

    log.info("[stream] full_response=%r, sf.command=%s, len=%d",
             full_response[:200], sf.command, len(full_response))

    if is_markdown_image_shortcut(full_response):
        log.warning(
            "intercepted markdown image shortcut (stream): %s",
            extract_markdown_image_path(full_response),
        )
        yield IMAGE_SHORTCUT_WARNING
        return

    # Fallback: detect commands with full-text scan for naked commands
    cmd_info = sf.get_commands(scan_mode="all_naked")
    if not cmd_info:
        cmd_info = sf.command

    if not cmd_info:
        # Plain response - already streamed live. Persist and finish.
        text = visible_response or _EMPTY_RESPONSE_FALLBACK
        Database.add_message("assistant", text, session_id=session_id)
        _post_turn(profile, user_message, text, session_id, active_session)
        return

    # Check if batch (list) or single (dict)
    is_batch = isinstance(cmd_info, list)
    commands = cmd_info if is_batch else [cmd_info]

    # Tool path - persist narration BEFORE executing the detected command(s).
    # visible_response has first command line stripped by StreamFilter (if on first line).
    # For batch commands found mid-text, strip all command lines.
    if is_batch:
        narration = _strip_all_command_lines(full_response, commands)
    else:
        narration = visible_response.strip() if visible_response else ""
    
    if narration:
        Database.add_message("assistant", narration, session_id=session_id)

    # Execute all commands in batch
    tool_results_raw = execute_command(cmd_info, session_id=session_id)
    
    # Normalize to list for consistent processing
    if not is_batch:
        tool_results_raw = [tool_results_raw]
    
    # Process all tool results and yield each
    tool_markdowns: list[str] = []
    any_image_tool = False
    for tool_name, tool_result in tool_results_raw:
        tool_markdown = tool_result.get("markdown", str(tool_result))
        tool_markdowns.append(tool_markdown)
        _persist_tool_result(tool_name, tool_markdown, session_id)
        if parse_image_path(tool_markdown) is not None:
            any_image_tool = True
        # Yield each tool result
        yield "\n\n" + tool_markdown

    # Combine all tool markdowns for synthesis
    combined_tool_markdown = "\n\n".join(tool_markdowns)

    # Single synthesis with all results combined
    synthesis_chunks: list[str] = []
    full_synthesis = ""
    yielded_synthesis_header = False
    try:
        for chunk, full in _stream_synthesis(
            profile, session_id, interface, combined_tool_markdown
        ):
            synthesis_chunks.append(chunk)
            full_synthesis = full
            if not yielded_synthesis_header:
                yield "\n\n" + chunk if any_image_tool else chunk
                yielded_synthesis_header = True
            else:
                yield chunk
    except Exception as e:  # noqa: BLE001
        log.warning("synthesis stream failed, no narration yielded: %s", e)

    synthesis = _clean(full_synthesis) if full_synthesis else None

    if synthesis:
        Database.add_message("assistant", synthesis, session_id=session_id)
        final_response = (
            f"{combined_tool_markdown}\n\n{synthesis}" if any_image_tool else synthesis
        )
        _post_turn(profile, user_message, final_response, session_id, active_session)
    else:
        _post_turn(profile, user_message, combined_tool_markdown, session_id, active_session)
