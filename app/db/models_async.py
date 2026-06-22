# FILE: app.db.models_async.py
# DESCRIPTION: Async PostgreSQL repository.
#
#   Mirror of app.db.models.py but using AsyncPgSession + the
#   pg_*_async helpers. SQL strings and row parsers are imported from
#   app.db.queries so the two layers stay byte-identical.

from __future__ import annotations

from datetime import datetime

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
    SQL_APIKEY_DELETE,
    SQL_APIKEY_INSERT,
    SQL_APIKEY_SELECT_ALL,
    SQL_APIKEY_SELECT_BY_NAME,
    SQL_APIKEY_SELECT_ID_BY_NAME,
    SQL_APIKEY_UPDATE,
    SQL_ENC_ENCRYPTED_KEYS,
    SQL_ENC_ENCRYPTED_MESSAGES,
    SQL_ENC_TOTAL_KEYS,
    SQL_ENC_TOTAL_MESSAGES,
    SQL_MESSAGE_CONVERSATION_SUMMARY,
    SQL_MESSAGE_COUNT_CONVERSATIONAL,
    SQL_MESSAGE_DELETE_FOR_SESSION,
    SQL_MESSAGE_HISTORY_FOR_AI_ASC_ALL,
    SQL_MESSAGE_HISTORY_FOR_AI_ASC_LIMIT,
    SQL_MESSAGE_HISTORY_FOR_AI_DESC_LIMIT,
    SQL_MESSAGE_INSERT,
    SQL_MESSAGE_RECENT_SYSTEM_FOR_SESSION,
    SQL_MESSAGE_RECENT_SYSTEM_GLOBAL,
    SQL_MESSAGE_SELECT_ASC_ALL,
    SQL_MESSAGE_SELECT_ASC_LIMIT,
    SQL_MESSAGE_SELECT_AFTER_ID,
    SQL_MESSAGE_SELECT_CONTENT_BY_ID,
    SQL_MESSAGE_SELECT_DESC_LIMIT,
    SQL_MESSAGE_SELECT_ENCRYPTED,
    SQL_MESSAGE_UPDATE,
    SQL_MESSAGE_UPDATE_DECRYPTED,
    SQL_PROFILE_INSERT_DEFAULT,
    SQL_PROFILE_SELECT_FIRST,
    SQL_PROFILE_SELECT_BY_ID,
    SQL_SESSION_ACTIVATE_ONE_SCOPED,
    SQL_SESSION_ACTIVATE_ONE,
    SQL_SESSION_DEACTIVATE_ALL,
    SQL_SESSION_DEACTIVATE_FOR_USER,
    SQL_SESSION_DELETE,
    SQL_SESSION_DELETE_SCOPED,
    SQL_SESSION_INCREMENT_COUNT,
    SQL_SESSION_INSERT,
    SQL_SESSION_MEMORY_NOTES,
    SQL_SESSION_RENAME,
    SQL_SESSION_RENAME_SCOPED,
    SQL_SESSION_RESET_COUNT_AND_MEMORY,
    SQL_SESSION_SELECT_ACTIVE,
    SQL_SESSION_SELECT_ACTIVE_FOR_USER,
    SQL_SESSION_SELECT_ALL,
    SQL_SESSION_SELECT_ALL_FOR_USER,
    SQL_SESSION_UPDATE_MEMORY,
    SQL_SESSIONS_RECENT_ACTIVE,
    TOOL_ROLES,
    build_encryption_status,
    build_profile_update,
    decrypt_api_key_rows,
    encrypt_api_key,
    format_ai_history_rows,
    format_conversation_summary,
    format_session_event,
    parse_event_row,
    parse_message_row,
    parse_profile_row,
    parse_session_memory_rows,
    parse_session_row,
    tool_role_for,
)
from app.logging_config import get_logger

import json

log = get_logger(__name__)

# Backward-compat re-export
__re_exports__ = (TOOL_ROLES, ALL_TOOL_ROLES)


# ---------------------------------------------------------------------------
# Schema initialization
# ---------------------------------------------------------------------------


async def init_pg_tables_async() -> None:
    """Create PostgreSQL tables and indexes if missing."""
    async with AsyncPgSession() as s:
        for ddl in SCHEMA_DDL:
            await s.execute(ddl)
    log.info("PostgreSQL tables initialized (async)")


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


async def get_profile_async(user_id: str | None = None) -> dict:
    if user_id is not None:
        row = await pg_fetchone_async(SQL_PROFILE_SELECT_BY_ID, (user_id,))
    else:
        row = await pg_fetchone_async(SQL_PROFILE_SELECT_FIRST)
    if not row:
        now = datetime.now()
        await pg_execute_async(
            SQL_PROFILE_INSERT_DEFAULT, (*DEFAULT_PROFILE_PARAMS, now, now)
        )
        row = await pg_fetchone_async(SQL_PROFILE_SELECT_FIRST)
    return parse_profile_row(row)


async def update_profile_async(updates: dict, user_id: str | None = None) -> bool:
    if not updates:
        return False
    built = build_profile_update(updates)
    if built is None:
        return False
    query, params = built
    if user_id is not None:
        query += " WHERE id = %s"
        params.append(user_id)
    try:
        await pg_execute_async(query, params)
        return True
    except Exception as e:  # noqa: BLE001
        log.error("update_profile_async failed: %s", e)
        return False


async def get_context_async(user_id: str | None = None) -> dict:
    return (await get_profile_async(user_id)).get("context", {})


async def update_context_async(context_dict: dict, user_id: str | None = None) -> bool:
    return await update_profile_async({"context": context_dict}, user_id)


async def get_memory_async(user_id: str | None = None) -> dict:
    return (await get_profile_async(user_id)).get("memory", {})


async def update_memory_async(memory_dict: dict, user_id: str | None = None) -> bool:
    return await update_profile_async({"memory": memory_dict}, user_id)


# ---------------------------------------------------------------------------
# Chat sessions
# ---------------------------------------------------------------------------


async def get_active_session_async(user_id: str | None = None) -> dict:
    if user_id is not None:
        row = await pg_fetchone_async(SQL_SESSION_SELECT_ACTIVE_FOR_USER, (user_id,))
        if not row:
            now = datetime.now()
            await pg_execute_async(
                SQL_SESSION_INSERT, (user_id, "New Chat", True, 0, "{}", now, now)
            )
            row = await pg_fetchone_async(SQL_SESSION_SELECT_ACTIVE_FOR_USER, (user_id,))
    else:
        row = await pg_fetchone_async(SQL_SESSION_SELECT_ACTIVE)
        if not row:
            now = datetime.now()
            fallback_uid = (await get_profile_async())["id"]
            await pg_execute_async(
                SQL_SESSION_INSERT, (fallback_uid, "New Chat", True, 0, "{}", now, now)
            )
            row = await pg_fetchone_async(SQL_SESSION_SELECT_ACTIVE)
    return parse_session_row(row)


async def get_all_sessions_async(user_id: str | None = None) -> list[dict]:
    if user_id is not None:
        rows = await pg_fetchall_async(SQL_SESSION_SELECT_ALL_FOR_USER, (user_id,))
    else:
        rows = await pg_fetchall_async(SQL_SESSION_SELECT_ALL)
    return [parse_session_row(r) for r in rows]


async def create_session_async(name: str = "New Chat", user_id: str | None = None) -> str | None:
    if user_id is None:
        user_id = (await get_profile_async())["id"]
    now = datetime.now()
    try:
        async with AsyncPgSession() as s:
            row = await s.execute_returning(
                SQL_SESSION_INSERT, (user_id, name, False, 0, "{}", now, now)
            )
            return row.get("id") if row else None
    except Exception as e:  # noqa: BLE001
        log.error("create_session_async failed: %s", e)
        return None


async def switch_session_async(session_id: str, user_id: str | None = None) -> bool:
    try:
        async with AsyncPgSession() as s:
            if user_id is not None:
                await s.execute(SQL_SESSION_DEACTIVATE_FOR_USER, (user_id,))
                await s.execute(SQL_SESSION_ACTIVATE_ONE_SCOPED, (datetime.now(), session_id, user_id))
            else:
                await s.execute(SQL_SESSION_DEACTIVATE_ALL)
                await s.execute(SQL_SESSION_ACTIVATE_ONE, (datetime.now(), session_id))
        return True
    except Exception as e:  # noqa: BLE001
        log.error("switch_session_async failed: %s", e)
        return False


async def rename_session_async(session_id: str, new_name: str, user_id: str | None = None) -> bool:
    try:
        if user_id is not None:
            await pg_execute_async(
                SQL_SESSION_RENAME_SCOPED, (new_name, datetime.now(), session_id, user_id)
            )
        else:
            await pg_execute_async(
                SQL_SESSION_RENAME, (new_name, datetime.now(), session_id)
            )
        return True
    except Exception as e:  # noqa: BLE001
        log.error("rename_session_async failed: %s", e)
        return False


async def delete_session_async(session_id: str, user_id: str | None = None) -> bool:
    try:
        async with AsyncPgSession() as s:
            if user_id is not None:
                await s.execute(SQL_SESSION_DELETE_SCOPED, (session_id, user_id))
            else:
                await s.execute(SQL_SESSION_DELETE, (session_id,))
        return True
    except Exception as e:  # noqa: BLE001
        log.error("delete_session_async failed: %s", e)
        return False


async def update_session_memory_async(session_id: str, memory: dict) -> bool:
    try:
        await pg_execute_async(
            SQL_SESSION_UPDATE_MEMORY,
            (json.dumps(memory), datetime.now(), session_id),
        )
        return True
    except Exception as e:  # noqa: BLE001
        log.error("update_session_memory_async failed: %s", e)
        return False


async def get_session_memory_async(session_id: str, user_id: str | None = None) -> dict:
    rows = await pg_fetchall_async(SQL_SESSION_MEMORY_NOTES, (session_id,))
    return parse_session_memory_rows(rows)


async def increment_message_count_async(session_id: str) -> bool:
    try:
        await pg_execute_async(
            SQL_SESSION_INCREMENT_COUNT, (datetime.now(), session_id)
        )
        return True
    except Exception as e:  # noqa: BLE001
        log.error("increment_message_count_async failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Pipeline state (stored in memory_state)
# ---------------------------------------------------------------------------


async def get_memory_state_async(session_id: str) -> dict:
    """Get pipeline state from session's memory_state.

    Returns dict with:
        - last_segmented_count: int
        - last_segmented_at: ISO timestamp
    """
    row = await pg_fetchone_async(
        "SELECT memory_state FROM chat_sessions WHERE id = %s", (session_id,)
    )
    if not row:
        return {"last_segmented_count": 0}

    ms = row.get("memory_state")
    if not ms:
        return {"last_segmented_count": 0}

    # JSONB column - already dict from psycopg v3
    if isinstance(ms, dict):
        return ms
    else:
        return {"last_segmented_count": 0}


async def update_memory_state_async(session_id: str, state: dict) -> bool:
    """Update pipeline state in session's memory_state.

    Merges with existing state.
    """
    try:
        existing = await get_memory_state_async(session_id)
        existing.update(state)
        await pg_execute_async(
            "UPDATE chat_sessions SET memory_state = %s, updated_at = %s WHERE id = %s",
            (json.dumps(existing), datetime.now(), session_id),
        )
        return True
    except Exception as e:
        log.error("update_memory_state_async failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------


async def get_api_keys_async(key_name: str | None = None) -> dict[str, str]:
    if key_name:
        rows = await pg_fetchall_async(SQL_APIKEY_SELECT_BY_NAME, (key_name,))
    else:
        rows = await pg_fetchall_async(SQL_APIKEY_SELECT_ALL)
    return decrypt_api_key_rows(rows)


async def get_api_key_async(key_name: str) -> str | None:
    return (await get_api_keys_async(key_name)).get(key_name)


async def add_api_key_async(key_name: str, key_value: str) -> bool:
    encrypted = encrypt_api_key(key_value)
    is_encrypted = encrypted != key_value
    try:
        existing = await pg_fetchone_async(SQL_APIKEY_SELECT_ID_BY_NAME, (key_name,))
        if existing:
            await pg_execute_async(
                SQL_APIKEY_UPDATE, (encrypted, is_encrypted, key_name)
            )
        else:
            await pg_execute_async(
                SQL_APIKEY_INSERT,
                (key_name, encrypted, is_encrypted, datetime.now()),
            )
        return True
    except Exception as e:  # noqa: BLE001
        log.error("add_api_key_async failed: %s", e)
        return False


async def remove_api_key_async(key_name: str) -> bool:
    try:
        await pg_execute_async(SQL_APIKEY_DELETE, (key_name,))
        return True
    except Exception as e:  # noqa: BLE001
        log.error("remove_api_key_async failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


async def add_message_async(
    session_id: str,
    role: str,
    content: str,
    image_paths: list[str] | None = None,
    user_id: str | None = None,
) -> int | None:
    """Insert a message row, bump the session's message_count, return id.

    Timestamp is set by database NOW() to ensure ordering coherence.
    """
    import json

    if user_id is None:
        user_id = (await get_profile_async())["id"]
    paths_json = json.dumps(image_paths or [])
    try:
        async with AsyncPgSession() as s:
            row = await s.execute_returning(
                SQL_MESSAGE_INSERT,
                (session_id, user_id, role, content, paths_json),
            )
            if row:
                await increment_message_count_async(session_id)
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
    session_id: str, limit: int = 100, order: str = "ASC"
) -> list[dict]:
    """Fetch messages for a session in chronological order.

    order: "ASC" (oldest first) or "DESC" (newest first).
    """
    if order.upper() == "DESC":
        query = SQL_MESSAGE_SELECT_DESC_LIMIT
    else:
        query = SQL_MESSAGE_SELECT_ASC_LIMIT
    rows = await pg_fetchall_async(query, (session_id, limit))
    return [parse_message_row(r) for r in rows]


async def get_session_messages_after_id_async(
    session_id: str, after_message_id: int, limit: int = 1000
) -> list[dict]:
    """Fetch messages for a session after a specific message ID.

    Used by memory pipeline for ID-based tracking. Returns messages
    with id > after_message_id, ordered by id ascending.
    """
    rows = await pg_fetchall_async(
        SQL_MESSAGE_SELECT_AFTER_ID, (session_id, after_message_id, limit)
    )
    return [parse_message_row(r) for r in rows]


async def get_recent_messages_async(session_id: str, limit: int = 20) -> list[dict]:
    return await get_session_messages_async(session_id, limit)


async def get_chat_history_async(
    session_id: str, limit: int | None = None, recent: bool = False,
    user_id: str | None = None,
) -> list[dict]:
    if limit and recent:
        rows = await pg_fetchall_async(
            SQL_MESSAGE_SELECT_DESC_LIMIT, (session_id, limit)
        )
        rows = list(reversed(rows))
    elif limit:
        rows = await pg_fetchall_async(
            SQL_MESSAGE_SELECT_ASC_LIMIT, (session_id, limit)
        )
    else:
        rows = await pg_fetchall_async(SQL_MESSAGE_SELECT_ASC_ALL, (session_id,))
    return [parse_message_row(r) for r in rows]


async def clear_session_messages_async(session_id: str) -> bool:
    try:
        await pg_execute_async(SQL_MESSAGE_DELETE_FOR_SESSION, (session_id,))
        await pg_execute_async(
            SQL_SESSION_RESET_COUNT_AND_MEMORY,
            (datetime.now(), session_id),
        )
        return True
    except Exception as e:  # noqa: BLE001
        log.error("clear_session_messages_async failed: %s", e)
        return False


async def get_message_count_async(session_id: str) -> int:
    row = await pg_fetchone_async(SQL_MESSAGE_COUNT_CONVERSATIONAL, (session_id,))
    return row.get("cnt", 0) if row else 0


async def add_session_event_async(
    session_id: str, content: str, interface: str = "terminal"
) -> int | None:
    return await add_message_async(
        session_id, "system", format_session_event(content, interface)
    )


async def get_recent_sessions_async(limit: int = 20) -> list[dict]:
    rows = await pg_fetchall_async(SQL_MESSAGE_RECENT_SYSTEM_GLOBAL, (limit,))
    return [parse_event_row(r) for r in rows]


async def get_recent_sessions_for_session_async(
    session_id: str, limit: int = 20
) -> list[dict]:
    rows = await pg_fetchall_async(
        SQL_MESSAGE_RECENT_SYSTEM_FOR_SESSION, (session_id, limit)
    )
    return [parse_event_row(r) for r in rows]


async def get_recent_active_sessions_async(
    current_session_id: str, limit: int = 5
) -> list[dict]:
    """Fetch recently active sessions for meta-awareness block.

    Returns sessions ordered by last activity, excluding the current session.
    Used by the LLM context system to show session-switching context.
    """
    rows = await pg_fetchall_async(
        SQL_SESSIONS_RECENT_ACTIVE, (current_session_id, limit)
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
    session_id: str, limit: int = 20
) -> str:
    rows = await pg_fetchall_async(
        SQL_MESSAGE_CONVERSATION_SUMMARY, (session_id, limit)
    )
    return format_conversation_summary(rows)


async def add_tool_result_async(
    session_id: str, tool_name: str, result_content: str
) -> int | None:
    return await add_message_async(session_id, tool_role_for(tool_name), result_content)


async def add_system_note_async(session_id: str, content: str) -> int | None:
    return await add_message_async(session_id, "system", content)


async def add_memory_note_async(session_id: str, content: str) -> int | None:
    return await add_system_note_async(session_id, content)


# ---------------------------------------------------------------------------
# AI history
# ---------------------------------------------------------------------------


async def get_chat_history_for_ai_async(
    session_id: str,
    limit: int | None = None,
    recent: bool = False,
    include_image_paths: bool = False,
    user_id: str | None = None,
) -> list[dict]:
    if limit and recent:
        rows = await pg_fetchall_async(
            SQL_MESSAGE_HISTORY_FOR_AI_DESC_LIMIT, (session_id, limit)
        )
        rows = list(reversed(rows))
    elif limit:
        rows = await pg_fetchall_async(
            SQL_MESSAGE_HISTORY_FOR_AI_ASC_LIMIT, (session_id, limit)
        )
    else:
        rows = await pg_fetchall_async(
            SQL_MESSAGE_HISTORY_FOR_AI_ASC_ALL, (session_id,)
        )
    return format_ai_history_rows(rows, include_image_paths=include_image_paths)


# ---------------------------------------------------------------------------
# Encryption status / migration helpers
# ---------------------------------------------------------------------------


async def get_encryption_status_async() -> dict:
    return build_encryption_status(
        await pg_fetchone_async(SQL_ENC_TOTAL_MESSAGES),
        await pg_fetchone_async(SQL_ENC_ENCRYPTED_MESSAGES),
        await pg_fetchone_async(SQL_ENC_TOTAL_KEYS),
        await pg_fetchone_async(SQL_ENC_ENCRYPTED_KEYS),
    )


async def get_all_encrypted_messages_async() -> list[dict]:
    rows = await pg_fetchall_async(SQL_MESSAGE_SELECT_ENCRYPTED)
    return [parse_message_row(r) for r in rows]


async def batch_decrypt_messages_async(message_ids: list[int]) -> dict:
    decrypted_count = 0
    failed_count = 0
    for msg_id in message_ids:
        try:
            row = await pg_fetchone_async(SQL_MESSAGE_SELECT_CONTENT_BY_ID, (msg_id,))
            if row and row.get("content"):
                from app.encryption import encryptor

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
    "get_context_async",
    "update_context_async",
    "get_memory_async",
    "update_memory_async",
    # Sessions
    "get_active_session_async",
    "get_all_sessions_async",
    "create_session_async",
    "switch_session_async",
    "rename_session_async",
    "delete_session_async",
    "get_session_memory_async",
    "update_session_memory_async",
    "increment_message_count_async",
    "get_memory_state_async",
    "update_memory_state_async",
    # API keys
    "get_api_keys_async",
    "get_api_key_async",
    "add_api_key_async",
    "remove_api_key_async",
    # Messages
    "add_message_async",
    "update_message_async",
    "get_session_messages_async",
    "get_session_messages_after_id_async",
    "get_recent_messages_async",
    "get_chat_history_async",
    "clear_session_messages_async",
    "get_message_count_async",
    "add_session_event_async",
    "get_recent_sessions_async",
    "get_recent_sessions_for_session_async",
    "get_recent_active_sessions_async",
    "get_session_conversation_summary_async",
    "add_tool_result_async",
    "add_system_note_async",
    "add_memory_note_async",
    # AI history
    "get_chat_history_for_ai_async",
    # Encryption
    "get_encryption_status_async",
    "get_all_encrypted_messages_async",
    "batch_decrypt_messages_async",
    # Tool roles (re-exported for backward-compat imports)
    "TOOL_ROLES",
    "ALL_TOOL_ROLES",
]
