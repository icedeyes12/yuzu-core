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
    import os
    if not os.path.exists(image_path):
        log.warning("image not found: %s", image_path)
        return None, None
    try:
        with open(image_path, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
    except OSError as e:
        log.warning("image read failed (%s): %s", image_path, e)
        return None, None
    mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
    return data, mime


# ---------------------------------------------------------------------------
# Response post-processing
# ---------------------------------------------------------------------------


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
    is_image_tool: bool,
) -> str | None:
    """Run a 2nd LLM pass to narrate around the tool result.

    Returns the cleaned synthesis text, or None when the LLM returned nothing.
    """
    image_context: list[dict[str, Any]] | None = None
    if is_image_tool:
        image_context = _build_image_context(tool_markdown, session_id)

    text, _ = generate_ai_response(
        profile, "", interface, session_id, image_content_for_context=image_context
    )
    if not text or not text.strip():
        return None

    cleaned = _clean(text)
    nested = detect_command(cleaned)
    if nested:
        if is_image_tool:
            log.info("ignoring nested command in image synthesis")
            cleaned = _strip_nested_commands(cleaned)
        else:
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
    is_image_tool: bool,
) -> Iterator[tuple[str, str]]:
    """Stream the 2nd LLM pass.

    Yields (chunk, full_so_far) tuples. The orchestrator can pass `chunk`
    straight to the consumer and persist `full_so_far` once the stream ends.
    On nested-command detection we fall back to the non-streaming
    _run_synthesis path because nested execution is structural, not a
    streaming concern.
    """
    image_context: list[dict[str, Any]] | None = None
    if is_image_tool:
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
    _trigger_memory_pipeline(session_id)


def _trigger_memory_pipeline(session_id: int) -> None:
    try:
        from app.memory.memory import trigger_memory_pipeline_async
        session_memory = Database.get_session_memory(session_id) or {}
        count = session_memory.get("message_count", 0)
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

    try:
        raw_response, _ = generate_ai_response(
            profile, user_message, interface, session_id
        )
    except Exception:
        _persist_user(user_message, session_id, cached_images)
        raise

    _persist_user(user_message, session_id, cached_images)

    if raw_response is None:
        log.error("AI provider returned None")
        return ""

    raw_response = _clean(raw_response) or _EMPTY_RESPONSE_FALLBACK

    if is_markdown_image_shortcut(raw_response):
        log.warning(
            "intercepted markdown image shortcut: %s",
            extract_markdown_image_path(raw_response),
        )
        return IMAGE_SHORTCUT_WARNING

    cmd_info = detect_command(raw_response)
    if not cmd_info:
        Database.add_message("assistant", raw_response, session_id=session_id)
        _post_turn(profile, user_message, raw_response, session_id, active_session)
        return raw_response

    # Tool path
    tool_name, tool_result = execute_command(cmd_info, session_id=session_id)
    tool_markdown = tool_result.get("markdown", str(tool_result))
    _persist_tool_result(tool_name, tool_markdown, session_id)

    is_image_tool = parse_image_path(tool_markdown) is not None
    synthesis = _run_synthesis(
        profile, session_id, interface, tool_markdown, is_image_tool
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


def handle_user_message_streaming(
    user_message: str,
    interface: str = "terminal",
    provider: str | None = None,
    model: str | None = None,
) -> Iterator[str]:
    """Streaming entrypoint with true incremental chunk delivery.

    Behavior:
      - Buffers chunks only until a leading /command can be ruled out
        (typically the first 1-3 chunks).
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

    if is_markdown_image_shortcut(full_response):
        log.warning(
            "intercepted markdown image shortcut (stream): %s",
            extract_markdown_image_path(full_response),
        )
        yield IMAGE_SHORTCUT_WARNING
        return

    if not sf.command:
        # Plain response - already streamed live. Persist and finish.
        text = visible_response or _EMPTY_RESPONSE_FALLBACK
        Database.add_message("assistant", text, session_id=session_id)
        _post_turn(profile, user_message, text, session_id, active_session)
        return

    # Tool path - the command line was suppressed during streaming.
    tool_name, tool_result = execute_command(sf.command, session_id=session_id)
    tool_markdown = tool_result.get("markdown", str(tool_result))
    _persist_tool_result(tool_name, tool_markdown, session_id)
    yield "\n\n" + tool_markdown

    is_image_tool = parse_image_path(tool_markdown) is not None
    synthesis_chunks: list[str] = []
    full_synthesis = ""
    yielded_synthesis_header = False
    try:
        for chunk, full in _stream_synthesis(
            profile, session_id, interface, tool_markdown, is_image_tool
        ):
            synthesis_chunks.append(chunk)
            full_synthesis = full
            if not yielded_synthesis_header:
                yield "\n\n" + chunk if is_image_tool else chunk
                yielded_synthesis_header = True
            else:
                yield chunk
    except Exception as e:  # noqa: BLE001
        log.warning("synthesis stream failed, no narration yielded: %s", e)

    synthesis = _clean(full_synthesis) if full_synthesis else None

    if synthesis:
        Database.add_message("assistant", synthesis, session_id=session_id)
        final_response = (
            f"{tool_markdown}\n\n{synthesis}" if is_image_tool else synthesis
        )
        _post_turn(profile, user_message, final_response, session_id, active_session)
    else:
        _post_turn(profile, user_message, tool_markdown, session_id, active_session)
