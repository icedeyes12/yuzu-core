# FILE: app.db.models.py
# DESCRIPTION: Sync PostgreSQL repository.
#
#   Each function is a thin wrapper that calls a SQL constant from
#   app.db.queries, runs it through app.db.connection, and passes
#   the result to a parser also defined in db_queries. The async mirror
#   lives in db_pg_models_async.py and uses the same constants and parsers.

from __future__ import annotations

from datetime import datetime

from app.db.connection import PgSession, pg_execute, pg_fetchall, pg_fetchone
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
    SQL_MESSAGE_INSERT,
    SQL_MESSAGE_RECENT_SYSTEM_FOR_SESSION,
    SQL_MESSAGE_RECENT_SYSTEM_GLOBAL,
    SQL_MESSAGE_SELECT_ASC_ALL,
    SQL_MESSAGE_SELECT_ASC_LIMIT,
    SQL_MESSAGE_SELECT_CONTENT_BY_ID,
    SQL_MESSAGE_SELECT_DESC_LIMIT,
    SQL_MESSAGE_SELECT_ENCRYPTED,
    SQL_MESSAGE_UPDATE,
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

# ALL_TOOL_ROLES re-exported here for backward compatibility with callers
# that imported it from app.db_pg_models.
__re_exports__ = (TOOL_ROLES, ALL_TOOL_ROLES)


# ---------------------------------------------------------------------------
# Schema initialization
# ---------------------------------------------------------------------------


def init_pg_tables() -> None:
    """Create PostgreSQL tables and indexes if missing."""
    with PgSession() as s:
        for ddl in SCHEMA_DDL:
            s.execute(ddl)
    log.info("PostgreSQL tables initialized")


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


def get_profile() -> dict:
    """Get the user profile. Creates a default row if none exists."""
    row = pg_fetchone(SQL_PROFILE_SELECT_FIRST)
    if not row:
        now = datetime.now()
        pg_execute(SQL_PROFILE_INSERT_DEFAULT, (*DEFAULT_PROFILE_PARAMS, now, now))
        row = pg_fetchone(SQL_PROFILE_SELECT_FIRST)
    return parse_profile_row(row)


def update_profile(updates: dict) -> bool:
    """Update the user profile with a partial set of fields."""
    if not updates:
        return False
    built = build_profile_update(updates)
    if built is None:
        return False
    query, params = built
    try:
        pg_execute(query, params)
        return True
    except Exception as e:  # noqa: BLE001
        log.error("update_profile failed: %s", e)
        return False


def get_context() -> dict:
    return get_profile().get("context", {})


def update_context(context_dict: dict) -> bool:
    return update_profile({"context": context_dict})


def get_memory() -> dict:
    return get_profile().get("memory", {})


def update_memory(memory_dict: dict) -> bool:
    return update_profile({"memory": memory_dict})


# ---------------------------------------------------------------------------
# Pipeline state (stored in memory_state)
# ---------------------------------------------------------------------------


def get_memory_state(session_id: str) -> dict:
    """Get pipeline state from session's memory_state.

    Returns dict with:
        - last_segmented_count: int
        - last_segmented_at: ISO timestamp
    """
    row = pg_fetchone(
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


def update_memory_state(session_id: str, state: dict) -> bool:
    """Update pipeline state in session's memory_state.

    Merges with existing state.
    """
    try:
        existing = get_memory_state(session_id)
        existing.update(state)
        pg_execute(
            "UPDATE chat_sessions SET memory_state = %s, updated_at = %s WHERE id = %s",
            (json.dumps(existing), datetime.now(), session_id),
        )
        return True
    except Exception as e:
        log.error("update_memory_state failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Chat sessions
# ---------------------------------------------------------------------------


def get_active_session() -> dict:
    """Get the currently active session. Creates one if none."""
    row = pg_fetchone(SQL_SESSION_SELECT_ACTIVE)
    if not row:
        now = datetime.now()
        user_id = get_profile()["id"]
        pg_execute(SQL_SESSION_INSERT, (user_id, "New Chat", True, 0, "{}", now, now))
        row = pg_fetchone(SQL_SESSION_SELECT_ACTIVE)
    return parse_session_row(row)


def get_all_sessions() -> list[dict]:
    return [parse_session_row(r) for r in pg_fetchall(SQL_SESSION_SELECT_ALL)]


def create_session(name: str = "New Chat", user_id: str | None = None) -> str | None:
    if user_id is None:
        user_id = get_profile()["id"]
    now = datetime.now()
    try:
        with PgSession() as s:
            row = s.execute_returning(
                SQL_SESSION_INSERT, (user_id, name, False, 0, "{}", now, now)
            )
            return row.get("id") if row else None
    except Exception as e:  # noqa: BLE001
        log.error("create_session failed: %s", e)
        return None


def switch_session(session_id: str) -> bool:
    try:
        with PgSession() as s:
            s.execute(SQL_SESSION_DEACTIVATE_ALL)
            s.execute(SQL_SESSION_ACTIVATE_ONE, (datetime.now(), session_id))
        return True
    except Exception as e:  # noqa: BLE001
        log.error("switch_session failed: %s", e)
        return False


def rename_session(session_id: str, new_name: str) -> bool:
    try:
        pg_execute(SQL_SESSION_RENAME, (new_name, datetime.now(), session_id))
        return True
    except Exception as e:  # noqa: BLE001
        log.error("rename_session failed: %s", e)
        return False


def delete_session(session_id: str) -> bool:
    try:
        with PgSession() as s:
            s.execute(SQL_SESSION_DELETE, (session_id,))
        return True
    except Exception as e:  # noqa: BLE001
        log.error("delete_session failed: %s", e)
        return False


def update_session_memory(session_id: str, memory: dict) -> bool:
    try:
        pg_execute(
            SQL_SESSION_UPDATE_MEMORY,
            (json.dumps(memory), datetime.now(), session_id),
        )
        return True
    except Exception as e:  # noqa: BLE001
        log.error("update_session_memory failed: %s", e)
        return False


def get_session_memory(session_id: str) -> dict:
    rows = pg_fetchall(SQL_SESSION_MEMORY_NOTES, (session_id,))
    return parse_session_memory_rows(rows)


def increment_message_count(session_id: str) -> bool:
    try:
        pg_execute(SQL_SESSION_INCREMENT_COUNT, (datetime.now(), session_id))
        return True
    except Exception as e:  # noqa: BLE001
        log.error("increment_message_count failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------


def get_api_keys(key_name: str | None = None) -> dict[str, str]:
    if key_name:
        rows = pg_fetchall(SQL_APIKEY_SELECT_BY_NAME, (key_name,))
    else:
        rows = pg_fetchall(SQL_APIKEY_SELECT_ALL)
    return decrypt_api_key_rows(rows)


def get_api_key(key_name: str) -> str | None:
    return get_api_keys(key_name).get(key_name)


def add_api_key(key_name: str, key_value: str) -> bool:
    encrypted = encrypt_api_key(key_value)
    is_encrypted = encrypted != key_value
    try:
        if pg_fetchone(SQL_APIKEY_SELECT_ID_BY_NAME, (key_name,)):
            pg_execute(SQL_APIKEY_UPDATE, (encrypted, is_encrypted, key_name))
        else:
            pg_execute(
                SQL_APIKEY_INSERT,
                (key_name, encrypted, is_encrypted, datetime.now()),
            )
        return True
    except Exception as e:  # noqa: BLE001
        log.error("add_api_key failed: %s", e)
        return False


def remove_api_key(key_name: str) -> bool:
    try:
        pg_execute(SQL_APIKEY_DELETE, (key_name,))
        return True
    except Exception as e:  # noqa: BLE001
        log.error("remove_api_key failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def add_message(
    session_id: str,
    role: str,
    content: str,
    image_paths: list[str] | None = None,
    user_id: str | None = None,
) -> int | None:
    """Insert a message row, bump the session's message_count, return id.

    Timestamp is set by database NOW() to ensure ordering coherence.
    """
    if user_id is None:
        user_id = get_profile()["id"]
    try:
        paths_json = json.dumps(image_paths or [])
        with PgSession() as s:
            row = s.execute_returning(
                SQL_MESSAGE_INSERT,
                (session_id, user_id, role, content, paths_json),  # timestamp handled by DB
            )
            if row:
                increment_message_count(session_id)
                return row.get("id")
        return None
    except Exception as e:
        log.error("add_message failed: %s", e)
        return None


def update_message(
    message_id: int, content: str, image_paths: list[str] | None = None
) -> bool:
    """Update the content and optional image paths of an existing message."""
    try:
        paths_json = json.dumps(image_paths or [])
        pg_execute(SQL_MESSAGE_UPDATE, (content, paths_json, message_id))
        return True
    except Exception as e:
        log.error("update_message failed: %s", e)
        return False


def get_session_messages(
    session_id: str, limit: int = 100, order: str = "ASC"
) -> list[dict]:
    """Fetch messages by session_id.

    order: "ASC" (oldest first) or "DESC" (newest first).
    """
    if order.upper() == "DESC":
        rows = pg_fetchall(SQL_MESSAGE_SELECT_DESC_LIMIT, (session_id, limit))
    else:
        rows = pg_fetchall(SQL_MESSAGE_SELECT_ASC_LIMIT, (session_id, limit))
    return [parse_message_row(r) for r in rows]


def get_recent_messages(session_id: str, limit: int = 20) -> list[dict]:
    """Alias kept for backward compatibility with older callers."""
    return get_session_messages(session_id, limit)


def get_chat_history(
    session_id: str, limit: int | None = None, recent: bool = False
) -> list[dict]:
    """Get messages ordered by timestamp.

    When `recent=True`, fetch the latest *limit* rows (DESC) and reverse so
    the caller still sees them in chronological order.
    """
    if limit and recent:
        rows = pg_fetchall(SQL_MESSAGE_SELECT_DESC_LIMIT, (session_id, limit))
        rows = list(reversed(rows))
    elif limit:
        rows = pg_fetchall(SQL_MESSAGE_SELECT_ASC_LIMIT, (session_id, limit))
    else:
        rows = pg_fetchall(SQL_MESSAGE_SELECT_ASC_ALL, (session_id,))
    return [parse_message_row(r) for r in rows]


def clear_session_messages(session_id: str) -> bool:
    try:
        pg_execute(SQL_MESSAGE_DELETE_FOR_SESSION, (session_id,))
        pg_execute(
            SQL_SESSION_RESET_COUNT_AND_MEMORY,
            (datetime.now(), session_id),
        )
        return True
    except Exception as e:  # noqa: BLE001
        log.error("clear_session_messages failed: %s", e)
        return False


def get_message_count(session_id: str) -> int:
    row = pg_fetchone(SQL_MESSAGE_COUNT_CONVERSATIONAL, (session_id,))
    return row.get("cnt", 0) if row else 0


def add_session_event(
    session_id: str, content: str, interface: str = "terminal"
) -> int | None:
    return add_message(session_id, "system", format_session_event(content, interface))


def get_recent_sessions(limit: int = 20) -> list[dict]:
    rows = pg_fetchall(SQL_MESSAGE_RECENT_SYSTEM_GLOBAL, (limit,))
    return [parse_event_row(r) for r in rows]


def get_recent_sessions_for_session(session_id: str, limit: int = 20) -> list[dict]:
    rows = pg_fetchall(SQL_MESSAGE_RECENT_SYSTEM_FOR_SESSION, (session_id, limit))
    return [parse_event_row(r) for r in rows]


def get_session_conversation_summary(session_id: str, limit: int = 20) -> str:
    rows = pg_fetchall(SQL_MESSAGE_CONVERSATION_SUMMARY, (session_id, limit))
    return format_conversation_summary(rows)


def add_tool_result(session_id: str, tool_name: str, result_content: str) -> int | None:
    return add_message(session_id, tool_role_for(tool_name), result_content)


def add_system_note(session_id: str, content: str) -> int | None:
    return add_message(session_id, "system", content)


def add_memory_note(session_id: str, content: str) -> int | None:
    """Alias for add_system_note."""
    return add_system_note(session_id, content)


# ---------------------------------------------------------------------------
# AI history (with tool-contract expansion)
# ---------------------------------------------------------------------------


def get_chat_history_for_ai(
    session_id: str,
    limit: int | None = None,
    recent: bool = False,
    include_image_paths: bool = False,
) -> list[dict]:
    """Fetch history and format specifically for LLM context (e.g. system turn)."""
    rows = get_chat_history(session_id, limit, recent)
    return format_ai_history_rows(rows, include_image_paths=include_image_paths)


# ---------------------------------------------------------------------------
# Encryption status / migration helpers
# ---------------------------------------------------------------------------


def get_encryption_status() -> dict:
    return build_encryption_status(
        pg_fetchone(SQL_ENC_TOTAL_MESSAGES),
        pg_fetchone(SQL_ENC_ENCRYPTED_MESSAGES),
        pg_fetchone(SQL_ENC_TOTAL_KEYS),
        pg_fetchone(SQL_ENC_ENCRYPTED_KEYS),
    )


def get_all_encrypted_messages() -> list[dict]:
    rows = pg_fetchall(SQL_MESSAGE_SELECT_ENCRYPTED)
    return [parse_message_row(r) for r in rows]


def batch_decrypt_messages(message_ids: list[int]) -> dict:
    """Decrypt and rewrite a batch of messages. Returns a counts dict."""
    decrypted_count = 0
    failed_count = 0
    for msg_id in message_ids:
        try:
            row = pg_fetchone(SQL_MESSAGE_SELECT_CONTENT_BY_ID, (msg_id,))
            if row and row.get("content"):
                from app.encryption import encryptor

                plaintext = encryptor.decrypt(row["content"])
                pg_execute(SQL_MESSAGE_UPDATE_DECRYPTED, (plaintext, msg_id))
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
    "init_pg_tables",
    # Profile
    "get_profile",
    "update_profile",
    "get_context",
    "update_context",
    "get_memory",
    "update_memory",
    # Sessions
    "get_active_session",
    "get_all_sessions",
    "create_session",
    "switch_session",
    "rename_session",
    "delete_session",
    "get_session_memory",
    "update_session_memory",
    "increment_message_count",
    # Pipeline state
    "get_memory_state",
    "update_memory_state",
    # API keys
    "get_api_keys",
    "get_api_key",
    "add_api_key",
    "remove_api_key",
    # Messages
    "add_message",
    "update_message",
    "get_session_messages",
    "get_recent_messages",
    "get_chat_history",
    "clear_session_messages",
    "get_message_count",
    "add_session_event",
    "get_recent_sessions",
    "get_recent_sessions_for_session",
    "get_session_conversation_summary",
    "add_tool_result",
    "add_system_note",
    "add_memory_note",
    # AI history
    "get_chat_history_for_ai",
    # Encryption
    "get_encryption_status",
    "get_all_encrypted_messages",
    "batch_decrypt_messages",
    # Tool roles (re-exported for backward-compat imports)
    "TOOL_ROLES",
    "ALL_TOOL_ROLES",
]
