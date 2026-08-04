from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.core.logging_config import get_logger
from app.db.connection import (
    AsyncPgSession,
    pg_execute_async,
    pg_fetchall_async,
    pg_fetchone_async,
)
from app.db.queries import (
    ALL_TOOL_ROLES,
    DEFAULT_PROFILE_PARAMS,
    SCHEMA_DDL,
    SQL_ENC_ENCRYPTED_MESSAGES,
    SQL_ENC_TOTAL_MESSAGES,
    SQL_GLOBAL_KNOWLEDGE_DELETE,
    SQL_GLOBAL_KNOWLEDGE_GET,
    SQL_GLOBAL_KNOWLEDGE_INSERT,
    SQL_GLOBAL_KNOWLEDGE_LIST,
    SQL_GLOBAL_KNOWLEDGE_UPDATE,
    SQL_MESSAGE_CONVERSATION_SUMMARY,
    SQL_MESSAGE_COUNT_CONVERSATIONAL,
    SQL_MESSAGE_DELETE_FOR_SESSION,
    SQL_MESSAGE_HISTORY_FOR_AI_ASC_ALL,
    SQL_MESSAGE_HISTORY_FOR_AI_ASC_LIMIT,
    SQL_MESSAGE_HISTORY_FOR_AI_DESC_LIMIT,
    SQL_MESSAGE_INSERT,
    SQL_MESSAGE_SELECT_AFTER_ID,
    SQL_MESSAGE_SELECT_ASC_ALL,
    SQL_MESSAGE_SELECT_ASC_LIMIT,
    SQL_MESSAGE_SELECT_ASC_OFFSET_LIMIT,
    SQL_MESSAGE_SELECT_BEFORE_TS,
    SQL_MESSAGE_SELECT_CONTENT_BY_ID,
    SQL_MESSAGE_SELECT_DESC_LIMIT,
    SQL_MESSAGE_SELECT_ENCRYPTED,
    SQL_MESSAGE_UPDATE,
    SQL_MESSAGE_UPDATE_DECRYPTED,
    SQL_PIPELINE_STATE_CLAIM,
    SQL_PIPELINE_STATE_CLEAR,
    SQL_PIPELINE_STATE_SELECT,
    SQL_PIPELINE_STATE_UPDATE,
    SQL_PROFILE_INSERT_DEFAULT,
    SQL_PROFILE_SELECT_BY_ID,
    SQL_SESSION_ACTIVATE_ONE_SCOPED,
    SQL_SESSION_DEACTIVATE_FOR_USER,
    SQL_SESSION_DELETE_SCOPED,
    SQL_SESSION_INCREMENT_COUNT,
    SQL_SESSION_INSERT,
    SQL_SESSION_RENAME_PLACEHOLDER_SCOPED,
    SQL_SESSION_RENAME_SCOPED,
    SQL_SESSION_RESET_COUNT,
    SQL_SESSION_SELECT_ACTIVE_FOR_USER,
    SQL_SESSION_SELECT_ALL_FOR_USER,
    SQL_SESSIONS_RECENT_ACTIVE,
    TOOL_ROLES,
    build_encryption_status,
    build_profile_update,
    format_ai_history_rows,
    format_conversation_summary,
    format_public_history_rows,
    format_session_event,
    parse_global_knowledge_row,
    parse_message_row,
    parse_profile_row,
    parse_session_row,
)

log = get_logger(__name__)

type DBRow = dict[str, Any]

# Backward-compat re-export
__re_exports__ = (TOOL_ROLES, ALL_TOOL_ROLES)


# ---------------------------------------------------------------------------
# Schema initialization
# ---------------------------------------------------------------------------


async def init_pg_tables_async() -> None:
    """(｡•̀ᴗ-)✧"""
    async with AsyncPgSession() as s:
        for statement in SCHEMA_DDL:
            await s.execute(statement)
    log.info("PostgreSQL tables initialized (async)")


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


async def get_profile_async(user_id: str) -> DBRow:
    row = await pg_fetchone_async(SQL_PROFILE_SELECT_BY_ID, (user_id,))
    if not row:
        now = datetime.now()
        await pg_execute_async(
            SQL_PROFILE_INSERT_DEFAULT, (*DEFAULT_PROFILE_PARAMS, now, now)
        )
        row = await pg_fetchone_async(SQL_PROFILE_SELECT_BY_ID, (user_id,))
    return parse_profile_row(row)


async def update_profile_async(updates: dict[str, Any], user_id: str) -> bool:
    if not updates:
        return False
    built = build_profile_update(updates)
    if built is None:
        return False
    query, params = built
    query += " WHERE id = %s"
    params.append(user_id)
    try:
        await pg_execute_async(query, tuple(params))
        return True
    except Exception as e:  # noqa: BLE001
        log.error("update_profile_async failed: %s", e)
        return False


async def get_model_parameters_async(user_id: str) -> DBRow:
    return (await get_profile_async(user_id)).get("model_parameters", {})


async def update_model_parameters_async(
    model_parameters_dict: dict[str, Any], user_id: str
) -> bool:
    return await update_profile_async(
        {"model_parameters": model_parameters_dict}, user_id
    )


async def list_global_knowledge_async(user_id: str) -> list[DBRow]:
    rows = await pg_fetchall_async(SQL_GLOBAL_KNOWLEDGE_LIST, (user_id,))
    return [parse_global_knowledge_row(row) for row in rows]


async def get_global_knowledge_async(entry_id: str, user_id: str) -> DBRow:
    row = await pg_fetchone_async(SQL_GLOBAL_KNOWLEDGE_GET, (entry_id, user_id))
    return parse_global_knowledge_row(row)


async def create_global_knowledge_async(
    category: str, content: str, sort_order: int, enabled: bool, user_id: str
) -> DBRow:
    async with AsyncPgSession() as s:
        row = await s.execute_returning(
            SQL_GLOBAL_KNOWLEDGE_INSERT,
            (user_id, category, content, sort_order, enabled),
        )
    return parse_global_knowledge_row(row)


async def update_global_knowledge_async(
    entry_id: str,
    category: str,
    content: str,
    sort_order: int,
    enabled: bool,
    user_id: str,
) -> DBRow:
    async with AsyncPgSession() as s:
        row = await s.execute_returning(
            SQL_GLOBAL_KNOWLEDGE_UPDATE,
            (category, content, sort_order, enabled, entry_id, user_id),
        )
    return parse_global_knowledge_row(row)


async def delete_global_knowledge_async(entry_id: str, user_id: str) -> bool:
    row = await pg_fetchone_async(SQL_GLOBAL_KNOWLEDGE_DELETE, (entry_id, user_id))
    return row is not None


# ---------------------------------------------------------------------------
# Chat sessions
# ---------------------------------------------------------------------------


async def get_active_session_async(user_id: str) -> DBRow:
    row = await pg_fetchone_async(SQL_SESSION_SELECT_ACTIVE_FOR_USER, (user_id,))
    if not row:
        now = datetime.now()
        await pg_execute_async(
            SQL_SESSION_INSERT, (user_id, "New Chat", True, 0, now, now)
        )
        row = await pg_fetchone_async(SQL_SESSION_SELECT_ACTIVE_FOR_USER, (user_id,))
    return parse_session_row(row)


async def get_all_sessions_async(user_id: str) -> list[DBRow]:
    rows = await pg_fetchall_async(SQL_SESSION_SELECT_ALL_FOR_USER, (user_id,))
    return [parse_session_row(r) for r in rows]


async def create_session_async(name: str = "New Chat", *, user_id: str) -> str | None:
    now = datetime.now()
    try:
        async with AsyncPgSession() as s:
            row = await s.execute_returning(
                SQL_SESSION_INSERT, (user_id, name, False, 0, now, now)
            )
            return row.get("id") if row else None
    except Exception as e:  # noqa: BLE001
        log.error("create_session_async failed: %s", e)
        return None


async def switch_session_async(session_id: str, user_id: str) -> bool:
    try:
        async with AsyncPgSession() as s:
            await s.execute(SQL_SESSION_DEACTIVATE_FOR_USER, (user_id,))
            activated = await s.execute_returning(
                SQL_SESSION_ACTIVATE_ONE_SCOPED,
                (datetime.now(), session_id, user_id),
            )
            if not activated:
                raise ValueError("session not found for current user")
        return True
    except Exception as e:  # noqa: BLE001
        log.error("switch_session_async failed: %s", e)
        return False


async def rename_session_async(session_id: str, new_name: str, user_id: str) -> bool:
    try:
        row = await pg_fetchone_async(
            SQL_SESSION_RENAME_SCOPED,
            (new_name, datetime.now(), session_id, user_id),
        )
        return row is not None
    except Exception as e:  # noqa: BLE001
        log.error("rename_session_async failed: %s", e)
        return False


async def rename_session_if_placeholder_async(
    session_id: str, new_name: str, user_id: str
) -> bool:
    """(｡•̀ᴗ-)✧"""
    try:
        row = await pg_fetchone_async(
            SQL_SESSION_RENAME_PLACEHOLDER_SCOPED,
            (new_name, datetime.now(), session_id, user_id),
        )
        return row is not None
    except Exception as e:  # noqa: BLE001
        log.error("rename_session_if_placeholder_async failed: %s", e)
        return False


async def delete_session_async(session_id: str, user_id: str) -> bool:
    try:
        async with AsyncPgSession() as s:
            await s.execute(SQL_SESSION_DELETE_SCOPED, (session_id, user_id))
        return True
    except Exception as e:  # noqa: BLE001
        log.error("delete_session_async failed: %s", e)
        return False


async def increment_message_count_async(session_id: str) -> bool:
    try:
        await pg_execute_async(
            SQL_SESSION_INCREMENT_COUNT, (datetime.now(), session_id)
        )
        return True
    except Exception as e:  # noqa: BLE001
        log.error("increment_message_count_async failed: %s", e)
        return False


async def get_pipeline_state_async(session_id: str, user_id: str) -> DBRow:
    """(｡•̀ᴗ-)✧"""
    row = await pg_fetchone_async(SQL_PIPELINE_STATE_SELECT, (session_id, user_id))
    state = row.get("memory_pipeline_state") if row else None
    return state if isinstance(state, dict) else {}


async def update_pipeline_state_async(
    session_id: str, state: dict[str, Any], user_id: str
) -> bool:
    """(｡•̀ᴗ-)✧"""
    try:
        existing = await get_pipeline_state_async(session_id, user_id)
        existing.update(state)
        await pg_execute_async(
            SQL_PIPELINE_STATE_UPDATE,
            (json.dumps(existing), datetime.now(), session_id, user_id),
        )
        return True
    except Exception as e:
        log.error("update_pipeline_state_async failed: %s", e)
        return False


async def claim_pipeline_fence_async(
    session_id: str,
    user_id: str,
    fence_count: int,
    fence_since: str,
    stale_before: str,
) -> DBRow | None:
    """(｡•̀ᴗ-)✧"""
    async with AsyncPgSession() as session:
        return await session.execute_returning(
            SQL_PIPELINE_STATE_CLAIM,
            (
                fence_count,
                fence_since,
                datetime.now(),
                session_id,
                user_id,
                stale_before,
            ),
        )


async def clear_pipeline_fence_async(session_id: str, user_id: str) -> DBRow | None:
    """(｡•̀ᴗ-)✧"""
    async with AsyncPgSession() as session:
        return await session.execute_returning(
            SQL_PIPELINE_STATE_CLEAR, (datetime.now(), session_id, user_id)
        )


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


async def add_message_async(
    session_id: str,
    role: str,
    content: str,
    attachments: list[dict[str, Any]] | list[str] | None = None,
    *,
    user_id: str,
    tool_calls: list[dict[str, Any]] | None = None,
    tool_call_id: str | None = None,
    turn_id: str | None = None,
) -> int | None:
    """Insert a message row, bump the session's message_count, return id.

    Timestamp is set by database NOW() to ensure ordering coherence.
    """
    import json

    paths_json = json.dumps(attachments or [])
    tool_calls_json = json.dumps(tool_calls) if tool_calls else None
    try:
        async with AsyncPgSession() as s:
            row = await s.execute_returning(
                SQL_MESSAGE_INSERT,
                (
                    session_id,
                    user_id,
                    role,
                    content,
                    paths_json,
                    tool_calls_json,
                    tool_call_id,
                    turn_id,
                ),
            )
            if row:
                _ = await increment_message_count_async(session_id)
                return row.get("id")
        return None
    except Exception as e:
        log.error("add_message_async failed: %s", e)
        return None


async def update_message_async(message_id: int, content: str) -> bool:
    """Update the content of an existing message (async)."""
    try:
        await pg_execute_async(SQL_MESSAGE_UPDATE, (content, None, message_id))
        return True
    except Exception as e:
        log.error("update_message_async failed: %s", e)
        return False


async def get_session_messages_async(
    session_id: str,
    limit: int = 100,
    order: str = "ASC",
    *,
    user_id: str,
    offset: int = 0,
) -> list[DBRow]:
    """Fetch messages for a session in chronological order.

    order: "ASC" (oldest first) or "DESC" (newest first).
    """
    if offset and order.upper() == "ASC":
        query = SQL_MESSAGE_SELECT_ASC_OFFSET_LIMIT
    elif order.upper() == "DESC":
        query = SQL_MESSAGE_SELECT_DESC_LIMIT
    else:
        query = SQL_MESSAGE_SELECT_ASC_LIMIT
    params = (
        (session_id, user_id, limit, offset)
        if offset and order.upper() == "ASC"
        else (session_id, user_id, limit)
    )
    rows = await pg_fetchall_async(query, params)
    return [parse_message_row(r) for r in rows]


async def get_session_messages_after_id_async(
    session_id: str, after_message_id: str, limit: int = 1000, *, user_id: str
) -> list[DBRow]:
    """Fetch messages for a session after a specific message ID.

    Used by memory pipeline for ID-based tracking. Returns messages
    with id > after_message_id, ordered by id ascending.
    """
    rows = await pg_fetchall_async(
        SQL_MESSAGE_SELECT_AFTER_ID, (session_id, user_id, after_message_id, limit)
    )
    return [parse_message_row(r) for r in rows]


async def get_chat_history_before_ts_async(
    session_id: str,
    before_ts: str,
    limit: int = 50,
    *,
    user_id: str,
) -> list[DBRow]:
    """Fetch history chunk before a specific timestamp for infinite scroll."""
    rows = await pg_fetchall_async(
        SQL_MESSAGE_SELECT_BEFORE_TS, (session_id, user_id, before_ts, limit)
    )
    rows = list(reversed(rows))
    return _trim_public_history_blocks(format_public_history_rows(rows))


async def get_chat_history_async(
    session_id: str,
    limit: int | None = None,
    recent: bool = False,
    *,
    user_id: str,
) -> list[DBRow]:
    if limit and recent:
        rows = await pg_fetchall_async(
            SQL_MESSAGE_SELECT_DESC_LIMIT, (session_id, user_id, limit)
        )
        rows = list(reversed(rows))
    elif limit:
        rows = await pg_fetchall_async(
            SQL_MESSAGE_SELECT_ASC_LIMIT, (session_id, user_id, limit)
        )
    else:
        rows = await pg_fetchall_async(
            SQL_MESSAGE_SELECT_ASC_ALL, (session_id, user_id)
        )
    return _trim_public_history_blocks(format_public_history_rows(rows))


def _trim_public_history_blocks(messages: list[DBRow]) -> list[DBRow]:
    """(｡•̀ᴗ-)✧"""
    result: list[DBRow] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.get("role") != "assistant" or not message.get("tool_calls"):
            if message.get("role") != "tool":
                result.append(message)
            index += 1
            continue
        call_ids = {
            call.get("id")
            for call in message["tool_calls"]
            if isinstance(call, dict) and isinstance(call.get("id"), str)
        }
        block = [message]
        index += 1
        while index < len(messages) and call_ids:
            response = messages[index]
            if (
                response.get("role") != "tool"
                or response.get("tool_call_id") not in call_ids
            ):
                break
            block.append(response)
            call_ids.remove(response["tool_call_id"])
            index += 1
        if not call_ids:
            result.extend(block)
    return result


async def clear_session_messages_async(session_id: str, *, user_id: str) -> bool:
    try:
        await pg_execute_async(SQL_MESSAGE_DELETE_FOR_SESSION, (session_id, user_id))
        await pg_execute_async(
            SQL_SESSION_RESET_COUNT,
            (datetime.now(), session_id, user_id),
        )
        return True
    except Exception as e:  # noqa: BLE001
        log.error("clear_session_messages_async failed: %s", e)
        return False


async def get_message_count_async(session_id: str, user_id: str | None = None) -> int:
    """Count conversational messages, optionally scoped to their owner."""
    if user_id:
        row = await pg_fetchone_async(
            "SELECT COUNT(*) AS cnt FROM messages WHERE session_id = %s AND user_id = %s AND role IN ('user', 'assistant')",
            (session_id, user_id),
        )
    else:
        row = await pg_fetchone_async(SQL_MESSAGE_COUNT_CONVERSATIONAL, (session_id,))
    return row.get("cnt", 0) if row else 0


async def add_session_event_async(
    session_id: str, content: str, interface: str = "terminal", *, user_id: str
) -> int | None:
    return await add_message_async(
        session_id, "system", format_session_event(content, interface), user_id=user_id
    )


async def get_recent_active_sessions_async(
    user_id: str, current_session_id: str, limit: int = 5
) -> list[DBRow]:
    """Fetch recently active sessions for meta-awareness block.

    Returns sessions ordered by last activity, excluding the current session.
    Used by the LLM context system to show session-switching context.
    """
    rows = await pg_fetchall_async(
        SQL_SESSIONS_RECENT_ACTIVE, (current_session_id, user_id, limit)
    )
    return [
        {
            "id": r.get("id"),
            "name": r.get("name", "Unnamed Session"),
            "updated_at": str(r.get("updated_at", "")),
            "message_count": r.get("message_count", 0),
            "is_active": r.get("is_active", False),
        }
        for r in rows
    ]


async def get_session_conversation_summary_async(
    session_id: str, limit: int = 20, *, user_id: str
) -> str:
    rows = await pg_fetchall_async(
        SQL_MESSAGE_CONVERSATION_SUMMARY, (session_id, user_id, limit)
    )
    return format_conversation_summary(rows)


async def add_system_note_async(
    session_id: str, content: str, *, user_id: str
) -> int | None:
    return await add_message_async(session_id, "system", content, user_id=user_id)


# ---------------------------------------------------------------------------
# AI history
# ---------------------------------------------------------------------------


async def get_chat_history_for_ai_async(
    session_id: str,
    limit: int | None = None,
    recent: bool = False,
    include_attachments: bool = False,
    *,
    user_id: str,
) -> list[DBRow]:
    if limit and recent:
        rows = await pg_fetchall_async(
            SQL_MESSAGE_HISTORY_FOR_AI_DESC_LIMIT, (session_id, user_id, limit)
        )
        rows = list(reversed(rows))
    elif limit:
        rows = await pg_fetchall_async(
            SQL_MESSAGE_HISTORY_FOR_AI_ASC_LIMIT, (session_id, user_id, limit)
        )
    else:
        rows = await pg_fetchall_async(
            SQL_MESSAGE_HISTORY_FOR_AI_ASC_ALL, (session_id, user_id)
        )
    formatted = format_ai_history_rows(rows, include_attachments=include_attachments)
    return _trim_tool_history_blocks(formatted)


def _trim_tool_history_blocks(messages: list[DBRow]) -> list[DBRow]:
    """(｡•̀ᴗ-)✧"""
    result: list[DBRow] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.get("role") != "assistant" or not message.get("tool_calls"):
            if message.get("role") != "tool":
                result.append(message)
            index += 1
            continue
        call_ids = {
            call.get("id")
            for call in message["tool_calls"]
            if isinstance(call, dict) and isinstance(call.get("id"), str)
        }
        block = [message]
        index += 1
        while index < len(messages) and call_ids:
            response = messages[index]
            if (
                response.get("role") != "tool"
                or response.get("tool_call_id") not in call_ids
            ):
                break
            block.append(response)
            call_ids.remove(response["tool_call_id"])
            index += 1
        if not call_ids:
            result.extend(block)
    return result


# ---------------------------------------------------------------------------
# Encryption status / migration helpers
# ---------------------------------------------------------------------------


async def get_encryption_status_async() -> DBRow:
    return build_encryption_status(
        await pg_fetchone_async(SQL_ENC_TOTAL_MESSAGES),
        await pg_fetchone_async(SQL_ENC_ENCRYPTED_MESSAGES),
    )


async def get_all_encrypted_messages_async() -> list[DBRow]:
    rows = await pg_fetchall_async(SQL_MESSAGE_SELECT_ENCRYPTED)
    return [parse_message_row(r) for r in rows]


async def batch_decrypt_messages_async(message_ids: list[int]) -> DBRow:
    decrypted_count = 0
    failed_count = 0
    for msg_id in message_ids:
        try:
            row = await pg_fetchone_async(SQL_MESSAGE_SELECT_CONTENT_BY_ID, (msg_id,))
            if row and row.get("content"):
                from app.core.encryption import encryptor

                plaintext = encryptor.decrypt(row["content"])
                await pg_execute_async(
                    SQL_MESSAGE_UPDATE_DECRYPTED,
                    (plaintext, msg_id),
                )
                decrypted_count += 1
        except Exception as e:  # noqa: BLE001
            failed_count += 1
            log.error("decrypt message %s failed: %s", msg_id, e)
    return {
        "decrypted": decrypted_count,
        "failed": failed_count,
        "total": len(message_ids),
    }


__all__ = [
    # Schema
    "init_pg_tables_async",
    # Profile
    "get_profile_async",
    "update_profile_async",
    "get_model_parameters_async",
    "update_model_parameters_async",
    "list_global_knowledge_async",
    "get_global_knowledge_async",
    "create_global_knowledge_async",
    "update_global_knowledge_async",
    "delete_global_knowledge_async",
    # Sessions
    "get_active_session_async",
    "get_all_sessions_async",
    "create_session_async",
    "switch_session_async",
    "rename_session_async",
    "rename_session_if_placeholder_async",
    "delete_session_async",
    "increment_message_count_async",
    "get_pipeline_state_async",
    "update_pipeline_state_async",
    # Messages
    "add_message_async",
    "update_message_async",
    "get_session_messages_async",
    "get_session_messages_after_id_async",
    "get_chat_history_async",
    "get_chat_history_before_ts_async",
    "clear_session_messages_async",
    "get_message_count_async",
    "add_session_event_async",
    "get_recent_active_sessions_async",
    "get_session_conversation_summary_async",
    "add_system_note_async",
    # AI history
    "get_chat_history_for_ai_async",
    # Encryption
    "get_encryption_status_async",
    "get_all_encrypted_messages_async",
    "batch_decrypt_messages_async",
    # Tool roles (re-exported for backward-compat imports)
]

# ---------------------------------------------------------------------------
# Auth and Session Token operations
# ---------------------------------------------------------------------------


async def create_session_token_async(
    token: str, user_id: str, now: datetime, expires_at: datetime
) -> None:
    from app.db.queries import SQL_SESSION_TOKEN_CREATE

    await pg_execute_async(SQL_SESSION_TOKEN_CREATE, (token, user_id, now, expires_at))


async def validate_session_token_async(token: str) -> DBRow | None:
    from app.db.queries import SQL_SESSION_TOKEN_VALIDATE

    return await pg_fetchone_async(SQL_SESSION_TOKEN_VALIDATE, (token,))


async def revoke_session_token_async(token: str, now: datetime) -> None:
    from app.db.queries import SQL_SESSION_TOKEN_REVOKE

    await pg_execute_async(SQL_SESSION_TOKEN_REVOKE, (now, token))


async def lookup_identity_async(provider: str, provider_sub: str) -> DBRow | None:
    from app.db.queries import SQL_IDENTITY_LOOKUP

    return await pg_fetchone_async(SQL_IDENTITY_LOOKUP, (provider, provider_sub))


async def lookup_unclaimed_profile_async() -> DBRow | None:
    from app.db.queries import SQL_PROFILE_UNCLAIMED_LOOKUP

    return await pg_fetchone_async(SQL_PROFILE_UNCLAIMED_LOOKUP)


async def insert_default_profile_returning_async(
    params: tuple[Any, ...], created_at: datetime, updated_at: datetime
) -> DBRow | None:
    from app.db.queries import SQL_PROFILE_INSERT_DEFAULT_RETURNING

    return await pg_fetchone_async(
        SQL_PROFILE_INSERT_DEFAULT_RETURNING, (*params, created_at, updated_at)
    )


async def update_profile_avatar_async(
    user_id: str, avatar_url: str, now: datetime
) -> None:
    from app.db.queries import SQL_PROFILE_UPDATE_AVATAR

    await pg_execute_async(SQL_PROFILE_UPDATE_AVATAR, (avatar_url, now, user_id))


async def update_profile_user_name_async(
    user_id: str, user_name: str, now: datetime
) -> None:
    from app.db.queries import SQL_PROFILE_UPDATE_DISPLAY_NAME

    await pg_execute_async(SQL_PROFILE_UPDATE_DISPLAY_NAME, (user_name, now, user_id))


async def insert_identity_async(
    user_id: str, provider: str, provider_sub: str, email: str | None
) -> None:
    from app.db.queries import SQL_IDENTITY_INSERT

    await pg_execute_async(
        SQL_IDENTITY_INSERT, (user_id, provider, provider_sub, email)
    )


async def lookup_auth_me_async(user_id: str) -> DBRow | None:
    from app.db.queries import SQL_AUTH_ME_LOOKUP

    return await pg_fetchone_async(SQL_AUTH_ME_LOOKUP, (user_id,))
