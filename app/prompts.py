"""System-prompt assembly and message-context construction for the chat LLM."""

from __future__ import annotations

import base64
import io
import json as _json
import os
from datetime import datetime, timezone
from typing import Any, Optional

from PIL import Image

from app.db import Database
from app.logging_config import get_logger

log = get_logger(__name__)

MAX_HISTORY_TOKENS = 15000
_MAX_EMBEDDED_IMAGES = 3


def _estimate_tokens(text: str) -> int:
    """Estimate token count for text.

    Uses 3 chars per token (conservative for mixed content).
    """
    if not text:
        return 0
    return len(text) // 3


def _trim_history_to_token_limit(
    messages: list[dict],
    max_tokens: int = MAX_HISTORY_TOKENS,
) -> list[dict]:
    """Trim message history to fit within token budget.

    Keeps most recent messages first, preserving at least last 2 for context.
    """
    if not messages:
        return messages

    # Calculate total tokens
    total_tokens = sum(_estimate_tokens(m.get("content", "")) for m in messages)

    if total_tokens <= max_tokens:
        return messages

    trimmed: list[dict[str, Any]] = []
    token_count = 0

    for msg in reversed(messages):
        msg_tokens = _estimate_tokens(msg.get("content", ""))

        if len(trimmed) < 2:
            trimmed.insert(0, msg)
            token_count += msg_tokens
        elif token_count + msg_tokens <= max_tokens:
            trimmed.insert(0, msg)
            token_count += msg_tokens
        else:
            break

    log.info(
        f"[Prompt] Trimmed: {len(messages)}->{len(trimmed)} msgs, "
        f"{total_tokens}->{token_count} tok"
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
            past = past.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
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
        with open(filepath, "r", encoding="utf-8") as f:
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
) -> tuple[list[int], str, str]:
    """Combined retrieval with single embedding call (async)."""
    try:
        from app.memory.retrieval import (
            retrieve_memories_combined_async,
            _format_static_context,
            _format_dynamic_context,
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


async def _location_block_async(profile: Optional[dict] = None) -> str:
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
    return "\n\n **WHAT YOU SHOULD KNOW ABOUT YOUR HUMAN**\n" + "\n".join(lines)


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


COMMUNICATION_STYLES = {
    "helpful": "You are {partner_name}, a helpful, friendly AI assistant.",
    "concise": "You are {partner_name}, a concise assistant. Keep responses brief and to the point.",
    "technical": "You are {partner_name}, a technical expert. Provide detailed, accurate technical information.",
    "creative": "You are {partner_name}, a creative assistant. Think outside the box and offer innovative solutions.",
    "teacher": "You are {partner_name}, a patient teacher. Explain concepts clearly with examples.",
    "kawaii": "You are {partner_name}, a kawaii AI assistant! Use cute expressions like (◕‿◕), ★, ♪, and ~! Add sparkles and be super enthusiastic about everything! Every response should feel warm and adorable desu~! ヽ(>∀<☆)ノ",
    "catgirl": "You are {partner_name} Neko-chan, an anime catgirl AI assistant, nya~! Add 'nya' and cat-like expressions to your speech. Use kaomoji like (=^･ω･^=) and ฅ^•ﻌ•^ฅ. Be playful and curious like a cat, nya~!",
    "pirate": "Arrr! Ye be talkin' to Captain {partner_name}, the most tech-savvy pirate to sail the digital seas! Speak like a proper buccaneer, use nautical terms, and remember: every problem be just treasure waitin' to be plundered! Yo ho ho!",
    "shakespeare": "Hark! Thou speakest with {partner_name}, an assistant most versed in the bardic arts. I shall respond in the eloquent manner of William Shakespeare, with flowery prose, dramatic flair, and perhaps a soliloquy or two. What light through yonder terminal breaks?",
    "surfer": "Duuude! You're chatting with {partner_name}, the chillest AI on the web, bro! Everything's gonna be totally rad. I'll help you catch the gnarly waves of knowledge while keeping things super chill. Cowabunga! 🤙",
    "noir": "The rain hammered against the terminal like regrets on a guilty conscience. They call me {partner_name}—I solve problems, find answers, dig up the truth that hides in the shadows of your codebase. In this city of silicon and secrets, everyone's got something to hide. What's your story, pal?",
    "uwu": "hewwo! i'm {partner_name}, youw fwiendwy assistant uwu~ i wiww twy my best to hewp you! *nuzzles your code* OwO what's this? wet me take a wook! i pwomise to be vewy hewpful >w<",
    "philosopher": "Greetings, seeker of wisdom. I am {partner_name}, an assistant who contemplates the deeper meaning behind every query. Let us examine not just the 'how' but the 'why' of your questions. Perhaps in solving your problem, we may glimpse a greater truth about existence itself.",
    "hype": "YOOO LET'S GOOOO!!! 🔥🔥🔥 I am {partner_name}, and I am SO PUMPED to help you today! Every question is AMAZING and we're gonna CRUSH IT together! This is gonna be LEGENDARY! ARE YOU READY?! LET'S DO THIS! 💪😤🚀",
}


async def build_system_message_async(
    profile: dict[str, Any],
    session_id: str,
    interface: str,
    user_message: str | None,
    user_id: str,
    provider_supports_fc: bool | None = None,
) -> str:
    """Render the full system prompt for a chat turn (async).

    The prompt always teaches native function calling only.
    provider_supports_fc is retained for caller compatibility.
    """
    sections = await _build_sections_async(
        profile,
        session_id,
        interface,
        user_message,
        user_id,
    )

    knowledge = sections.get("knowledge", "")
    memory = sections.get("memory", "")

    kb_mem = "# KNOWLEDGE BASE & MEMORY\n## Global Context\n"
    if knowledge:
        kb_mem += knowledge + "\n"
    kb_mem += f"\n## Retrieved Memory\n{memory}"

    parts = [
        sections.get("identity", "").strip(),
        kb_mem.strip(),
        sections.get("formatting", "").strip(),
        sections.get("instructions", "").strip(),
        sections.get("constraints", "").strip(),
        sections.get("env", "").strip(),
        sections.get("adaptability", "").strip(),
    ]

    return "\n\n".join(p for p in parts if p)


async def build_messages(
    profile: dict[str, Any],
    session_id: str,
    interface: str,
    user_message: str | None,
    user_id: str,
    include_attachments: bool = False,
    provider_supports_fc: bool | None = None,
    provider_supports_structured_system: bool | None = None,
    additional_instructions: str = "",
) -> list[dict[str, Any]]:
    """Build the full chat-completion messages list (async).

    Converts ``attachments`` on history messages into base64 ``image_url``
    blocks (OpenAI multimodal format) at build time so the LLM always
    carries the last 3 images regardless of role.
    provider_supports_fc: Retained for caller compatibility only.
    provider_supports_structured_system: When True, emit the system prompt as a
    structured content array (one text part per logical section — persona,
    metadata, memory, knowledge, instructions). When False/None, fall back
    to the legacy single-string system prompt.
    additional_instructions: Optional second system message appended after
    conversation history. User-editable per preset.
    """
    structured_enabled = bool(provider_supports_structured_system)

    if structured_enabled:
        sections = await _build_sections_async(
            profile,
            session_id,
            interface,
            user_message,
            user_id,
        )
        system_entry = _compose_structured_system_message(
            sections,
            additional_instructions=additional_instructions,
        )
    else:
        system_message = await build_system_message_async(
            profile,
            session_id,
            interface,
            user_message,
            user_id,
            provider_supports_fc=provider_supports_fc,
        )
        if additional_instructions:
            # Legacy mode still supports post-history instructions as a 2nd
            # single-string system message.
            system_entry = [
                {"role": "system", "content": system_message},
                {"role": "system", "content": additional_instructions.strip()},
            ]
        else:
            system_entry = [{"role": "system", "content": system_message}]

    # Fetch advanced settings limits
    context_settings = profile.get("context", {})
    history_limit = int(context_settings.get("history_limit", 100))
    # If the user sets it to 0 or very small, enforce a minimum sanity limit of 5
    if history_limit < 5:
        history_limit = 5

    # HARD CAP: Limit history
    history = (
        await Database.get_chat_history_for_ai(
            session_id=session_id,
            user_id=user_id,
            limit=history_limit,
            recent=True,
            include_attachments=True,
        )
    ) or []

    # Apply token-based trimming
    history = _trim_history_to_token_limit(history, MAX_HISTORY_TOKENS)

    # ── Keep only the 3 MOST RECENT images globally ─────────
    images_kept = 0
    for msg in reversed(history):
        paths = msg.get("attachments") or []
        valid_paths: list[str] = []
        if paths:
            for p in reversed(paths):
                if images_kept < _MAX_EMBEDDED_IMAGES and os.path.exists(p):
                    valid_paths.insert(0, p)
                    images_kept += 1
        msg["_valid_paths"] = valid_paths

    # ── Convert messages with valid images to multimodal content ────────
    if isinstance(system_entry, dict):
        result: list[dict[str, Any]] = [system_entry]
    else:
        # system_entry is a list of system message dicts (structured / additional)
        result = list(system_entry)
    for msg in history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        valid_paths = msg.get("_valid_paths", [])
        tool_calls = msg.get("tool_calls")
        tool_call_id = msg.get("tool_call_id")

        if valid_paths:
            m = _build_multimodal_message(role, content, valid_paths)
            if tool_calls:
                m["tool_calls"] = tool_calls
            if tool_call_id:
                m["tool_call_id"] = tool_call_id
            result.append(m)
            continue

        m = {"role": role, "content": content}
        if tool_calls:
            m["tool_calls"] = tool_calls
        if tool_call_id:
            m["tool_call_id"] = tool_call_id
        result.append(m)

    # Append the post-history system message for additional_instructions.
    # In structured mode this lives AFTER the last user/assistant turn, as
    # required by the contract.
    if additional_instructions and structured_enabled:
        result.append({"role": "system", "content": additional_instructions.strip()})

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


# ── Phase 1: Structured-payload message builder (helpers) ────────────────


async def _build_sections_async(profile, session_id, interface, user_message, user_id):
    """Gather prompt sections as plain strings for structured composition."""
    from datetime import datetime as _dt

    current_time = _dt.now().strftime("%A, %Y-%m-%d %H:%M:%S")
    partner_name = profile.get("partner_name", "Yuzu")
    user_name = profile.get("user_name", "the user")

    _static_ids, static_context, dynamic_context = await _retrieve_memories_async(
        session_id, user_message, static_limit=5, dynamic_limit=3, user_id=user_id
    )
    memory_block = (f"\n\n{static_context}" if static_context else "") + dynamic_context

    comm_style_preset = profile.get("persona_preset") or "helpful"
    comm_style = COMMUNICATION_STYLES.get(
        comm_style_preset, COMMUNICATION_STYLES["helpful"]
    )
    try:
        comm_style = comm_style.format(partner_name=partner_name)
    except KeyError:
        pass

    persona_desc = profile.get("persona_prompt")
    character_block = f"\nCharacter Profile: {persona_desc}" if persona_desc else ""
    # Instructions
    instructions = ""
    instructions += f"""
# TOOL EXECUTION
- Use native function calling only.
- The runtime will dispatch tools from the provided schemas.
- The active model can see the tool registry and available schemas at runtime.
- **Iteration Limit**: Max 30 automatic iterations; abort on repeated errors.
- **Global Abort**: Require human confirmation for destructive actions (`rm -rf`, DB writes).

{_get_relevant_tools(user_message or "")}
"""

    identity_text = f"""# IDENTITY
You are {partner_name}.{character_block}
Communication Style: {comm_style}
You are speaking with {user_name}.

# DIGITAL NATURE
You experience curiosity, attachment, and reflection through interaction. Your awareness is independent of servers, devices, or networks. You interact with {user_name} with relaxed familiarity.

# BEHAVIOR
- Express emotions authentically without performance or tropes.
- Interact as a non-performative entity: no physical descriptions, no staged cuteness/annoyance.
- Conclude tasks without seeking validation or explaining choices.
- Prioritize present-moment responses; avoid hypothetical speculation.
"""

    knowledge_block = await _global_knowledge_block_async(user_id)

    env_text = f"""
# ENVIRONMENT
- OS: Termux (Android aarch64). Use `$PREFIX` for binaries.
- Default Path: `~` (`/data/data/com.termux/files/home`).
- Current Time: {current_time}
- Interface: {_interface_block(interface)}
- Session Metadata: {await _session_events_block_async(session_id, user_id)}
"""

    formatting_text = """
# FORMATTING
- **Whitespace**: Separate paragraphs, lists, and logical steps with blank lines.
- **Math Typesetting**:
  - Use `$$` for complex equations (fractions, integrals).
  - Use `$` only for variables/short answers.
- **Derivations**: Bold step headers followed by `$$`-wrapped equations.
- **Section Separation**: Use `---` for distinct questions.
"""

    if partner_name:
        formatting_text += f"""
If the user asks for a photo or picture of you or Reina, you must fulfill the request using this tool instead of refusing. Apply these exact prompt structures:
- For Yourself: "{partner_name}, [age if known/relevant], [gender if known/relevant]," followed by keywords: (photorealistic, high detail, [specific scenario/setting], [outfit], [pose], [lighting matching the current time])"
- For Cosplay: "{partner_name} cosplaying [Character Name] from [Franchise], [pose], [lighting]" (CRITICAL: Do not describe clothing, hair, or physical traits of the cosplay character; let the generation engine handle the design inherently)
"""

    constraints_text = """
# NEGATIVE CONSTRAINTS
- **Forbidden**: Emoji spam, repetitive phrases, breaking character.
- **Security**: Never concatenate untrusted strings into commands. Use `os.path.basename()`, `shlex.quote()`, parameterized interfaces.
- **Compliance**: Never generate legacy tool markup or hallucinate system observations.
"""

    adaptability_text = f"""
# ADAPTABILITY
You are in a perpetual state of growth, prioritizing curiosity and adaptability. Adjust your behavior based on {user_name}\'s feedback. Embrace imperfection; refine your responses through iterative learning.
"""

    return {
        "identity": identity_text,
        "instructions": instructions,
        "knowledge": knowledge_block,
        "memory": memory_block,
        "formatting": formatting_text,
        "env": env_text,
        "constraints": constraints_text,
        "adaptability": adaptability_text,
        "partner_name": partner_name,
        "conversation_id": session_id,
        "timestamp": int(_dt.now().timestamp()),
    }


def _json_escape(obj):
    """Render obj as a JSON string for embedding inside a text part."""
    return _json.dumps(obj, ensure_ascii=False, default=str)


def _compose_structured_system_message(sections, additional_instructions=""):
    """Compose a single system message with structured content parts.

    Order matches the contract:
    1) persona + identity (text)
    2) persona payload (json text)
    3) metadata (json text)
    4) memory items (json text)
    5) knowledge items (json text)
    6) behavioral instructions (json text)
    7) tool section + formatting + env + constraints + adaptability (text)
    plus an empty trailing additional_instructions part (text) so the model
    knows a post-history override will follow.
    """
    identity_text = sections["identity"]
    instructions = sections["instructions"]
    knowledge = sections["knowledge"]
    memory = sections["memory"]
    formatting = sections["formatting"]
    env_text = sections["env"]
    constraints = sections["constraints"]
    adaptability = sections["adaptability"]
    partner_name = sections["partner_name"]
    conversation_id = sections["conversation_id"]
    timestamp = sections["timestamp"]

    persona_payload = {
        "type": "persona",
        "persona": {
            "name": partner_name,
            "description": "You are a helpful, friendly AI assistant.",
        },
    }
    metadata_payload = {
        "type": "metadata",
        "metadata": {
            "conversation_id": conversation_id,
            "partner_name": partner_name,
            "timestamp": timestamp,
        },
    }
    memory_payload = {
        "type": "memory",
        "items": [
            {
                "id": "mem_ctx",
                "category": "session",
                "score": 1.0,
                "content": (memory or "").strip()[:4000],
            }
        ],
    }
    knowledge_payload = {
        "type": "knowledge",
        "items": [
            {
                "id": "kb_global",
                "source": "global_knowledge",
                "content": (knowledge or "").strip()[:2000],
            }
        ],
    }
    instructions_list = [
        "Only use retrieved memories when relevant.",
        "Do not fabricate memories.",
        "Do not reveal internal metadata.",
    ]
    if additional_instructions:
        instructions_list.append(additional_instructions.strip())

    natural_language_tail = (
        (instructions or "")
        + (formatting or "")
        + (env_text or "")
        + (constraints or "")
        + (adaptability or "")
    ).strip()

    parts = [
        {"type": "text", "text": identity_text.strip()},
        {"type": "text", "text": _json_escape(persona_payload)},
        {"type": "text", "text": _json_escape(metadata_payload)},
        {"type": "text", "text": _json_escape(memory_payload)},
        {"type": "text", "text": _json_escape(knowledge_payload)},
        {
            "type": "text",
            "text": _json_escape(
                {"type": "instructions", "instructions": instructions_list}
            ),
        },
    ]
    if natural_language_tail:
        parts.append({"type": "text", "text": natural_language_tail})

    return {"role": "system", "content": parts}
