# FILE: app/profile_analysis.py
# DESCRIPTION: Memory summarization, global player-profile analysis, and
#              the small helpers (normalization, merging, parsing) that
#              support them. All Chutes calls go through chutes_chat().

from __future__ import annotations

import os
import random
import re
import traceback
from datetime import datetime
from typing import Any

from app.db import Database
from app.llm_client import chutes_chat
from app.logging_config import get_logger

log = get_logger(__name__)

_IMPORTANT_KEYWORDS = (
    "love",
    "hate",
    "important",
    "always",
    "never",
    "forever",
    "remember",
)
_IDLE_THRESHOLD_HOURS = 1
_SUMMARY_TRIGGER_INTERVAL = 100

_SUMMARY_MODEL = "google/gemma-4-31B-turbo-TEE"
_SUMMARY_FALLBACKS = ("Qwen/Qwen3-235B-A22B-Instruct-2507-TEE",)
_GLOBAL_FREE_FALLBACKS = (
    "google/gemini-2.0-flash-exp:free",
    "deepseek/deepseek-chat-v3.1:free",
    "qwen/qwen3-235b-a22b:free",
)

_MEMORY_LIST_LIMITS: dict[str, int] = {
    "likes": 30,
    "dislikes": 30,
    "personality_traits": 15,
    "important_memories": 20,
}

_SECTION_PATTERNS: dict[str, str] = {
    "Player Summary:": "player_summary",
    "Player Summary": "player_summary",
    "Summary:": "player_summary",
    "Summary": "player_summary",
    "Likes:": "likes",
    "Likes": "likes",
    "Interests:": "likes",
    "Interests": "likes",
    "Dislikes:": "dislikes",
    "Dislikes": "dislikes",
    "Aversions:": "dislikes",
    "Personality Traits:": "personality_traits",
    "Personality Traits": "personality_traits",
    "Traits:": "personality_traits",
    "Personality:": "personality_traits",
    "Important Memories:": "important_memories",
    "Important Memories": "important_memories",
    "Memories:": "important_memories",
    "Key Memories:": "important_memories",
    "Relationship Dynamics:": "relationship_dynamics",
    "Relationship Dynamics": "relationship_dynamics",
    "Relationship:": "relationship_dynamics",
    "Dynamics:": "relationship_dynamics",
}


# ---------------------------------------------------------------------------
# Per-session summary (used by both terminal and web)
# ---------------------------------------------------------------------------


def detect_important_content(message: str) -> bool:
    lower = message.lower()
    return any(keyword in lower for keyword in _IMPORTANT_KEYWORDS)


def _idle_hours(session_memory: dict[str, Any]) -> float | None:
    last = session_memory.get("last_message_time")
    if not last:
        return None
    try:
        return (datetime.now() - datetime.fromisoformat(last)).total_seconds() / 3600.0
    except ValueError:
        return None


def should_summarize_memory(
    profile: dict[str, Any], user_message: str, session_id: int
) -> bool:
    history = Database.get_chat_history(session_id=session_id) or []
    convo_count = sum(1 for m in history if m["role"] in ("user", "assistant"))

    if (
        convo_count >= _SUMMARY_TRIGGER_INTERVAL
        and convo_count % _SUMMARY_TRIGGER_INTERVAL == 0
    ):
        session_memory = Database.get_session_memory(session_id) or {}
        if convo_count > session_memory.get("last_summary_count", 0):
            idle = _idle_hours(session_memory)
            if idle is not None and idle < _IDLE_THRESHOLD_HOURS:
                log.info(
                    "skipping summary: idle %.1fh < %sh", idle, _IDLE_THRESHOLD_HOURS
                )
                return False
            return True

    return detect_important_content(user_message)


def _format_recent_conversation(history: list[dict[str, Any]], limit: int = 100) -> str:
    parts = []
    for msg in history[-limit:]:
        role = "User" if msg["role"] == "user" else "AI"
        parts.append(f"{role}: {msg['content']}")
    return "\n".join(parts)


def summarize_memory(
    profile: dict[str, Any],
    user_message: str,
    ai_reply: str,
    session_id: int,
) -> bool:
    history = Database.get_chat_history(session_id=session_id, limit=80) or []
    if not history:
        return False

    convo_count = sum(1 for m in history if m["role"] in ("user", "assistant"))
    api_key = (Database.get_api_keys() or {}).get("openrouter")
    if not api_key:
        return False

    prompt = f"""
Write ONE paragraph summarizing the current conversation context in this session.

Recent Conversation:
{_format_recent_conversation(history)}

Current Interaction:
User: {user_message}
AI: {ai_reply}

Write one concise paragraph (3-5 sentences) summarizing what this session is about,
the current topics being discussed, and the general context. No lists, no bullet points,
just a natural paragraph.
""".strip()

    paragraph = chutes_chat(
        prompt,
        api_key=api_key,
        model=_SUMMARY_MODEL,
        system=(
            "You write concise, natural paragraphs summarizing conversation context. "
            "One paragraph only."
        ),
        title="Yuzu-Session-Context",
        max_tokens=500,
        temperature=0.2,
        timeout=60,
        fallback_models=_SUMMARY_FALLBACKS,
    )
    if not paragraph:
        return False

    Database.update_session_memory(
        session_id,
        {
            "session_context": paragraph.strip(),
            "last_summarized": datetime.now().isoformat(),
            "last_summary_count": convo_count,
            "last_message_time": datetime.now().isoformat(),
        },
    )

    _sync_episodic_to_db(session_id, paragraph.strip(), history)
    return True


def _sync_episodic_to_db(
    session_id: int, summary: str, history: list[dict[str, Any]]
) -> None:
    try:
        from app.memory.extractor import (
            calculate_emotional_weight,
            create_episodic_memory,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("structured-DB sync skipped: %s", e)
        return

    recent = history[-20:]
    try:
        emotional = calculate_emotional_weight(recent)
        importance = 0.5 + emotional * 0.3
        create_episodic_memory(
            session_id,
            summary,
            emotional,
            importance,
            source_message_ids=[m["id"] for m in recent],
        )
    except Exception as e:  # noqa: BLE001
        log.warning("sync episodic to DB failed: %s", e)


# ---------------------------------------------------------------------------
# Memory list normalization / merging
# ---------------------------------------------------------------------------


def normalize_memory_item(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text.strip().lower())
    return cleaned.rstrip(".,\"'")


def merge_and_clean_memory(
    existing: list[str], new_items: list[str], max_size: int
) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in (*existing, *new_items):
        if not item or not item.strip():
            continue
        norm = normalize_memory_item(item)
        if norm and norm not in seen:
            seen.add(norm)
            result.append(item)
    return result[:max_size]


def _merge_profile_data(
    existing_memory: dict[str, Any], new_data: dict[str, Any]
) -> dict[str, Any]:
    if not existing_memory:
        return new_data

    result = existing_memory.copy()

    new_summary = new_data.get("player_summary") or ""
    existing_summary = result.get("player_summary") or ""
    if new_summary and len(new_summary) > len(existing_summary) * 1.5:
        result["player_summary"] = new_summary
        log.info(
            "updated player summary (new=%d, old=%d chars)",
            len(new_summary),
            len(existing_summary),
        )

    if new_data.get("relationship_dynamics"):
        result["relationship_dynamics"] = new_data["relationship_dynamics"]

    new_facts = new_data.get("key_facts") or {}
    if new_facts:
        result_facts = result.setdefault(
            "key_facts",
            {k: [] for k in _MEMORY_LIST_LIMITS},
        )
        for category, limit in _MEMORY_LIST_LIMITS.items():
            existing_items = result_facts.get(category) or []
            incoming = new_facts.get(category) or []
            existing_norms = {
                normalize_memory_item(i) for i in existing_items if i and i.strip()
            }
            added = sum(
                1
                for i in incoming
                if i and i.strip() and normalize_memory_item(i) not in existing_norms
            )
            result_facts[category] = merge_and_clean_memory(
                existing_items, incoming, limit
            )
            if added:
                log.info("added %d new items to %s", added, category)

    result["last_global_summary"] = new_data.get("last_global_summary", "")
    result["sessions_analyzed"] = new_data.get("sessions_analyzed", 0)
    return result


# ---------------------------------------------------------------------------
# Global profile analysis (LLM-driven)
# ---------------------------------------------------------------------------


def _select_session_messages(
    messages: list[dict[str, Any]],
    max_per_session: int,
    recent_ratio: float,
    min_length: int,
) -> tuple[list[dict[str, Any]], str]:
    filtered = [
        m
        for m in messages
        if m["role"] in ("user", "assistant")
        and len(m["content"].strip()) >= min_length
    ]
    if not filtered:
        return [], "none"

    if len(filtered) <= max_per_session:
        return filtered, "all"

    recent_count = int(max_per_session * recent_ratio)
    random_count = max_per_session - recent_count
    recent_msgs = filtered[-recent_count:]
    older_msgs = filtered[:-recent_count]

    if older_msgs and random_count > 0:
        sample = random.sample(older_msgs, min(random_count, len(older_msgs)))
        return recent_msgs + sample, f"recent+random ({recent_count}+{len(sample)})"
    return recent_msgs, f"recent only ({len(recent_msgs)})"


def _build_global_analysis_prompt(conversation_text: str) -> str:
    return f"""# PLAYER PROFILE ANALYSIS TASK

## CONVERSATION HISTORY:
Below is the complete conversation history between the User and AI across multiple sessions.

{conversation_text}

## ANALYSIS INSTRUCTIONS:
You are an expert psychologist and data analyst. Your task is to analyze the conversation history above and extract deep insights about the User.

### FOCUS AREAS:
1. **Personality Analysis**: Identify core personality traits, communication style, emotional patterns
2. **Interests & Preferences**: What does the user like/dislike? Topics they frequently discuss
3. **Behavioral Patterns**: How do they interact? Response patterns, engagement style
4. **Relationship Dynamics**: How is their relationship with the AI? Emotional tone, trust level, interaction patterns, and development over time.

### OUTPUT FORMAT REQUIREMENTS:
You MUST use this exact format. Do not add any commentary, explanations, or additional text.

Player Summary: [Provide a comprehensive summary of the user's personality, interests, and overall interaction patterns. Be specific and evidence-based.]

Likes: [Provide specific likes, interests, or positive preferences. Format as comma-separated list.]

Dislikes: [Provide specific dislikes, aversions, or negative preferences. Format as comma-separated list.]

Personality Traits: [Provide personality characteristics. Use descriptive adjectives.]

Important Memories: [List significant memories, experiences, or topics that were emotionally important or frequently mentioned.]

Relationship Dynamics: [Provide analysis of the relationship dynamics between User and AI. Include emotional tone, trust level, interaction patterns, and development over time.]

### CRITICAL RULES:
- Base EVERYTHING on evidence from the conversations
- Be specific and concrete - avoid vague statements
- No markdown formatting, no bullet points, no numbering
- Follow the EXACT format above - no additional sections"""


def _global_analysis_call(prompt: str, api_key: str) -> str | None:
    system = (
        "You are an expert psychologist and data analyst specializing in conversation "
        "analysis. Your task is to extract deep, meaningful insights from conversation "
        "history. Read and comprehend the ENTIRE conversation history, identify "
        "patterns and significant moments, and follow the output format EXACTLY as "
        "specified."
    )
    primary = chutes_chat(
        prompt,
        api_key=api_key,
        model=_SUMMARY_MODEL,
        system=system,
        title="Yuzu-Global-Profile",
        max_tokens=4000,
        temperature=0.2,
        timeout=300,
    )
    if primary:
        return primary

    log.warning("primary global-profile model failed, trying free fallbacks")
    shortened = (
        prompt[:15000] + "\n\n...[analysis limited due to free tier constraints]"
    )
    return chutes_chat(
        shortened,
        api_key=api_key,
        model=_GLOBAL_FREE_FALLBACKS[0],
        system="Extract key insights from conversation history. Focus on most important patterns.",
        title="Yuzu-Global-Profile",
        max_tokens=2000,
        temperature=0.3,
        timeout=300,
        fallback_models=_GLOBAL_FREE_FALLBACKS[1:],
    )


def summarize_global_player_profile() -> bool:
    """Analyze ALL conversation history across ALL sessions and update the profile."""
    sessions = Database.get_all_sessions() or []
    log.info("global profile analysis: %d sessions", len(sessions))

    max_per_session = 2000
    max_chars = 900000
    recent_ratio = 0.7
    min_length = 5

    sorted_sessions = sorted(
        sessions, key=lambda s: s.get("created_at", ""), reverse=True
    )

    blocks: list[str] = []
    total_messages = 0

    for session in sorted_sessions:
        sid = session["id"]
        name = session.get("name") or f"Session {sid}"
        messages = Database.get_chat_history(session_id=sid, limit=None) or []
        if not messages:
            continue
        selected, method = _select_session_messages(
            messages, max_per_session, recent_ratio, min_length
        )
        if not selected:
            continue

        lines: list[str] = []
        for msg in selected:
            role = "User" if msg["role"] == "user" else "AI"
            content = msg["content"].strip()
            if len(content) > 400:
                content = content[:400] + "..."
            lines.append(f"{role}: {content}")
            total_messages += 1

        header = (
            f"\n\n=== SESSION: {name} ===\n"
            f"[Total: {len(messages)} msgs | Selected: {len(selected)} | Method: {method}]\n"
        )
        blocks.append(header + "\n".join(lines))

    if not blocks:
        log.info("no conversations available for analysis")
        return False

    conversation_text = "".join(blocks)
    while len(conversation_text) > max_chars and len(blocks) > 1:
        blocks.pop(0)
        conversation_text = "".join(blocks)
        log.info("trimmed oldest session, now %d chars", len(conversation_text))

    api_key = Database.get_api_key("chutes")
    if not api_key:
        log.error("no chutes API key configured")
        return False

    summary_text = _global_analysis_call(
        _build_global_analysis_prompt(conversation_text), api_key
    )
    if not summary_text:
        log.error("global profile analysis returned nothing")
        return False

    _save_debug_log(summary_text, len(blocks), total_messages, len(conversation_text))

    parsed = parse_global_profile_summary(summary_text)
    parsed["last_global_summary"] = datetime.now().isoformat()
    parsed["sessions_analyzed"] = len(blocks)
    parsed["total_messages"] = total_messages
    parsed["analysis_chars"] = len(conversation_text)

    profile = Database.get_profile() or {}
    merged = _merge_profile_data(profile.get("memory") or {}, parsed)
    try:
        Database.update_profile({"memory": merged})
    except Exception as e:  # noqa: BLE001
        log.error("profile update failed: %s", e)
        traceback.print_exc()
        return False

    log.info(
        "global profile updated: %d sessions, %d msgs, %d chars",
        len(blocks),
        total_messages,
        len(conversation_text),
    )
    return True


def _save_debug_log(
    summary_text: str, sessions: int, messages: int, chars: int
) -> None:
    try:
        os.makedirs("debug_logs", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join("debug_logs", f"profile_summary_{timestamp}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("=== GLOBAL PROFILE ANALYSIS ===\n")
            f.write(f"Date: {timestamp}\nSessions: {sessions}\n")
            f.write(f"Messages: {messages}\nChars: {chars}\n")
            f.write("\n=== RAW ANALYSIS ===\n")
            f.write(summary_text)
    except OSError as e:
        log.warning("debug log write failed: %s", e)


# ---------------------------------------------------------------------------
# Profile-summary parser
# ---------------------------------------------------------------------------


def _detect_section(line: str) -> tuple[str | None, str]:
    for pattern, key in _SECTION_PATTERNS.items():
        if line.startswith(pattern):
            return key, line[len(pattern) :].strip()
    return None, line


def parse_global_profile_summary(summary_text: str) -> dict[str, Any]:
    profile_data: dict[str, Any] = {
        "player_summary": "",
        "key_facts": {
            "likes": [],
            "dislikes": [],
            "personality_traits": [],
            "important_memories": [],
        },
        "relationship_dynamics": "",
        "last_updated": datetime.now().isoformat(),
    }

    cleaned_text = summary_text.replace("\r\n", "\n").replace("\r", "\n")
    current_section: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if not (current_section and buffer):
            return
        content = " ".join(buffer).strip()
        if current_section in ("player_summary", "relationship_dynamics"):
            profile_data[current_section] = content
        elif current_section in profile_data["key_facts"]:
            profile_data["key_facts"][current_section] = [
                item.strip() for item in content.split(",") if item.strip()
            ]

    for raw_line in cleaned_text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        section, remaining = _detect_section(line)
        if section is not None:
            flush()
            current_section = section
            buffer = [remaining] if remaining else []
        elif current_section:
            buffer.append(line)
    flush()

    for key in ("player_summary", "relationship_dynamics"):
        text = profile_data[key].strip()
        if text.endswith("."):
            text = text[:-1]
        profile_data[key] = text

    for key in profile_data["key_facts"]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in profile_data["key_facts"][key]:
            if item and item not in seen:
                seen.add(item)
                deduped.append(item)
        profile_data["key_facts"][key] = deduped

    return profile_data
