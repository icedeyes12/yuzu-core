# FILE: app.db.facade.py
# DESCRIPTION: Thin facade over app.db.models.
#
# The Database class normalizes argument order (most app code wants to pass
# `role` and `content` first, with `session_id` defaulting to the active
# session) and provides a stable surface for backward compatibility. Pure
# passthrough methods are generated programmatically to avoid 200+ lines of
# one-line wrappers.

from __future__ import annotations

from typing import Any, Callable

from app.db.models import (
    ALL_TOOL_ROLES,
    TOOL_ROLES,
    add_api_key as _pg_add_api_key,
    add_message as _pg_add_message,
    update_message as _pg_update_message,
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
from app.db.models_async import (
    add_api_key_async as _pg_add_api_key_async,
    add_message_async as _pg_add_message_async,
    update_message_async as _pg_update_message_async,
    add_session_event_async as _pg_add_session_event_async,
    add_system_note_async as _pg_add_system_note_async,
    add_tool_result_async as _pg_add_tool_result_async,
    batch_decrypt_messages_async as _pg_batch_decrypt_messages_async,
    clear_session_messages_async as _pg_clear_session_messages_async,
    create_session_async as _pg_create_session_async,
    delete_session_async as _pg_delete_session_async,
    get_active_session_async as _pg_get_active_session_async,
    get_all_encrypted_messages_async as _pg_get_all_encrypted_messages_async,
    get_all_sessions_async as _pg_get_all_sessions_async,
    get_api_key_async as _pg_get_api_key_async,
    get_api_keys_async as _pg_get_api_keys_async,
    get_chat_history_async as _pg_get_chat_history_async,
    get_chat_history_for_ai_async as _pg_get_chat_history_for_ai_async,
    get_context_async as _pg_get_context_async,
    get_encryption_status_async as _pg_get_encryption_status_async,
    get_message_count_async as _pg_get_message_count_async,
    get_profile_async as _pg_get_profile_async,
    get_recent_sessions_async as _pg_get_recent_sessions_async,
    get_recent_sessions_for_session_async as _pg_get_recent_sessions_for_session_async,
    get_recent_active_sessions_async as _pg_get_recent_active_sessions_async,
    get_session_conversation_summary_async as _pg_get_session_conversation_summary_async,
    get_session_memory_async as _pg_get_session_memory_async,
    get_session_messages_async as _pg_get_session_messages_async,
    increment_message_count_async as _pg_increment_message_count_async,
    remove_api_key_async as _pg_remove_api_key_async,
    rename_session_async as _pg_rename_session_async,
    switch_session_async as _pg_switch_session_async,
    update_context_async as _pg_update_context_async,
    update_profile_async as _pg_update_profile_async,
    update_session_memory_async as _pg_update_session_memory_async,
    create_session_token_async as _pg_create_session_token_async,
    validate_session_token_async as _pg_validate_session_token_async,
    revoke_session_token_async as _pg_revoke_session_token_async,
    lookup_identity_async as _pg_lookup_identity_async,
    lookup_unclaimed_profile_async as _pg_lookup_unclaimed_profile_async,
    insert_default_profile_returning_async as _pg_insert_default_profile_returning_async,
    update_profile_avatar_async as _pg_update_profile_avatar_async,
    update_profile_display_name_async as _pg_update_profile_display_name_async,
    insert_identity_async as _pg_insert_identity_async,
    lookup_auth_me_async as _pg_lookup_auth_me_async,
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


def _resolve_session_id(session_id: str | None, user_id: str) -> str:
    """Default a missing session_id to the currently active session."""
    if session_id is not None:
        return session_id
    active = _pg_get_active_session(user_id)
    return active["id"]


async def _resolve_session_id_async(session_id: str | None, user_id: str) -> str:
    """Default a missing session_id to the currently active session (async)."""
    if session_id is not None:
        return session_id
    active = await _pg_get_active_session_async(user_id)
    return active["id"]


class TenantScopeError(RuntimeError):
    """Raised when a tenant-scoped operation runs without a valid user_id.

    A falsy user_id (None / "") would silently scope a query to an empty tenant
    or cross tenant boundaries. Fail loud at the facade boundary instead of
    letting a malformed query reach the DB.
    """

    def __init__(self, method: str) -> None:
        super().__init__(
            f"{method}: user_id is required and must be non-empty (tenant isolation)"
        )
        self.method = method


def _require_user_id(method: str, user_id: str | None) -> None:
    """Validate user_id at the facade boundary. Raises TenantScopeError if falsy."""
    if not user_id or not str(user_id).strip():
        raise TenantScopeError(method)


def _proxy(target: Callable[..., Any]) -> staticmethod:
    """Wrap a function in a staticmethod that forwards *args/**kwargs.

    Used for pure passthroughs where Database.X(args) == _pg_X(args).
    """

    def _call(*args: Any, **kwargs: Any) -> Any:
        return target(*args, **kwargs)

    _call.__name__ = target.__name__
    _call.__doc__ = target.__doc__
    return staticmethod(_call)


def _proxy_async(target: Callable[..., Any]) -> staticmethod:
    """Wrap an async function in a staticmethod that forwards *args/**kwargs."""

    async def _call(*args: Any, **kwargs: Any) -> Any:
        return await target(*args, **kwargs)

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

    # ── Profile / context (pure passthroughs) ────────────────────────────────
    get_profile = _proxy(_pg_get_profile)
    get_profile_async = _proxy_async(_pg_get_profile_async)
    update_profile = _proxy(_pg_update_profile)
    update_profile_async = _proxy_async(_pg_update_profile_async)
    get_context = _proxy(_pg_get_context)
    get_context_async = _proxy_async(_pg_get_context_async)
    update_context = _proxy(_pg_update_context)
    update_context_async = _proxy_async(_pg_update_context_async)

    # ── API keys (pure passthroughs) ──────────────────────────────────────────
    get_api_keys = _proxy(_pg_get_api_keys)
    get_api_keys_async = _proxy_async(_pg_get_api_keys_async)
    get_api_key = _proxy(_pg_get_api_key)
    get_api_key_async = _proxy_async(_pg_get_api_key_async)
    add_api_key = _proxy(_pg_add_api_key)
    add_api_key_async = _proxy_async(_pg_add_api_key_async)
    remove_api_key = _proxy(_pg_remove_api_key)
    remove_api_key_async = _proxy_async(_pg_remove_api_key_async)

    # ── Sessions (pure passthroughs) ──────────────────────────────────────────
    create_session = _proxy(_pg_create_session)
    create_session_async = _proxy_async(_pg_create_session_async)
    get_active_session = _proxy(_pg_get_active_session)
    get_active_session_async = _proxy_async(_pg_get_active_session_async)
    get_all_sessions = _proxy(_pg_get_all_sessions)
    get_all_sessions_async = _proxy_async(_pg_get_all_sessions_async)
    switch_session = _proxy(_pg_switch_session)
    switch_session_async = _proxy_async(_pg_switch_session_async)
    rename_session = _proxy(_pg_rename_session)
    rename_session_async = _proxy_async(_pg_rename_session_async)
    delete_session = _proxy(_pg_delete_session)
    delete_session_async = _proxy_async(_pg_delete_session_async)
    get_session_memory = _proxy(_pg_get_session_memory)
    get_session_memory_async = _proxy_async(_pg_get_session_memory_async)
    update_session_memory = _proxy(_pg_update_session_memory)
    update_session_memory_async = _proxy_async(_pg_update_session_memory_async)
    increment_message_count = _proxy(_pg_increment_message_count)
    increment_message_count_async = _proxy_async(_pg_increment_message_count_async)
    get_session_messages_count = _proxy(_pg_get_message_count)
    get_session_messages_count_async = _proxy_async(_pg_get_message_count_async)
    get_session_conversation_summary = _proxy(_pg_get_session_conversation_summary)
    get_session_conversation_summary_async = _proxy_async(
        _pg_get_session_conversation_summary_async
    )
    get_recent_sessions = _proxy(_pg_get_recent_sessions)
    get_recent_sessions_async = _proxy_async(_pg_get_recent_sessions_async)
    get_recent_sessions_for_session = _proxy(_pg_get_recent_sessions_for_session)
    get_recent_sessions_for_session_async = _proxy_async(
        _pg_get_recent_sessions_for_session_async
    )
    get_recent_active_sessions_async = _proxy_async(
        _pg_get_recent_active_sessions_async
    )

    # ── Encryption status (pure passthroughs) ────────────────────────────────
    get_encryption_status = _proxy(_pg_get_encryption_status)
    get_encryption_status_async = _proxy_async(_pg_get_encryption_status_async)
    get_all_encrypted_messages = _proxy(_pg_get_all_encrypted_messages)
    get_all_encrypted_messages_async = _proxy_async(
        _pg_get_all_encrypted_messages_async
    )
    batch_decrypt_messages = _proxy(_pg_batch_decrypt_messages)
    batch_decrypt_messages_async = _proxy_async(_pg_batch_decrypt_messages_async)

    # ── Auth & Tokens (pure passthroughs) ─────────────────────────────────────
    create_session_token_async = _proxy_async(_pg_create_session_token_async)
    validate_session_token_async = _proxy_async(_pg_validate_session_token_async)
    revoke_session_token_async = _proxy_async(_pg_revoke_session_token_async)
    lookup_identity_async = _proxy_async(_pg_lookup_identity_async)
    lookup_unclaimed_profile_async = _proxy_async(_pg_lookup_unclaimed_profile_async)
    insert_default_profile_returning_async = _proxy_async(
        _pg_insert_default_profile_returning_async
    )
    update_profile_avatar_async = _proxy_async(_pg_update_profile_avatar_async)
    update_profile_display_name_async = _proxy_async(
        _pg_update_profile_display_name_async
    )
    insert_identity_async = _proxy_async(_pg_insert_identity_async)
    lookup_auth_me_async = _proxy_async(_pg_lookup_auth_me_async)

    # ── Messages (session_id-defaulting wrappers) ────────────────────────────
    @staticmethod
    def update_message(
        message_id: int, content: str, image_paths: list[str] | None = None
    ) -> bool:
        return _pg_update_message(message_id, content, image_paths)

    @staticmethod
    async def update_message_async(
        message_id: int, content: str, image_paths: list[str] | None = None
    ) -> bool:
        return await _pg_update_message_async(message_id, content)

    # These reorder args (role/content first) and default session_id to the
    # active session, which is the convention used throughout the codebase.

    @staticmethod
    def add_message(
        role: str,
        content: str,
        session_id: str | None = None,
        image_paths: list[str] | None = None,
        *,
        user_id: str,
    ) -> int | None:
        """Add a message to a session (defaults to active session)."""
        _require_user_id("add_message", user_id)
        return _pg_add_message(
            _resolve_session_id(session_id, user_id),
            role,
            content,
            image_paths,
            user_id=user_id,
        )

    @staticmethod
    async def add_message_async(
        role: str,
        content: str,
        session_id: str | None = None,
        image_paths: list[str] | None = None,
        *,
        user_id: str,
    ) -> int | None:
        """Add a message to a session (defaults to active session)."""
        _require_user_id("add_message_async", user_id)
        return await _pg_add_message_async(
            await _resolve_session_id_async(session_id, user_id),
            role,
            content,
            image_paths,
            user_id=user_id,
        )

    @staticmethod
    def get_messages(
        session_id: str | None = None, limit: int | None = None, *, user_id: str
    ) -> list[dict]:
        """Get messages for a session (defaults to active session)."""
        _require_user_id("get_messages", user_id)
        return _pg_get_session_messages(
            _resolve_session_id(session_id, user_id), limit or 100
        )

    @staticmethod
    async def get_messages_async(
        session_id: str | None = None, limit: int | None = None, *, user_id: str
    ) -> list[dict]:
        """Get messages for a session (defaults to active session)."""
        _require_user_id("get_messages_async", user_id)
        return await _pg_get_session_messages_async(
            await _resolve_session_id_async(session_id, user_id), limit or 100
        )

    @staticmethod
    def get_chat_history(
        session_id: str | None = None,
        limit: int | None = None,
        recent: bool = False,
        *,
        user_id: str,
    ) -> list[dict]:
        """Get chat history for a session (defaults to active session)."""
        _require_user_id("get_chat_history", user_id)
        return _pg_get_chat_history(
            _resolve_session_id(session_id, user_id), limit, recent, user_id=user_id
        )

    @staticmethod
    async def get_chat_history_async(
        session_id: str | None = None,
        limit: int | None = None,
        recent: bool = False,
        *,
        user_id: str,
    ) -> list[dict]:
        """Get chat history for a session (defaults to active session)."""
        _require_user_id("get_chat_history_async", user_id)
        return await _pg_get_chat_history_async(
            await _resolve_session_id_async(session_id, user_id),
            limit,
            recent,
            user_id=user_id,
        )

    @staticmethod
    def get_chat_history_for_ai(
        session_id: str | None = None,
        limit: int | None = None,
        recent: bool = False,
        include_image_paths: bool = False,
        *,
        user_id: str,
    ) -> list[dict]:
        """Build message context for AI provider (defaults to active session)."""
        _require_user_id("get_chat_history_for_ai", user_id)
        return _pg_get_chat_history_for_ai(
            _resolve_session_id(session_id, user_id),
            limit,
            recent,
            include_image_paths,
            user_id=user_id,
        )

    @staticmethod
    async def get_chat_history_for_ai_async(
        session_id: str | None = None,
        limit: int | None = None,
        recent: bool = False,
        include_image_paths: bool = False,
        *,
        user_id: str,
    ) -> list[dict]:
        """Build message context for AI provider (defaults to active session)."""
        _require_user_id("get_chat_history_for_ai_async", user_id)
        return await _pg_get_chat_history_for_ai_async(
            await _resolve_session_id_async(session_id, user_id),
            limit,
            recent,
            include_image_paths,
            user_id=user_id,
        )

    @staticmethod
    def clear_session(session_id: str | None = None, *, user_id: str) -> bool:
        """Clear all messages for a session (defaults to active session)."""
        _require_user_id("clear_session", user_id)
        return _pg_clear_session_messages(_resolve_session_id(session_id, user_id))

    @staticmethod
    async def clear_session_async(
        session_id: str | None = None, *, user_id: str
    ) -> bool:
        """Clear all messages for a session (defaults to active session)."""
        _require_user_id("clear_session_async", user_id)
        return await _pg_clear_session_messages_async(
            await _resolve_session_id_async(session_id, user_id)
        )

    @staticmethod
    def clear_chat_history(session_id: str | None = None, *, user_id: str) -> bool:
        """Alias for clear_session."""
        _require_user_id("clear_chat_history", user_id)
        return Database.clear_session(session_id, user_id=user_id)

    @staticmethod
    async def clear_chat_history_async(
        session_id: str | None = None, *, user_id: str
    ) -> bool:
        """Alias for clear_session_async."""
        _require_user_id("clear_chat_history_async", user_id)
        return await Database.clear_session_async(session_id, user_id=user_id)

    @staticmethod
    def add_session_event(
        content: str, interface: str = "terminal", *, user_id: str
    ) -> int | None:
        """Add a session event message to the active session."""
        _require_user_id("add_session_event", user_id)
        active = _pg_get_active_session(user_id)
        return _pg_add_session_event(active["id"], content, interface)

    @staticmethod
    async def add_session_event_async(
        content: str, interface: str = "terminal", *, user_id: str
    ) -> int | None:
        """Add a session event message to the active session."""
        _require_user_id("add_session_event_async", user_id)
        active = await _pg_get_active_session_async(user_id)
        return await _pg_add_session_event_async(active["id"], content, interface)

    @staticmethod
    def add_tool_result(
        tool_name: str,
        result_content: str,
        session_id: str | None = None,
        *,
        user_id: str,
    ) -> int | None:
        """Store tool result with tool-specific role (defaults to active session)."""
        _require_user_id("add_tool_result", user_id)
        return _pg_add_tool_result(
            _resolve_session_id(session_id, user_id), tool_name, result_content
        )

    @staticmethod
    async def add_tool_result_async(
        tool_name: str,
        result_content: str,
        session_id: str | None = None,
        *,
        user_id: str,
    ) -> int | None:
        """Store tool result with tool-specific role (defaults to active session)."""
        _require_user_id("add_tool_result_async", user_id)
        return await _pg_add_tool_result_async(
            await _resolve_session_id_async(session_id, user_id),
            tool_name,
            result_content,
        )

    @staticmethod
    def add_system_note(
        content: str, session_id: str | None = None, *, user_id: str
    ) -> int | None:
        """Add a system note message (defaults to active session)."""
        _require_user_id("add_system_note", user_id)
        return _pg_add_system_note(_resolve_session_id(session_id, user_id), content)

    @staticmethod
    async def add_system_note_async(
        content: str, session_id: str | None = None, *, user_id: str
    ) -> int | None:
        """Add a system note message (defaults to active session)."""
        _require_user_id("add_system_note_async", user_id)
        return await _pg_add_system_note_async(
            await _resolve_session_id_async(session_id, user_id), content
        )

    @staticmethod
    def add_memory_note(
        content: str, session_id: str | None = None, *, user_id: str
    ) -> int | None:
        """Alias for add_system_note."""
        _require_user_id("add_memory_note", user_id)
        return Database.add_system_note(content, session_id, user_id=user_id)

    @staticmethod
    async def add_memory_note_async(
        content: str, session_id: str | None = None, *, user_id: str
    ) -> int | None:
        """Alias for add_system_note_async."""
        _require_user_id("add_memory_note_async", user_id)
        return await Database.add_system_note_async(
            content, session_id, user_id=user_id
        )


__all__ = [
    "Database",
    "TenantScopeError",
    "TOOL_ROLES",
    "ALL_TOOL_ROLES",
    "init_db",
]
