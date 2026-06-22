from __future__ import annotations

from datetime import datetime
from typing import Any

from app.db import Database
from app.providers import get_ai_manager
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
_SUMMARY_FALLBACKS = ("Qwen/Qwen3-235B-A22B-Thinking-2507",)


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


async def should_summarize_memory_async(
    profile: dict[str, Any], user_message: str, session_id: str
) -> bool:
    history = await Database.get_chat_history_async(session_id=session_id) or []
    convo_count = sum(1 for m in history if m["role"] in ("user", "assistant"))

    if (
        convo_count >= _SUMMARY_TRIGGER_INTERVAL
        and convo_count % _SUMMARY_TRIGGER_INTERVAL == 0
    ):
        session_memory = await Database.get_session_memory_async(session_id) or {}
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


async def summarize_memory_async(
    profile: dict[str, Any],
    user_message: str,
    ai_reply: str,
    session_id: str,
    user_id: str | None = None,
) -> bool:
    history = (
        await Database.get_chat_history_async(session_id=session_id, limit=80, user_id=user_id) or []
    )
    if not history:
        return False

    convo_count = sum(1 for m in history if m["role"] in ("user", "assistant"))

    manager = await get_ai_manager()
    chutes = manager.providers.get("chutes")
    api_key = chutes.api_key if chutes else None

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

    paragraph = await chutes_chat(
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

    await Database.update_session_memory_async(
        session_id,
        {
            "session_context": paragraph.strip(),
            "last_summarized": datetime.now().isoformat(),
            "last_summary_count": convo_count,
            "last_message_time": datetime.now().isoformat(),
        },
    )

    await _sync_episodic_to_db_async(session_id, paragraph.strip(), history)
    return True


async def _sync_episodic_to_db_async(
    session_id: str, summary: str, history: list[dict[str, Any]]
) -> None:
    try:
        from app.memory.extractor import (
            calculate_emotional_weight,
            create_episodic_memory_async,
        )
    except Exception as e:
        log.warning("structured-DB sync skipped: %s", e)
        return

    recent = history[-20:]
    try:
        # Assuming calculate_emotional_weight is CPU bound but small
        emotional = calculate_emotional_weight(recent)
        importance = 0.5 + emotional * 0.3
        await create_episodic_memory_async(
            session_id,
            summary,
            emotional,
            importance,
            source_message_ids=[m["id"] for m in recent],
        )
    except Exception as e:
        log.warning("sync episodic to DB failed: %s", e)
