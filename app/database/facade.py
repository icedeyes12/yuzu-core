# FILE: app/database/facade.py
# DESCRIPTION: Thin facade over app.database.db_pg_models.
#
# The Database class normalizes argument order (most app code wants to pass
# `role` and `content` first, with `session_id` defaulting to the active
# session) and provides a stable surface for backward compatibility. Pure
# passthrough methods are generated programmatically to avoid 200+ lines of
# one-line wrappers.

from __future__ import annotations

from typing import Any, Callable

from app.database.db_pg_models import (
    ALL_TOOL_ROLES,
    TOOL_ROLES,
    add_api_key as _pg_add_api_key,
    add_image_tools_message as _pg_add_image_tools_message,
    add_message as _pg_add_message,
    add_session_event as _pg_add_session_event,
    add_system_note as _pg_add_system_note,
    add_tool_result as _pg_add_tool_result,
    batch_decrypt_messages as _pg_batch_decrypt_messages,
    clear_session_messages as _pg_clear_session_messages,
    create_session as _pg_create_session,
    delete_session as _pg_delete_session,
    get_active_session as _pg_get_active_session,
    get_all_encrypted_messages as _pg_get_all_encrypted_messages,
    get_all_sessions as _pg_get_all_sessions,
    get_api_key as _pg_get_api_key,
    get_api_keys as _pg_get_api_keys,
    get_chat_history as _pg_get_chat_history,
    get_chat_history_for_ai as _pg_get_chat_history_for_ai,
    get_context as _pg_get_context,
    get_encryption_status as _pg_get_encryption_status,
    get_message_count as _pg_get_message_count,
    get_profile as _pg_get_profile,
    get_recent_sessions as _pg_get_recent_sessions,
    get_recent_sessions_for_session as _pg_get_recent_sessions_for_session,
    get_session_conversation_summary as _pg_get_session_conversation_summary,
    get_session_memory as _pg_get_session_memory,
    get_session_messages as _pg_get_session_messages,
    increment_message_count as _pg_increment_message_count,
    init_pg_tables as _init_pg_tables,
    remove_api_key as _pg_remove_api_key,
    rename_session as _pg_rename_session,
    switch_session as _pg_switch_session,
    update_context as _pg_update_context,
    update_profile as _pg_update_profile,
    update_session_memory as _pg_update_session_memory,
)
from app.logging_config import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create PostgreSQL tables if missing."""
    log.info("initializing PostgreSQL tables")
    _init_pg_tables()
    log.info("PostgreSQL tables initialized")


# ---------------------------------------------------------------------------
# Database facade
# ---------------------------------------------------------------------------


def _resolve_session_id(session_id: int | None) -> int:
    """Default a missing session_id to the currently active session."""
    if session_id is not None:
        return session_id
    active = _pg_get_active_session()
    return active["id"]


def _proxy(target: Callable[..., Any]) -> staticmethod:
    """Wrap a function in a staticmethod that forwards *args/**kwargs.

    Used for pure passthroughs where Database.X(args) == _pg_X(args).
    """
    def _call(*args: Any, **kwargs: Any) -> Any:
        return target(*args, **kwargs)

    _call.__name__ = target.__name__
    _call.__doc__ = target.__doc__
    return staticmethod(_call)


class Database:
    """Static helper class delegating to PostgreSQL via db_pg_models.

    Two patterns live here:
      1. Pure passthroughs (generated via _proxy) for methods that don't
         need argument normalization.
      2. Hand-written wrappers for methods that:
           - default session_id to the active session, AND/OR
           - accept a different argument order than db_pg_models.
    """

    # ── Profile / context (pure passthroughs) ────────────────────────────────────
    get_profile = _proxy(_pg_get_profile)
    update_profile = _proxy(_pg_update_profile)
    get_context = _proxy(_pg_get_context)
    update_context = _proxy(_pg_update_context)

    # ── API keys (pure passthroughs) ──────────────────────────────────────────────
    get_api_keys = _proxy(_pg_get_api_keys)
    get_api_key = _proxy(_pg_get_api_key)
    add_api_key = _proxy(_pg_add_api_key)
    remove_api_key = _proxy(_pg_remove_api_key)

    # ── Sessions (pure passthroughs) ──────────────────────────────────────────────
    create_session = _proxy(_pg_create_session)
    get_active_session = _proxy(_pg_get_active_session)
    get_all_sessions = _proxy(_pg_get_all_sessions)
    switch_session = _proxy(_pg_switch_session)
    rename_session = _proxy(_pg_rename_session)
    delete_session = _proxy(_pg_delete_session)
    get_session_memory = _proxy(_pg_get_session_memory)
    update_session_memory = _proxy(_pg_update_session_memory)
    increment_message_count = _proxy(_pg_increment_message_count)
    get_session_messages_count = _proxy(_pg_get_message_count)
    get_session_conversation_summary = _proxy(_pg_get_session_conversation_summary)
    get_recent_sessions = _proxy(_pg_get_recent_sessions)
    get_recent_sessions_for_session = _proxy(_pg_get_recent_sessions_for_session)

    # ── Encryption status (pure passthroughs) ──────────────────────────────────
    get_encryption_status = _proxy(_pg_get_encryption_status)
    get_all_encrypted_messages = _proxy(_pg_get_all_encrypted_messages)
    batch_decrypt_messages = _proxy(_pg_batch_decrypt_messages)

    # ── Messages (session_id-defaulting wrappers) ────────────────────────────────
    # These reorder args (role/content first) and default session_id to the
    # active session, which is the convention used throughout the codebase.

    @staticmethod
    def add_message(
        role: str,
        content: str,
        session_id: int | None = None,
        image_paths: str | None = None,
    ) -> int | None:
        """Add a message to a session (defaults to active session)."""
        return _pg_add_message(_resolve_session_id(session_id), role, content, image_paths)

    @staticmethod
    def get_messages(
        session_id: int | None = None, limit: int | None = None
    ) -> list[dict]:
        """Get messages for a session (defaults to active session)."""
        return _pg_get_session_messages(_resolve_session_id(session_id), limit or 100)

    @staticmethod
    def get_chat_history(
        session_id: int | None = None,
        limit: int | None = None,
        recent: bool = False,
    ) -> list[dict]:
        """Get chat history for a session (defaults to active session)."""
        return _pg_get_chat_history(_resolve_session_id(session_id), limit, recent)

    @staticmethod
    def get_chat_history_for_ai(
        session_id: int | None = None,
        limit: int | None = None,
        recent: bool = False,
    ) -> list[dict]:
        """Build message context for AI provider (defaults to active session)."""
        return _pg_get_chat_history_for_ai(_resolve_session_id(session_id), limit, recent)

    @staticmethod
    def clear_session(session_id: int | None = None) -> bool:
        """Clear all messages for a session (defaults to active session)."""
        return _pg_clear_session_messages(_resolve_session_id(session_id))

    @staticmethod
    def clear_chat_history(session_id: int | None = None) -> bool:
        """Alias for clear_session."""
        return Database.clear_session(session_id)

    @staticmethod
    def add_session_event(content: str, interface: str = "terminal") -> int | None:
        """Add a session event message to the active session."""
        active = _pg_get_active_session()
        return _pg_add_session_event(active["id"], content, interface)

    @staticmethod
    def add_image_tools_message(
        image_url: str, session_id: int | None = None
    ) -> int | None:
        """Add an image tools message (defaults to active session)."""
        return _pg_add_image_tools_message(_resolve_session_id(session_id), image_url)

    @staticmethod
    def add_tool_result(
        tool_name: str,
        result_content: str,
        session_id: int | None = None,
    ) -> int | None:
        """Store tool result with tool-specific role (defaults to active session)."""
        return _pg_add_tool_result(_resolve_session_id(session_id), tool_name, result_content)

    @staticmethod
    def add_system_note(
        content: str, session_id: int | None = None
    ) -> int | None:
        """Add a system note message (defaults to active session)."""
        return _pg_add_system_note(_resolve_session_id(session_id), content)

    @staticmethod
    def add_memory_note(
        content: str, session_id: int | None = None
    ) -> int | None:
        """Alias for add_system_note."""
        return Database.add_system_note(content, session_id)


__all__ = [
    "Database",
    "TOOL_ROLES",
    "ALL_TOOL_ROLES",
    "init_db",
]
