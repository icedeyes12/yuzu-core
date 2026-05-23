# FILE: app/orchestrator.py
# DESCRIPTION: Single entrypoint for handling user messages.
#              Implements Thought → Action → Observation agentic loop.
#              Uses <tool>...</tool> protocol for tool invocation.

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Iterator

from app.commands import (
    IMAGE_SHORTCUT_WARNING,
    execute_commands,
    extract_markdown_image_path,
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
from app.tools.registry import get_tool_role
from app.visual_context import store_visual_context

log = get_logger(__name__)

_TIMESTAMP_SUFFIX = re.compile(r"\s*\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\s*$")
_EMPTY_RESPONSE_FALLBACK = "I'm having trouble responding right now. Please try again."
_MD_IMAGE_PATTERN = re.compile(r"!\[[^\]]{0,200}\]\(([^)]{1,200})\)")

# Services
from app.services.session_service import SessionService
from app.services.memory_service import MemoryService

# Maximum orchestration loops to prevent runaway execution
_MAX_ORCHESTRATION_LOOPS = 30

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
    """Resolve any image references in *message* to local cache paths, with validation."""
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
    import base64

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


def _parse_raw_tool_calls(provider_name: str, raw_response: dict | None) -> list[dict]:
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
        return [
            {"name": c["name"], "arguments": c["arguments"]}
            for c in calls
            if c.get("name")
        ]
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


def _persist_user(message: str, session_id: int, image_paths: list[str] | None) -> None:
    Database.add_message(
        "user", message, session_id=session_id, image_paths=image_paths or None
    )


def _persist_assistant(content: str, session_id: int, image_paths: list[str] | None = None) -> None:
    """Persist an assistant response, with optional image paths (for image generation)."""
    Database.add_message("assistant", content, session_id=session_id, image_paths=image_paths)


def _persist_tool_result(tool_name: str, markdown: str, session_id: int) -> None:
    """Persist a tool result, extracting and saving any generated image paths."""
    from app.commands import parse_image_path
    
    image_paths = []
    path = parse_image_path(markdown)
    if path:
        image_paths.append(path)
        
    Database.add_message(get_tool_role(tool_name), markdown, session_id=session_id, image_paths=image_paths or None)


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
        profile,
        "",
        interface,
        session_id,
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
    # Auto-rename via service
    SessionService.auto_name_session_if_needed(session_id, active_session)
    
    # Memory checks via service
    MemoryService.run_per_message_checks(
        profile, user_message, final_response, session_id, active_session
    )

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
    # DEPRECATED: use MemoryService.trigger_pipeline
    MemoryService.trigger_pipeline(session_id)


# --------------------------------------------------------------------
# Public entry points
# --------------------------------------------------------------------


def handle_user_message(user_message: str, interface: str = "terminal") -> str:
    """Process a user message end-to-end and return the assistant reply.

    Non-streaming path for CLI and simple API calls.
    For tool execution with agentic loop, use handle_user_message_streaming().
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
            
            # Extract any generated image paths
            generated_paths = []
            for tm in tool_markdowns:
                path = parse_image_path(tm)
                if path:
                    generated_paths.append(path)

            # Run synthesis
            synthesis = _run_synthesis(profile, session_id, interface, combined)
            if synthesis:
                # DEPRECATED: image_paths are now primarily tracked in the tool_result message
                # but we keep them here for backward compatibility with synthesis context
                _persist_assistant(synthesis, session_id, generated_paths)
                final = (
                    f"{combined}\n\n{synthesis}"
                    if parse_image_path(combined)
                    else synthesis
                )
            else:
                final = combined

            _post_turn(profile, user_message, final, session_id, active_session)
            return final

    provider_name = (profile.get("providers_config") or {}).get(
        "preferred_provider", "ollama"
    )

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
    tool_calls = _parse_raw_tool_calls(provider_name, raw_api_response)
    if tool_calls:
        tool_results = _execute_tool_calls(tool_calls, session_id)
        if tool_results:
            tool_name, tool_result = tool_results[0]
            tool_markdown = tool_result.get("markdown", str(tool_result))
            _persist_tool_result(tool_name, tool_markdown, session_id)

            is_image_tool = parse_image_path(tool_markdown) is not None
            generated_paths = [parse_image_path(tool_markdown)] if is_image_tool else None
            
            synthesis = _run_synthesis(profile, session_id, interface, tool_markdown)

            if synthesis:
                # DEPRECATED: image_paths are now primarily tracked in the tool_result message
                _persist_assistant(synthesis, session_id, generated_paths)
                final_response = (
                    f"{tool_markdown}\n\n{synthesis}" if is_image_tool else synthesis
                )
                _post_turn(
                    profile, user_message, final_response, session_id, active_session
                )
                return final_response

            _post_turn(profile, user_message, tool_markdown, session_id, active_session)
            return tool_markdown

    # Non-streaming path: just return LLM response
    # Tool execution via <tool> blocks only happens in streaming path
    _persist_assistant(text_response, session_id)
    _post_turn(profile, user_message, text_response, session_id, active_session)
    return text_response


def handle_user_message_streaming(
    user_message: str,
    interface: str = "terminal",
    provider: str | None = None,
    model: str | None = None,
    abort_check: callable[[], bool] | None = None,
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

    # Check for early abort
    if abort_check and abort_check():
        log.info("[stream] early abort for session")
        return

    active_session = Database.get_active_session()
    session_id = active_session["id"]
    cached_images = _cache_images_from_message(user_message)

    # STRICT: Persist user message immediately to ensure it's in history even if process crashes
    _persist_user(user_message, session_id, cached_images)

    # Fast-path: user typed /imagine directly
    stripped = user_message.strip()
    if stripped.startswith("/imagine ") or stripped.startswith("<tool>"):
        commands, _ = parse_tool_blocks(stripped)
        if commands or stripped.startswith("/imagine"):
            if stripped.startswith("/imagine"):
                commands = [stripped]

            results = execute_commands(commands, session_id=session_id)

            tool_markdown = ""
            for tool_name, result in results:
                tool_markdown = result.get("markdown", str(result))
                _persist_tool_result(tool_name, tool_markdown, session_id)
                yield tool_markdown

            _post_turn(profile, user_message, tool_markdown, session_id, active_session)
            return

    # Collect streamed response
    response_chunks: list[str] = []
    assistant_msg_id = Database.add_message("assistant", "", session_id=session_id)
    last_db_update = time.time()
    
    try:
        for chunk in generate_ai_response_streaming(
            profile, user_message, interface, session_id, provider, model
        ):
            if chunk:
                # Check for cancellation
                if abort_check and abort_check():
                    log.info("[stream] aborting during first pass")
                    if response_chunks:
                        Database.update_message(assistant_msg_id, "".join(response_chunks))
                    return

                response_chunks.append(chunk)
                
                # Periodically update DB to ensure state recovery on reconnect
                now = time.time()
                if now - last_db_update > 2.0: # Every 2 seconds
                    Database.update_message(assistant_msg_id, "".join(response_chunks))
                    last_db_update = now
                    
                yield chunk
    except Exception as e:
        log.error("[stream] error in first pass: %s", e)
        # Ensure partial response is saved even on error
        if response_chunks:
            Database.update_message(assistant_msg_id, "".join(response_chunks))
        raise

    # Final update for this pass
    full_response = "".join(response_chunks)
    Database.update_message(assistant_msg_id, full_response)

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
        # Plain response - already streamed and persisted.
        _post_turn(profile, user_message, full_response, session_id, active_session)
        return

    log.info("[stream] found %d tool block(s)", len(commands))

    # Full response with tool blocks is already persisted in assistant_msg_id

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

    # Agentic loop: execute tools, stream synthesis, check for more tools
    current_synthesis_context = combined_tool_markdown
    # Track paths across loops
    all_generated_paths = []
    for tm in tool_markdowns:
        p = parse_image_path(tm)
        if p:
            all_generated_paths.append(p)
        
    loop_count = 0
    
    while loop_count < _MAX_ORCHESTRATION_LOOPS:
        loop_count += 1
        log.info("[stream] orchestration loop %d", loop_count)
        
        # Check for cancellation
        if abort_check and abort_check():
            log.info("[stream] aborting orchestration loop")
            return

        # Stream synthesis
        synthesis_chunks: list[str] = []
        full_synthesis = ""
        synthesis_msg_id = None # Lazy created
        last_synth_update = time.time()

        try:
            for chunk in _stream_synthesis(
                profile, session_id, interface, current_synthesis_context
            ):
                if chunk:
                    # Check for cancellation
                    if abort_check and abort_check():
                        log.info("[stream] aborting during synthesis")
                        if full_synthesis and synthesis_msg_id:
                            Database.update_message(synthesis_msg_id, full_synthesis)
                        return

                    synthesis_chunks.append(chunk)
                    full_synthesis += chunk
                    
                    # Lazy create message row
                    if synthesis_msg_id is None:
                        synthesis_msg_id = Database.add_message("assistant", "", session_id=session_id)

                    # Periodic update
                    now = time.time()
                    if now - last_synth_update > 2.0:
                        Database.update_message(synthesis_msg_id, full_synthesis)
                        last_synth_update = now
                        
                    yield "\n\n" + chunk if any_image_tool and not synthesis_chunks[:-1] else chunk
        except Exception as e:
            log.error("[stream] error in synthesis loop: %s", e)
            if full_synthesis:
                Database.update_message(synthesis_msg_id, full_synthesis)
            raise

        synthesis = _clean(full_synthesis) if full_synthesis else None
        
        # Final update
        if full_synthesis and synthesis_msg_id:
            # Check if this loop generated images to attach to the assistant message
            # All generated paths from this loop and previous ones are in all_generated_paths
            # DEPRECATED: image_paths population in update_message is now the primary way to track images
            Database.update_message(synthesis_msg_id, full_synthesis, image_paths=all_generated_paths)

        if not synthesis:
            # No synthesis - already handled persistence above if any chunks existed
            _post_turn(
                profile, user_message, current_synthesis_context, session_id, active_session
            )
            return

        # Synthesis already persisted in synthesis_msg_id
        
        # Check if synthesis contains more tool blocks
        if not has_tool_blocks(synthesis):
            # No more tools - we're done
            final_response = (
                f"{current_synthesis_context}\n\n{synthesis}" if any_image_tool else synthesis
            )
            _post_turn(profile, user_message, final_response, session_id, active_session)
            return

        log.info("[stream] synthesis contains tool blocks, continuing loop")
        
        # Parse and execute tools from synthesis
        next_commands, _ = parse_tool_blocks(synthesis)
        if not next_commands:
            _post_turn(profile, user_message, synthesis, session_id, active_session)
            return

        # Execute tools
        next_results = execute_commands(next_commands, session_id=session_id)
        next_markdowns: list[str] = []
        any_image_tool = False

        for tool_name, result in next_results:
            tm = result.get("markdown", str(result))
            next_markdowns.append(tm)
            _persist_tool_result(tool_name, tm, session_id)
            p = parse_image_path(tm)
            if p:
                any_image_tool = True
                all_generated_paths.append(p)
            yield "\n\n" + tm

        # Update context for next synthesis
        current_synthesis_context = "\n\n".join(next_markdowns)

    # Max loops reached
    log.warning("[stream] max orchestration loops reached (%d)", _MAX_ORCHESTRATION_LOOPS)
    _post_turn(profile, user_message, synthesis or current_synthesis_context, session_id, active_session)
