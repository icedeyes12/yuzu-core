from __future__ import annotations

from datetime import datetime
from typing import Any

from app.db import Database
from app.llm_client import chutes_chat
from app.logging_config import get_logger

log = get_logger(__name__)


class SessionService:
    _AUTO_NAME_TRIGGER_COUNT = 10
    _AUTO_NAME_TRUNCATE = 40
    _AUTO_NAME_MODEL = "google/gemma-4-31B-turbo-TEE"

    # Global session tracker for web clients to prevent duplicate connection messages
    _web_session_tracker: dict[str, bool] = {}

    @classmethod
    def set_session_tracker(cls, tracker: dict[str, bool]):
        cls._web_session_tracker = tracker

    @classmethod
    def is_client_connected(cls, client_id: str) -> bool:
        return cls._web_session_tracker.get(client_id, False)

    @classmethod
    def mark_client_connected(cls, client_id: str):
        cls._web_session_tracker[client_id] = True

    @classmethod
    def clear_client_session(cls, client_id: str):
        cls._web_session_tracker.pop(client_id, None)

    @staticmethod
    def start_session(interface: str = "terminal") -> dict[str, Any]:
        """Mark the active session as started and run any wake-up tasks."""
        profile = Database.get_profile()
        active_session = Database.get_active_session()
        session_id = active_session["id"]

        sessions = Database.get_all_sessions() or []
        last_active = SessionService._last_active_timestamp(sessions, session_id)

        connection_msg = SessionService.generate_connection_msg(
            profile["display_name"], interface, last_active, len(sessions)
        )
        Database.add_message("system", connection_msg, session_id)

        history = profile.get("session_history") or {}
        history["current_session"] = {
            "start_time": datetime.now().isoformat(),
            "interface": interface,
            "message_count": 0,
            "start_timestamp": SessionService._format_now(),
        }
        history["total_sessions"] = (history.get("total_sessions") or 0) + 1
        Database.update_profile({"session_history": history})

        SessionService._bootstrap_memory(session_id)
        return profile

    @staticmethod
    def end_session_cleanup(
        profile: dict[str, Any],
        interface: str = "terminal",
        unexpected_exit: bool = False,
    ) -> str:
        """Persist a disconnect note and update aggregate session history."""
        active_session = Database.get_active_session()
        session_id = active_session["id"]

        # Calculate duration if possible
        history = profile.get("session_history") or {}
        current_session = history.get("current_session", {})
        start_time_str = current_session.get("start_time")
        duration_minutes = 0.0
        if start_time_str:
            try:
                start_time = datetime.fromisoformat(start_time_str)
                duration_minutes = (datetime.now() - start_time).total_seconds() / 60
            except Exception:
                pass

        disconnect_msg = SessionService.generate_disconnect_msg(
            profile["display_name"], interface, duration_minutes, unexpected_exit
        )
        Database.add_message("system", disconnect_msg, session_id)

        history["last_session"] = {
            "end_time": datetime.now().isoformat(),
            "end_timestamp": SessionService._format_now(),
            "duration_minutes": round(duration_minutes, 1),
            "message_count": Database.get_session_messages_count(session_id),
            "interface": interface,
            "unexpected_exit": unexpected_exit,
        }
        history["total_sessions"] = (history.get("total_sessions") or 0) + 1
        history["total_time_minutes"] = (
            history.get("total_time_minutes") or 0
        ) + duration_minutes
        history["current_session"] = {}
        Database.update_profile({"session_history": history})
        return disconnect_msg

    @staticmethod
    def auto_name_session_if_needed(
        session_id: int, active_session: dict[str, Any]
    ) -> None:
        """Rename a 'New Chat' session once it has reached the trigger count."""
        if active_session.get("name") != "New Chat":
            return
        if (
            Database.get_session_messages_count(session_id)
            < SessionService._AUTO_NAME_TRIGGER_COUNT
        ):
            return

        api_keys = Database.get_api_keys() or {}
        api_key = api_keys.get("chutes")
        summary = Database.get_session_conversation_summary(session_id, limit=15)

        name: str | None = None
        if api_key and summary:
            name = SessionService._auto_name_via_llm(summary, api_key)
        if not name:
            name = SessionService._auto_name_from_history(session_id)
        if not name:
            # Fallback: use timestamp-based name
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            name = f"Chat {timestamp}"

        Database.rename_session(session_id, name)

    @staticmethod
    async def start_session_async(interface: str = "terminal") -> dict[str, Any]:
        """Mark the active session as started and run any wake-up tasks (async)."""
        profile = await Database.get_profile_async()
        active_session = await Database.get_active_session_async()
        session_id = active_session["id"]

        sessions = await Database.get_all_sessions_async() or []
        last_active = SessionService._last_active_timestamp(sessions, session_id)

        connection_msg = SessionService.generate_connection_msg(
            profile["display_name"], interface, last_active, len(sessions)
        )
        await Database.add_message_async("system", connection_msg, session_id)

        history = profile.get("session_history") or {}
        history["current_session"] = {
            "start_time": datetime.now().isoformat(),
            "interface": interface,
            "message_count": 0,
            "start_timestamp": SessionService._format_now(),
        }
        history["total_sessions"] = (history.get("total_sessions") or 0) + 1
        await Database.update_profile_async({"session_history": history})

        await SessionService._bootstrap_memory_async(session_id)
        return profile

    @staticmethod
    async def end_session_cleanup_async(
        profile: dict[str, Any],
        interface: str = "terminal",
        unexpected_exit: bool = False,
    ) -> str:
        """Persist a disconnect note and update aggregate session history (async)."""
        active_session = await Database.get_active_session_async()
        session_id = active_session["id"]

        # Calculate duration if possible
        history = profile.get("session_history") or {}
        current_session = history.get("current_session", {})
        start_time_str = current_session.get("start_time")
        duration_minutes = 0.0
        if start_time_str:
            try:
                start_time = datetime.fromisoformat(start_time_str)
                duration_minutes = (datetime.now() - start_time).total_seconds() / 60
            except Exception:
                pass

        disconnect_msg = SessionService.generate_disconnect_msg(
            profile["display_name"], interface, duration_minutes, unexpected_exit
        )
        await Database.add_message_async("system", disconnect_msg, session_id)

        history["last_session"] = {
            "end_time": datetime.now().isoformat(),
            "end_timestamp": SessionService._format_now(),
            "duration_minutes": round(duration_minutes, 1),
            "message_count": await Database.get_session_messages_count_async(
                session_id
            ),
            "interface": interface,
            "unexpected_exit": unexpected_exit,
        }
        history["total_sessions"] = (history.get("total_sessions") or 0) + 1
        history["total_time_minutes"] = (
            history.get("total_time_minutes") or 0
        ) + duration_minutes
        history["current_session"] = {}
        await Database.update_profile_async({"session_history": history})
        return disconnect_msg

    @staticmethod
    async def auto_name_session_if_needed_async(
        session_id: int, active_session: dict[str, Any]
    ) -> None:
        """Rename a 'New Chat' session once it has reached the trigger count (async)."""
        if active_session.get("name") != "New Chat":
            return
        if (
            await Database.get_session_messages_count_async(session_id)
            < SessionService._AUTO_NAME_TRIGGER_COUNT
        ):
            return

        api_keys = await Database.get_api_keys_async() or {}
        api_key = api_keys.get("chutes")
        summary = await Database.get_session_conversation_summary_async(
            session_id, limit=15
        )

        name: str | None = None
        if api_key and summary:
            name = await SessionService._auto_name_via_llm_async(summary, api_key)
        if not name:
            name = await SessionService._auto_name_from_history_async(session_id)
        if not name:
            # Fallback: use timestamp-based name
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            name = f"Chat {timestamp}"

        await Database.rename_session_async(session_id, name)

    @staticmethod
    def generate_connection_msg(
        display_name: str, interface: str, last_active: str, session_count: int
    ) -> str:
        return (
            f"*{display_name} connected to {interface} interface at {SessionService._format_now()}. "
            f"Last active: {last_active}. Session count: #{session_count}*"
        )

    @staticmethod
    def generate_disconnect_msg(
        display_name: str,
        interface: str,
        duration_minutes: float,
        unexpected_exit: bool = False,
    ) -> str:
        status = "unexpectedly " if unexpected_exit else ""
        return (
            f"*{display_name} disconnected {status}from {interface} "
            f"at {SessionService._format_now()} after {duration_minutes:.1f} minutes*"
        )

    @staticmethod
    def _format_now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _last_active_timestamp(sessions: list[dict[str, Any]], current_id: int) -> str:
        others = [s for s in sessions if s["id"] != current_id and s.get("updated_at")]
        if not others:
            return "Never"
        others.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
        return others[0]["updated_at"]

    @staticmethod
    def _bootstrap_memory(session_id: int) -> None:
        try:
            from app.memory.review import run_decay

            run_decay(session_id)
        except Exception as e:
            log.warning("memory bootstrap failed: %s", e)

    @staticmethod
    async def _bootstrap_memory_async(session_id: int) -> None:
        try:
            from app.memory.review import run_decay_async

            await run_decay_async(session_id)
        except Exception as e:
            log.warning("memory bootstrap failed: %s", e)

    @staticmethod
    def _auto_name_via_llm(conversation_summary: str, api_key: str) -> str | None:
        prompt = (
            "Based on this conversation, create a SHORT session title (max 6 words):\n\n"
            f"{conversation_summary}\n\n"
            "Reply with ONLY the title, nothing else."
        )
        name = chutes_chat(
            prompt,
            api_key=api_key,
            model=SessionService._AUTO_NAME_MODEL,
            title="Yuzu-Session-Naming",
            max_tokens=64,
        )
        if not name:
            return None
        cleaned = name.replace('"', "").replace("'", "").strip()
        return (cleaned[:50] + "...") if len(cleaned) > 50 else cleaned

    @staticmethod
    async def _auto_name_via_llm_async(
        conversation_summary: str, api_key: str
    ) -> str | None:
        prompt = (
            "Based on this conversation, create a SHORT session title (max 6 words):\n\n"
            f"{conversation_summary}\n\n"
            "Reply with ONLY the title, nothing else."
        )
        name = await chutes_chat(
            prompt,
            api_key=api_key,
            model=SessionService._AUTO_NAME_MODEL,
            title="Yuzu-Session-Naming",
            max_tokens=64,
        )
        if not name:
            return None
        cleaned = name.replace('"', "").replace("'", "").strip()
        return (cleaned[:50] + "...") if len(cleaned) > 50 else cleaned

    @staticmethod
    def _auto_name_from_history(session_id: int) -> str | None:
        history = Database.get_chat_history(session_id, limit=5) or []
        for msg in history:
            if msg["role"] == "user" and len(msg["content"].strip()) > 10:
                text = msg["content"].strip()
                short = text[: SessionService._AUTO_NAME_TRUNCATE]
                return (
                    short + "..."
                    if len(text) > SessionService._AUTO_NAME_TRUNCATE
                    else short
                )
        return None

    @staticmethod
    async def _auto_name_from_history_async(session_id: int) -> str | None:
        history = await Database.get_chat_history_async(session_id, limit=5) or []
        for msg in history:
            if msg["role"] == "user" and len(msg["content"].strip()) > 10:
                text = msg["content"].strip()
                short = text[: SessionService._AUTO_NAME_TRUNCATE]
                return (
                    short + "..."
                    if len(text) > SessionService._AUTO_NAME_TRUNCATE
                    else short
                )
        return None
