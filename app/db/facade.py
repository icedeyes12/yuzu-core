"""Thin facade over db/models_async — provides a stable Database surface."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.db.models_async import (
    add_message_async as _pg_add_message_async,
)
from app.db.models_async import (
    add_session_event_async as _pg_add_session_event_async,
)
from app.db.models_async import (
    add_system_note_async as _pg_add_system_note_async,
)
from app.db.models_async import (
    batch_decrypt_messages_async as _pg_batch_decrypt_messages_async,
)
from app.db.models_async import (
    clear_session_messages_async as _pg_clear_session_messages_async,
)
from app.db.models_async import (
    create_global_knowledge_async as _pg_create_global_knowledge_async,
)
from app.db.models_async import (
    create_session_async as _pg_create_session_async,
)
from app.db.models_async import (
    create_session_token_async as _pg_create_session_token_async,
)
from app.db.models_async import (
    delete_global_knowledge_async as _pg_delete_global_knowledge_async,
)
from app.db.models_async import (
    delete_session_async as _pg_delete_session_async,
)
from app.db.models_async import (
    get_active_session_async as _pg_get_active_session_async,
)
from app.db.models_async import (
    get_all_encrypted_messages_async as _pg_get_all_encrypted_messages_async,
)
from app.db.models_async import (
    get_all_sessions_async as _pg_get_all_sessions_async,
)
from app.db.models_async import (
    get_chat_history_async as _pg_get_chat_history_async,
)
from app.db.models_async import (
    get_chat_history_for_ai_async as _pg_get_chat_history_for_ai_async,
)
from app.db.models_async import (
    get_context_async as _pg_get_context_async,
)
from app.db.models_async import (
    get_encryption_status_async as _pg_get_encryption_status_async,
)
from app.db.models_async import (
    get_global_knowledge_async as _pg_get_global_knowledge_async,
)
from app.db.models_async import (
    get_message_count_async as _pg_get_message_count_async,
)
from app.db.models_async import (
    get_profile_async as _pg_get_profile_async,
)
from app.db.models_async import (
    get_recent_active_sessions_async as _pg_get_recent_active_sessions_async,
)
from app.db.models_async import (
    get_session_conversation_summary_async as _pg_get_session_conversation_summary_async,
)
from app.db.models_async import (
    get_session_messages_async as _pg_get_session_messages_async,
)
from app.db.models_async import (
    increment_message_count_async as _pg_increment_message_count_async,
)
from app.db.models_async import (
    insert_default_profile_returning_async as _pg_insert_default_profile_returning_async,
)
from app.db.models_async import (
    insert_identity_async as _pg_insert_identity_async,
)
from app.db.models_async import (
    list_global_knowledge_async as _pg_list_global_knowledge_async,
)
from app.db.models_async import (
    lookup_auth_me_async as _pg_lookup_auth_me_async,
)
from app.db.models_async import (
    lookup_identity_async as _pg_lookup_identity_async,
)
from app.db.models_async import (
    lookup_unclaimed_profile_async as _pg_lookup_unclaimed_profile_async,
)
from app.db.models_async import (
    rename_session_async as _pg_rename_session_async,
)
from app.db.models_async import (
    rename_session_if_placeholder_async as _pg_rename_session_if_placeholder_async,
)
from app.db.models_async import (
    revoke_session_token_async as _pg_revoke_session_token_async,
)
from app.db.models_async import (
    switch_session_async as _pg_switch_session_async,
)
from app.db.models_async import (
    update_context_async as _pg_update_context_async,
)
from app.db.models_async import (
    update_global_knowledge_async as _pg_update_global_knowledge_async,
)
from app.db.models_async import (
    update_message_async as _pg_update_message_async,
)
from app.db.models_async import (
    update_profile_async as _pg_update_profile_async,
)
from app.db.models_async import (
    update_profile_avatar_async as _pg_update_profile_avatar_async,
)
from app.db.models_async import (
    update_profile_user_name_async as _pg_update_profile_user_name_async,
)
from app.db.models_async import (
    validate_session_token_async as _pg_validate_session_token_async,
)
from app.logging_config import get_logger

log = get_logger(__name__)

type DBRow = dict[str, Any]


def init_db() -> None:
    """Create PostgreSQL tables if missing (runs sync init for bootstrap)."""
    import asyncio

    log.info("initializing PostgreSQL tables")
    asyncio.run(_init_pg_tables_async_wrapper())
    log.info("PostgreSQL tables initialized")


async def _init_pg_tables_async_wrapper() -> None:
    from app.db.models_async import init_pg_tables_async

    await init_pg_tables_async()


async def _resolve_session_id_async(session_id: str | None, user_id: str) -> str:
    """Default a missing session_id to the currently active session (async)."""
    if session_id is not None:
        return session_id
    active = await _pg_get_active_session_async(user_id)
    return str(active["id"])


class TenantScopeError(RuntimeError):
    """Raised when a tenant-scoped operation runs without a valid user_id."""

    def __init__(self, method: str) -> None:
        super().__init__(
            f"{method}: user_id is required and must be non-empty (tenant isolation)"
        )
        self.method: str = method


def _require_user_id(method: str, user_id: str | None) -> None:
    """Validate user_id at the facade boundary. Raises TenantScopeError if falsy."""
    if not user_id or not str(user_id).strip():
        raise TenantScopeError(method)


def _proxy_async(target: Callable[..., Any]) -> Any:
    """Wrap an async function in a staticmethod that forwards *args/**kwargs."""

    async def _call(*args: Any, **kwargs: Any) -> Any:
        return await target(*args, **kwargs)

    _call.__name__ = target.__name__
    _call.__doc__ = target.__doc__
    return staticmethod(_call)


class Database:
    """Static helper class delegating to PostgreSQL via async models."""

    # Profile
    get_profile = _proxy_async(_pg_get_profile_async)
    update_profile = _proxy_async(_pg_update_profile_async)
    get_context = _proxy_async(_pg_get_context_async)
    update_context = _proxy_async(_pg_update_context_async)

    # Global Knowledge
    list_global_knowledge = _proxy_async(_pg_list_global_knowledge_async)
    get_global_knowledge = _proxy_async(_pg_get_global_knowledge_async)
    create_global_knowledge = _proxy_async(_pg_create_global_knowledge_async)
    update_global_knowledge = _proxy_async(_pg_update_global_knowledge_async)
    delete_global_knowledge = _proxy_async(_pg_delete_global_knowledge_async)

    # Sessions
    create_session = _proxy_async(_pg_create_session_async)
    get_active_session = _proxy_async(_pg_get_active_session_async)
    get_all_sessions = _proxy_async(_pg_get_all_sessions_async)
    switch_session = _proxy_async(_pg_switch_session_async)
    rename_session = _proxy_async(_pg_rename_session_async)
    rename_session_if_placeholder = _proxy_async(
        _pg_rename_session_if_placeholder_async
    )
    delete_session = _proxy_async(_pg_delete_session_async)

    # Pipeline bookkeeping
    increment_message_count = _proxy_async(_pg_increment_message_count_async)
    get_session_messages_count = _proxy_async(_pg_get_message_count_async)
    get_session_conversation_summary = _proxy_async(
        _pg_get_session_conversation_summary_async
    )
    get_recent_active_sessions = _proxy_async(_pg_get_recent_active_sessions_async)

    # Encryption
    get_encryption_status = _proxy_async(_pg_get_encryption_status_async)
    get_all_encrypted_messages = _proxy_async(_pg_get_all_encrypted_messages_async)
    batch_decrypt_messages = _proxy_async(_pg_batch_decrypt_messages_async)

    # Auth
    create_session_token = _proxy_async(_pg_create_session_token_async)
    validate_session_token = _proxy_async(_pg_validate_session_token_async)
    revoke_session_token = _proxy_async(_pg_revoke_session_token_async)
    lookup_identity = _proxy_async(_pg_lookup_identity_async)
    lookup_unclaimed_profile = _proxy_async(_pg_lookup_unclaimed_profile_async)
    insert_default_profile_returning = _proxy_async(
        _pg_insert_default_profile_returning_async
    )
    update_profile_avatar = _proxy_async(_pg_update_profile_avatar_async)
    update_profile_user_name = _proxy_async(_pg_update_profile_user_name_async)
    insert_identity = _proxy_async(_pg_insert_identity_async)
    lookup_auth_me = _proxy_async(_pg_lookup_auth_me_async)

    @staticmethod
    async def update_message(
        message_id: int, content: str, _attachments: list[str] | None = None
    ) -> bool:
        return await _pg_update_message_async(message_id, content)

    @staticmethod
    def add_message(
        role: str,
        content: str,
        session_id: str | None = None,
        attachments: list[dict[str, Any]] | list[str] | None = None,
        *,
        user_id: str,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        turn_id: str | None = None,
    ) -> Any:
        """Add a message to a session (defaults to active session)."""
        _require_user_id("add_message", user_id)

        async def _call() -> int | None:
            return await _pg_add_message_async(
                await _resolve_session_id_async(session_id, user_id),
                role,
                content,
                attachments,
                user_id=user_id,
                tool_calls=tool_calls,
                tool_call_id=tool_call_id,
                turn_id=turn_id,
            )

        return _call()

    @staticmethod
    def get_messages(
        session_id: str | None = None, limit: int | None = None, *, user_id: str
    ) -> Any:
        """Get messages for a session (defaults to active session)."""
        _require_user_id("get_messages", user_id)

        async def _call() -> list[DBRow]:
            return await _pg_get_session_messages_async(
                await _resolve_session_id_async(session_id, user_id),
                limit or 100,
                user_id=user_id,
            )

        return _call()

    @staticmethod
    def get_chat_history(
        session_id: str | None = None,
        limit: int | None = None,
        recent: bool = False,
        *,
        user_id: str,
    ) -> Any:
        """Get chat history for a session (defaults to active session)."""
        _require_user_id("get_chat_history", user_id)

        async def _call() -> list[DBRow]:
            return await _pg_get_chat_history_async(
                await _resolve_session_id_async(session_id, user_id),
                limit,
                recent,
                user_id=user_id,
            )

        return _call()

    @staticmethod
    def get_chat_history_for_ai(
        session_id: str | None = None,
        limit: int | None = None,
        recent: bool = False,
        include_attachments: bool = False,
        *,
        user_id: str,
    ) -> Any:
        """Build message context for AI provider (defaults to active session)."""
        _require_user_id("get_chat_history_for_ai", user_id)

        async def _call() -> list[DBRow]:
            return await _pg_get_chat_history_for_ai_async(
                await _resolve_session_id_async(session_id, user_id),
                limit,
                recent,
                include_attachments,
                user_id=user_id,
            )

        return _call()

    @staticmethod
    def clear_session(session_id: str | None = None, *, user_id: str) -> Any:
        """Clear all messages for a session (defaults to active session)."""
        _require_user_id("clear_session", user_id)

        async def _call() -> bool:
            return await _pg_clear_session_messages_async(
                await _resolve_session_id_async(session_id, user_id), user_id=user_id
            )

        return _call()

    clear_chat_history = clear_session

    @staticmethod
    def add_session_event(
        content: str, interface: str = "terminal", *, user_id: str
    ) -> Any:
        """Add a session event message to the active session."""
        _require_user_id("add_session_event", user_id)

        async def _call() -> int | None:
            active = await _pg_get_active_session_async(user_id)
            return await _pg_add_session_event_async(
                str(active["id"]), content, interface, user_id=user_id
            )

        return _call()

    @staticmethod
    def add_system_note(
        content: str, session_id: str | None = None, *, user_id: str
    ) -> Any:
        """Add a system note message (defaults to active session)."""
        _require_user_id("add_system_note", user_id)

        async def _call() -> int | None:
            return await _pg_add_system_note_async(
                await _resolve_session_id_async(session_id, user_id),
                content,
                user_id=user_id,
            )

        return _call()


__all__ = [
    "Database",
    "TenantScopeError",
    "init_db",
]
