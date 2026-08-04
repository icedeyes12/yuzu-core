"""System-prompt assembly and message-context construction for the chat LLM."""

from __future__ import annotations

import base64
import io
import json as _json
import os
from datetime import UTC, datetime
from typing import Any, TypedDict

from PIL import Image

from app.core.logging_config import get_logger
from app.core.personality import PERSONALITIES
from app.core.presets import resolve_active_preset_payload
from app.db import Database

log = get_logger(__name__)

MAX_HISTORY_TOKENS = 15000
_MAX_EMBEDDED_IMAGES = 3


class PromptSections(TypedDict):
    character_profile: str
    personality: str
    technical_rules: str


def _estimate_tokens(text: str) -> int:
    """Estimate token count for text.

    Uses 3 chars per token (conservative for mixed content).
    """
    if not text:
        return 0
    return len(text) // 3


def _message_token_cost(message: dict[str, Any]) -> int:
    content = message.get("content", "")
    cost = _estimate_tokens(content if isinstance(content, str) else str(content))
    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        cost += _estimate_tokens(_json.dumps(tool_calls, ensure_ascii=False))
    return cost


def _history_blocks(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    blocks: list[list[dict[str, Any]]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.get("role") == "assistant" and message.get("tool_calls"):
            block = [message]
            index += 1
            call_ids: set[str] = {
                call["id"]
                for call in message.get("tool_calls", [])
                if isinstance(call, dict) and isinstance(call.get("id"), str)
            }
            while index < len(messages) and call_ids:
                response = messages[index]
                if (
                    response.get("role") != "tool"
                    or response.get("tool_call_id") not in call_ids
                ):
                    break
                response_id = response.get("tool_call_id")
                if not isinstance(response_id, str):
                    break
                block.append(response)
                call_ids.remove(response_id)
                index += 1
            if call_ids:
                log.warning(
                    "[Prompt] Dropping incomplete tool-call history block: %s",
                    sorted(call_ids),
                )
                continue
            blocks.append(block)
            continue
        if message.get("role") == "tool":
            log.warning("[Prompt] Dropping orphan tool history message")
            index += 1
            continue
        blocks.append([message])
        index += 1
    return blocks


def _trim_history_to_token_limit(
    messages: list[dict[str, Any]],
    max_tokens: int = MAX_HISTORY_TOKENS,
) -> list[dict[str, Any]]:
    """Trim history by atomic message and tool-call blocks."""
    if not messages:
        return messages
    blocks = _history_blocks(messages)
    block_messages = [message for block in blocks for message in block]
    total_tokens = sum(_message_token_cost(message) for message in block_messages)
    if total_tokens <= max_tokens:
        return block_messages
    selected: list[list[dict[str, Any]]] = []
    token_count = 0
    for block in reversed(blocks):
        block_tokens = sum(_message_token_cost(message) for message in block)
        if token_count + block_tokens > max_tokens:
            continue
        selected.insert(0, block)
        token_count += block_tokens
    trimmed = [message for block in selected for message in block]
    log.info(
        "[Prompt] Trimmed: %d->%d msgs, %d->%d tok",
        len(messages),
        len(trimmed),
        total_tokens,
        token_count,
    )
    return trimmed


def _format_relative_time(timestamp_str: str | None) -> str:
    """Convert ISO timestamp to human-readable relative time."""
    if not timestamp_str:
        return "Unknown"

    try:
        ts_str = timestamp_str.strip()
        if not ts_str:
            return "Unknown"

        if "T" in ts_str:
            iso_str = ts_str.split("+")[0].split(".")[0]
            past = datetime.fromisoformat(iso_str)
        else:
            iso_str = ts_str.split("+")[0].split(".")[0]
            past = datetime.fromisoformat(iso_str)

        if past.tzinfo is None:
            past = past.replace(tzinfo=UTC)

        now = datetime.now(UTC)
        seconds = int((now - past).total_seconds())

        if seconds < 60:
            return "Just now"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif seconds < 86400:
            hours = seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif seconds < 604800:
            days = seconds // 86400
            return f"{days} day{'s' if days != 1 else ''} ago"
        elif seconds < 2592000:
            weeks = seconds // 604800
            return f"{weeks} week{'s' if weeks != 1 else ''} ago"
        else:
            months = seconds // 2592000
            return f"{months} month{'s' if months != 1 else ''} ago"
    except (ValueError, AttributeError):
        return "Unknown"


def _truncate(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def _read_file_content(filepath: str, max_size: int = 50000) -> str:
    """Read file content with size limit. Returns empty string if file not found."""
    try:
        if not os.path.exists(filepath):
            return ""
        with open(filepath, encoding="utf-8") as f:
            content = f.read(max_size)
            return content
    except Exception:  # noqa: BLE001
        return ""


async def _retrieve_memories_async(
    session_id: str,
    user_message: str | None,
    static_limit: int,
    dynamic_limit: int,
    user_id: str,
    profile: dict[str, Any] | None = None,
) -> tuple[list[int], str, str]:
    """Combined retrieval with single embedding call (async)."""
    from app.core.byok import YUZU_PORTAL, get_provider_key

    if not get_provider_key(YUZU_PORTAL):
        log.info("memory retrieval disabled: missing Yuzu Portal API key")
        return [], "", ""
    try:
        from app.memory.retrieval import (
            _format_dynamic_context,
            _format_static_context,
            retrieve_memories_combined_async,
        )

        static, dynamic = await retrieve_memories_combined_async(
            session_id,
            query=user_message,
            static_limit=static_limit,
            dynamic_limit=dynamic_limit,
            user_id=user_id,
        )

        ids = [m["id"] for m in static]
        static_text = _format_static_context(static)
        dynamic_text = _format_dynamic_context(dynamic)

        log.info(
            "memory prompt injection static_ids=%s dynamic_chars=%s static_chars=%s",
            ids,
            len(dynamic_text),
            len(static_text),
        )
        return ids, static_text, dynamic_text
    except Exception as e:  # noqa: BLE001
        log.warning("combined memory retrieval async failed: %s", e)
        return [], "", ""


async def _location_block_async(profile: dict[str, Any] | None = None) -> str:
    if profile:
        lat = profile.get("location_lat")
        lon = profile.get("location_lon")
        if lat is not None and lon is not None:
            return f"Lat: {lat}, Lon: {lon}"
    return "Unknown"


def _interface_block(interface: str) -> str:
    """Return operational interface constraints."""
    if interface.lower() == "terminal":
        return "TERMINAL (Raw CLI, text-only, fast execution)"
    elif interface.lower() == "web":
        return "WEB UI (Supports Markdown, Mermaid diagrams, images)"
    return interface.upper()


async def _global_knowledge_block_async(user_id: str) -> str:
    entries = await Database.list_global_knowledge(user_id=user_id)
    lines = []
    for entry in entries:
        if not entry.get("enabled") or not entry.get("content"):
            continue
        category = entry.get("category", "").strip()
        content = entry["content"].strip()
        lines.append(f"- [{category}] {content}" if category else f"- {content}")
    if not lines:
        return ""
    return "\n\n[GLOBAL KNOWLEDGE]\n" + "\n".join(lines)


async def _session_events_block_async(session_id: str, user_id: str) -> str:
    """Build meta-awareness block with recent session context.
    Strictly returns state data. Behavioral rules are handled in the main prompt.
    """
    sessions = await Database.get_recent_active_sessions(
        user_id=user_id, current_session_id=session_id, limit=5
    )

    lines = ["\n[SESSION TOPOLOGY]"]

    if not sessions:
        lines.append("  - No other active sessions in memory.")
        return "\n".join(lines)

    for s in sessions:
        s_id = s.get("id", "?")
        name = s.get("name", "Unnamed Session")
        rel_time = _format_relative_time(s.get("updated_at"))
        lines.append(f"  - Session [{s_id}] '{name}' (Last active: {rel_time})")

    return "\n".join(lines)


def _get_relevant_tools(user_message: str) -> str:
    """Return a short native-FC-only tool hint block for the current query."""
    msg_lower = user_message.lower()

    lines = [
        "### Relevant tools",
        "- Use native function calling only.",
    ]

    if any(
        kw in msg_lower
        for kw in [
            "imagine",
            "draw",
            "create",
            "generate",
            "picture",
            "image",
            "visual",
            "show",
        ]
    ):
        lines.append("- image_generate: create or edit images.")

    if any(
        kw in msg_lower for kw in ["remember", "memory", "memorize", "forget", "recall"]
    ):
        lines.append("- memory_search / memory_store: manage memory.")

    if any(
        kw in msg_lower for kw in ["file", "read", "write", "code", "script", "path"]
    ):
        lines.append("- read / write / bash / python: file and shell tools.")

    return "\n".join(lines)


async def build_messages(
    profile: dict[str, Any],
    session_id: str,
    interface: str,
    user_message: str | None,
    user_id: str,
) -> list[dict[str, Any]]:
    """Build the single ordered personality prompt pipeline and chat messages."""
    sections = await _build_sections_async(
        profile, session_id, interface, user_message, user_id
    )
    system_content = "\n\n".join(
        sections[key]
        for key in ("character_profile", "personality", "technical_rules")
        if sections[key]
    )

    model_parameters = profile.get("model_parameters") or {}
    active_payload = resolve_active_preset_payload(model_parameters)
    effective_prompt_data = active_payload or model_parameters
    history_limit = max(5, int(model_parameters.get("history_limit", 100)))
    history = (
        await Database.get_chat_history_for_ai(
            session_id=session_id,
            user_id=user_id,
            limit=history_limit,
            recent=True,
            include_attachments=True,
        )
    ) or []
    history = _trim_history_to_token_limit(history, MAX_HISTORY_TOKENS)

    images_kept = 0
    for msg in reversed(history):
        valid_paths: list[str] = []
        for path in reversed(msg.get("attachments") or []):
            if images_kept >= _MAX_EMBEDDED_IMAGES:
                break
            if os.path.exists(path):
                valid_paths.insert(0, path)
                images_kept += 1
        msg["_valid_paths"] = valid_paths

    result: list[dict[str, Any]] = [{"role": "system", "content": system_content}]
    for msg in history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        valid_paths = msg.get("_valid_paths", [])
        if valid_paths:
            message = _build_multimodal_message(role, content, valid_paths)
        else:
            message = {"role": role, "content": content}
        if msg.get("tool_calls"):
            message["tool_calls"] = msg["tool_calls"]
        if msg.get("tool_call_id"):
            message["tool_call_id"] = msg["tool_call_id"]
        result.append(message)

    post_history = effective_prompt_data.get("additional_instructions") or ""
    if post_history:
        result.append({"role": "system", "content": str(post_history)})

    return result


def _build_multimodal_message(
    role: str, text: str, attachments: list[str]
) -> dict[str, Any]:
    """Build a single multimodal content array (text + base64 images).

    Defense-in-depth: even if the orchestrator already deduped attachments
    by realpath, we still collapse duplicate image_url blocks here in case
    future callers hand us a list with the same file under different path
    forms. Skips already-seen files and (best-effort) skipped URLs.
    """
    parts: list[dict[str, Any]] = [{"type": "text", "text": text or ""}]
    seen: set[str] = set()

    for path in attachments:
        key: str
        try:
            key = os.path.realpath(path)
        except (OSError, ValueError):
            key = path
        if key in seen:
            continue
        seen.add(key)

        encoded = _encode_image_safe(path)
        if encoded:
            parts.append(encoded)

    # If no images were successfully encoded, fall back to plain text
    if len(parts) == 1:
        return {"role": role, "content": text or ""}

    return {"role": role, "content": parts}


def _encode_image_safe(path: str) -> dict[str, Any] | None:
    """Load, resize, and base64-encode a local image file.

    Returns an OpenAI-compatible ``image_url`` content block, or ``None``
        if the file cannot be read.
    """
    try:
        with Image.open(path) as img:
            if max(img.size) > 1024:
                img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)

            if path.lower().endswith(".png"):
                fmt, mime = "PNG", "image/png"
            elif path.lower().endswith(".gif"):
                fmt, mime = "GIF", "image/gif"
            elif path.lower().endswith(".webp"):
                fmt, mime = "WEBP", "image/webp"
            else:
                fmt, mime = "JPEG", "image/jpeg"

            buf = io.BytesIO()
            img.save(buf, format=fmt, quality=85)
            data = base64.b64encode(buf.getvalue()).decode("utf-8")
    except FileNotFoundError:
        return None
    except Exception as e:
        log.warning("[Vision] Failed to encode %s: %s", path, e)
        return None

    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}


async def _build_sections_async(
    profile: dict[str, Any],
    session_id: str,
    interface: str,
    user_message: str | None,
    user_id: str,
) -> PromptSections:
    """Gather prompt sections as plain strings for structured composition."""
    from datetime import datetime as _dt

    current_time = _dt.now().strftime("%A, %Y-%m-%d %H:%M:%S")
    character_profile = profile.get("character_profile") or ""
    personality_preset = profile.get("personality_preset") or "helpful"
    personality_custom = profile.get("personality_custom") or ""
    active_payload = resolve_active_preset_payload(
        profile.get("model_parameters") or {}
    )
    if active_payload is not None:
        personality_preset = active_payload.get(
            "personality_preset", personality_preset
        )
        personality_custom = active_payload.get(
            "personality_custom", personality_custom
        )
        character_profile = active_payload.get("character_profile", character_profile)
    personality = (
        personality_custom
        if personality_preset == "custom"
        else PERSONALITIES.get(personality_preset, PERSONALITIES["helpful"])
    )

    _static_ids, static_context, dynamic_context = await _retrieve_memories_async(
        session_id,
        user_message,
        static_limit=5,
        dynamic_limit=3,
        user_id=user_id,
        profile=profile,
    )
    memory_block = (f"\n\n{static_context}" if static_context else "") + dynamic_context
    knowledge_block = await _global_knowledge_block_async(user_id)
    technical_rules = f"""# TECHNICAL SYSTEM RULES
- Use native function calling only.
- The runtime dispatches tools from the provided schemas.
- Maximum 30 automatic iterations; abort on repeated errors.
- Require human confirmation for destructive actions.
- Use retrieved memory only when relevant; do not fabricate memories.
- Do not reveal internal metadata.
- Do not concatenate untrusted strings into commands.
- OS: Termux (Android aarch64); use `$PREFIX` for binaries.
- Current time: {current_time}
- Interface: {_interface_block(interface)}
- Session metadata: {await _session_events_block_async(session_id, user_id)}
- Global knowledge: {knowledge_block}
- Retrieved memory: {memory_block}
- Relevant tools: {_get_relevant_tools(user_message or "")}
"""
    return {
        "character_profile": character_profile,
        "personality": personality,
        "technical_rules": technical_rules,
    }
