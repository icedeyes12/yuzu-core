# FILE: app/db_pg_models_async.py
# DESCRIPTION: Async PostgreSQL repository.
#
#   Mirror of app/db_pg_models.py but using AsyncPgSession + the
#   pg_*_async helpers. SQL strings and row parsers are imported from
#   app.db_queries so the two layers stay byte-identical.

from __future__ import annotations

from datetime import datetime

from app.db_pg import (
    AsyncPgSession,
    pg_execute_async,
    pg_fetchall_async,
    pg_fetchone_async,
)
from app.db_queries import (
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
    SQL_MESSAGE_SELECT_CONTENT_BY_ID,
    SQL_MESSAGE_SELECT_DESC_LIMIT,
    SQL_MESSAGE_SELECT_ENCRYPTED,
    SQL_MESSAGE_UPDATE_DECRYPTED,
    SQL_PROFILE_INSERT_DEFAULT,
    SQL_PROFILE_SELECT_FIRST,
    SQL_SESSION_ACTIVATE_ONE,
    SQL_SESSION_DEACTIVATE_ALL,
    SQL_SESSION_DELETE,
    SQL_SESSION_INCREMENT_COUNT,
    SQL_SESSION_INSERT,
    SQL_SESSION_MEMORY_NOTES,
    SQL_SESSION_RENAME,
    SQL_SESSION_RESET_COUNT_AND_MEMORY,
    SQL_SESSION_SELECT_ACTIVE,
    SQL_SESSION_SELECT_ALL,
    SQL_SESSION_UPDATE_MEMORY,
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


async def get_profile_async() -> dict:
    row = await pg_fetchone_async(SQL_PROFILE_SELECT_FIRST)
    if not row:
        now = datetime.now()
        await pg_execute_async(
            SQL_PROFILE_INSERT_DEFAULT, (*DEFAULT_PROFILE_PARAMS, now, now)
        )
        row = await pg_fetchone_async(SQL_PROFILE_SELECT_FIRST)
    return parse_profile_row(row)


async def update_profile_async(updates: dict) -> bool:
    if not updates:
        return False
    built = build_profile_update(updates)
    if built is None:
        return False
    query, params = built
    try:
        await pg_execute_async(query, params)
        return True
    except Exception as e:  # noqa: BLE001
        log.error("update_profile_async failed: %s", e)
        return False


async def get_context_async() -> dict:
    return (await get_profile_async()).get("context", {})


async def update_context_async(context_dict: dict) -> bool:
    return await update_profile_async({"context": context_dict})


async def get_memory_async() -> dict:
    return (await get_profile_async()).get("memory", {})


async def update_memory_async(memory_dict: dict) -> bool:
    return await update_profile_async({"memory": memory_dict})


# ---------------------------------------------------------------------------
# Chat sessions
# ---------------------------------------------------------------------------


async def get_active_session_async() -> dict:
    row = await pg_fetchone_async(SQL_SESSION_SELECT_ACTIVE)
    if not row:
        now = datetime.now()
        await pg_execute_async(
            SQL_SESSION_INSERT, ("New Chat", True, 0, "{}", now, now)
        )
        row = await pg_fetchone_async(SQL_SESSION_SELECT_ACTIVE)
    return parse_session_row(row)


async def get_all_sessions_async() -> list[dict]:
    rows = await pg_fetchall_async(SQL_SESSION_SELECT_ALL)
    return [parse_session_row(r) for r in rows]


async def create_session_async(name: str = "New Chat") -> int | None:
    now = datetime.now()
    try:
        async with AsyncPgSession() as s:
            row = await s.execute_returning(
                SQL_SESSION_INSERT, (name, False, 0, "{}", now, now)
            )
            return row.get("id") if row else None
    except Exception as e:  # noqa: BLE001
        log.error("create_session_async failed: %s", e)
        return None


async def switch_session_async(session_id: int) -> bool:
    try:
        async with AsyncPgSession() as s:
            await s.execute(SQL_SESSION_DEACTIVATE_ALL)
            await s.execute(
                SQL_SESSION_ACTIVATE_ONE, (datetime.now(), session_id)
            )
        return True
    except Exception as e:  # noqa: BLE001
        log.error("switch_session_async failed: %s", e)
        return False


async def rename_session_async(session_id: int, new_name: str) -> bool:
    try:
        await pg_execute_async(
            SQL_SESSION_RENAME, (new_name, datetime.now(), session_id)
        )
        return True
    except Exception as e:  # noqa: BLE001
        log.error("rename_session_async failed: %s", e)
        return False


async def delete_session_async(session_id: int) -> bool:
    try:
        async with AsyncPgSession() as s:
            await s.execute(SQL_SESSION_DELETE, (session_id,))
        return True
    except Exception as e:  # noqa: BLE001
        log.error("delete_session_async failed: %s", e)
        return False


async def update_session_memory_async(session_id: int, memory: dict) -> bool:
    try:
        await pg_execute_async(
            SQL_SESSION_UPDATE_MEMORY,
            (json.dumps(memory), datetime.now(), session_id),
        )
        return True
    except Exception as e:  # noqa: BLE001
        log.error("update_session_memory_async failed: %s", e)
        return False


async def get_session_memory_async(session_id: int) -> dict:
    rows = await pg_fetchall_async(SQL_SESSION_MEMORY_NOTES, (session_id,))
    return parse_session_memory_rows(rows)


async def increment_message_count_async(session_id: int) -> bool:
    try:
        await pg_execute_async(
            SQL_SESSION_INCREMENT_COUNT, (datetime.now(), session_id)
        )
        return True
    except Exception as e:  # noqa: BLE001
        log.error("increment_message_count_async failed: %s", e)
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
        existing = await pg_fetchone_async(
            SQL_APIKEY_SELECT_ID_BY_NAME, (key_name,)
        )
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
    session_id: int,
    role: str,
    content: str,
    image_paths: str | None = None,  # noqa: ARG001
) -> int | None:
    try:
        async with AsyncPgSession() as s:
            row = await s.execute_returning(
                SQL_MESSAGE_INSERT,
                (session_id, role, content, datetime.now()),
            )
            if row:
                await increment_message_count_async(session_id)
                return row.get("id")
        return None
    except Exception as e:  # noqa: BLE001
        log.error("add_message_async failed: %s", e)
        return None


async def get_session_messages_async(
    session_id: int, limit: int = 100
) -> list[dict]:
    rows = await pg_fetchall_async(
        SQL_MESSAGE_SELECT_ASC_LIMIT, (session_id, limit)
    )
    return [parse_message_row(r) for r in rows]


async def get_recent_messages_async(
    session_id: int, limit: int = 20
) -> list[dict]:
    return await get_session_messages_async(session_id, limit)


async def get_chat_history_async(
    session_id: int, limit: int | None = None, recent: bool = False
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
        rows = await pg_fetchall_async(
            SQL_MESSAGE_SELECT_ASC_ALL, (session_id,)
        )
    return [parse_message_row(r) for r in rows]


async def clear_session_messages_async(session_id: int) -> bool:
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


async def get_message_count_async(session_id: int) -> int:
    row = await pg_fetchone_async(
        SQL_MESSAGE_COUNT_CONVERSATIONAL, (session_id,)
    )
    return row.get("cnt", 0) if row else 0


async def add_session_event_async(
    session_id: int, content: str, interface: str = "terminal"
) -> int | None:
    return await add_message_async(
        session_id, "system", format_session_event(content, interface)
    )


async def get_recent_sessions_async(limit: int = 20) -> list[dict]:
    rows = await pg_fetchall_async(SQL_MESSAGE_RECENT_SYSTEM_GLOBAL, (limit,))
    return [parse_event_row(r) for r in rows]


async def get_recent_sessions_for_session_async(
    session_id: int, limit: int = 20
) -> list[dict]:
    rows = await pg_fetchall_async(
        SQL_MESSAGE_RECENT_SYSTEM_FOR_SESSION, (session_id, limit)
    )
    return [parse_event_row(r) for r in rows]


async def get_session_conversation_summary_async(
    session_id: int, limit: int = 20
) -> str:
    rows = await pg_fetchall_async(
        SQL_MESSAGE_CONVERSATION_SUMMARY, (session_id, limit)
    )
    return format_conversation_summary(rows)


async def add_image_tools_message_async(
    session_id: int, image_url: str
) -> int | None:
    return await add_message_async(session_id, "image_tools", image_url)


async def add_tool_result_async(
    session_id: int, tool_name: str, result_content: str
) -> int | None:
    return await add_message_async(
        session_id, tool_role_for(tool_name), result_content
    )


async def add_system_note_async(session_id: int, content: str) -> int | None:
    return await add_message_async(session_id, "system", content)


async def add_memory_note_async(session_id: int, content: str) -> int | None:
    return await add_system_note_async(session_id, content)


# ---------------------------------------------------------------------------
# AI history
# ---------------------------------------------------------------------------


async def get_chat_history_for_ai_async(
    session_id: int, limit: int | None = None, recent: bool = False
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
    return format_ai_history_rows(rows)


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
            row = await pg_fetchone_async(
                SQL_MESSAGE_SELECT_CONTENT_BY_ID, (msg_id,)
            )
            if row and row.get("content"):
                from app.encryption import encryptor
                plaintext = encryptor.decrypt(row["content"])
                await pg_execute_async(
                    SQL_MESSAGE_UPDATE_DECRYPTED, (plaintext, msg_id)
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
    "get_profile_async", "update_profile_async",
    "get_context_async", "update_context_async",
    "get_memory_async", "update_memory_async",
    # Sessions
    "get_active_session_async", "get_all_sessions_async",
    "create_session_async", "switch_session_async",
    "rename_session_async", "delete_session_async",
    "get_session_memory_async", "update_session_memory_async",
    "increment_message_count_async",
    # API keys
    "get_api_keys_async", "get_api_key_async",
    "add_api_key_async", "remove_api_key_async",
    # Messages
    "add_message_async", "get_session_messages_async",
    "get_recent_messages_async", "get_chat_history_async",
    "clear_session_messages_async", "get_message_count_async",
    "add_session_event_async", "get_recent_sessions_async",
    "get_recent_sessions_for_session_async",
    "get_session_conversation_summary_async",
    "add_image_tools_message_async", "add_tool_result_async",
    "add_system_note_async", "add_memory_note_async",
    # AI history
    "get_chat_history_for_ai_async",
    # Encryption
    "get_encryption_status_async", "get_all_encrypted_messages_async",
    "batch_decrypt_messages_async",
    # Tool roles (re-exported for backward-compat imports)
    "TOOL_ROLES", "ALL_TOOL_ROLES",
]
