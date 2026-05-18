# FILE: app/session_lifecycle.py
# DESCRIPTION: Session start/end + auto-naming using a small LLM helper.

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.database import Database
from app.llm_client import chutes_chat
from app.logging_config import get_logger

log = get_logger(__name__)

_AUTO_NAME_TRIGGER_COUNT = 10
_AUTO_NAME_TRUNCATE = 40
_AUTO_NAME_MODEL = "google/gemma-4-31B-turbo-TEE"


class _NoopContext:
    def __enter__(self) -> "_NoopContext":
        return self

    def __exit__(self, *_: Any) -> None:
        return None


# Public alias retained for any third-party caller that imported UserContext.
UserContext = _NoopContext


# ---------------------------------------------------------------------------
# Auto-naming
# ---------------------------------------------------------------------------


def _auto_name_via_llm(conversation_summary: str, api_key: str) -> str | None:
    prompt = (
        "Based on this conversation, create a SHORT session title (max 6 words):\n\n"
        f"{conversation_summary}\n\n"
        "Reply with ONLY the title, nothing else."
    )
    name = chutes_chat(
        prompt,
        api_key=api_key,
        model=_AUTO_NAME_MODEL,
        title="Yuzu-Session-Naming",
        max_tokens=64,
    )
    if not name:
        return None
    cleaned = name.replace('"', "").replace("'", "").strip()
    return (cleaned[:50] + "...") if len(cleaned) > 50 else cleaned


def _auto_name_from_history(session_id: int) -> str | None:
    history = Database.get_chat_history(session_id, limit=5) or []
    for msg in history:
        if msg["role"] == "user" and len(msg["content"].strip()) > 10:
            text = msg["content"].strip()
            short = text[:_AUTO_NAME_TRUNCATE]
            return short + "..." if len(text) > _AUTO_NAME_TRUNCATE else short
    return None


def auto_name_session_if_needed(
    session_id: int, active_session: dict[str, Any]
) -> None:
    """Rename a 'New Chat' session once it has reached the trigger count."""
    if active_session.get("name") != "New Chat":
        return
    if Database.get_session_messages_count(session_id) < _AUTO_NAME_TRIGGER_COUNT:
        return

    api_keys = Database.get_api_keys() or {}
    api_key = api_keys.get("chutes")
    summary = Database.get_session_conversation_summary(session_id, limit=15)

    name: str | None = None
    if api_key and summary:
        name = _auto_name_via_llm(summary, api_key)
    if not name:
        name = _auto_name_from_history(session_id)
    if not name:
        # Fallback: use timestamp-based name
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        name = f"Chat {timestamp}"

    Database.rename_session(session_id, name)


# ---------------------------------------------------------------------------
# Session start / end
# ---------------------------------------------------------------------------


def _format_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _last_active_timestamp(sessions: list[dict[str, Any]], current_id: int) -> str:
    others = [s for s in sessions if s["id"] != current_id and s.get("updated_at")]
    if not others:
        return "Never"
    others.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return others[0]["updated_at"]


def start_session(interface: str = "terminal") -> dict[str, Any]:
    """Mark the active session as started and run any wake-up tasks."""
    profile = Database.get_profile()
    active_session = Database.get_active_session()
    session_id = active_session["id"]

    sessions = Database.get_all_sessions() or []
    last_active = _last_active_timestamp(sessions, session_id)

    connection_msg = (
        f"*{profile['display_name']} connected to {interface} interface at {_format_now()}. "
        f"Last active: {last_active}. Session count: #{len(sessions)}*"
    )
    Database.add_message("system", connection_msg, session_id)

    history = profile.get("session_history") or {}
    history["current_session"] = {
        "start_time": datetime.now().isoformat(),
        "interface": interface,
        "message_count": 0,
        "start_timestamp": _format_now(),
    }
    history["total_sessions"] = (history.get("total_sessions") or 0) + 1
    Database.update_profile({"session_history": history})

    _bootstrap_memory(session_id)
    return profile


def _bootstrap_memory(session_id: int) -> None:
    try:
        from app.memory.review import run_decay

        run_decay(session_id)
        # Don't enqueue pipeline on every session start - let natural triggers handle it
        # Pipeline will be triggered by should_trigger_segmentation() thresholds
    except Exception as e:  # noqa: BLE001
        log.warning("memory bootstrap failed: %s", e)


def end_session_cleanup(
    profile: dict[str, Any],
    interface: str = "terminal",
    unexpected_exit: bool = False,
) -> str:
    """Persist a disconnect note and update aggregate session history."""
    active_session = Database.get_active_session()
    session_id = active_session["id"]
    sessions = Database.get_all_sessions() or []
    session_count = len(sessions)

    connection_msg = (
        f"*{profile['display_name']} disconnected from {interface} "
        f"at {_format_now()} after a {session_count} session*"
    )
    Database.add_message("system", connection_msg, session_id)

    history = profile.get("session_history") or {}
    history["last_session"] = {
        "end_time": datetime.now().isoformat(),
        "end_timestamp": _format_now(),
        "duration_minutes": round(session_count, 1),
        "message_count": session_count,
        "interface": interface,
        "unexpected_exit": unexpected_exit,
    }
    history["total_sessions"] = (history.get("total_sessions") or 0) + session_count
    history["total_time_minutes"] = (
        history.get("total_time_minutes") or 0
    ) + session_count
    history["current_session"] = {}
    Database.update_profile({"session_history": history})
    return connection_msg
