# FILE: app/database/db_queries.py
# DESCRIPTION: Single source of truth for SQL strings, schema DDL, row
#              parsers, and shared constants used by both the sync and
#              async repository layers.
#
# Why this file exists:
#   The sync (db_pg_models.py) and async (db_pg_models_async.py) modules
#   used to duplicate every SQL string, every CREATE TABLE statement, and
#   every row-to-dict mapping. Any fix made to one had to be remembered in
#   the other - and over time, they drifted. Centralizing here makes the
#   sync/async wrappers thin (3-5 lines each) and removes the drift risk.
#
# Conventions:
#   * SQL constants are UPPER_SNAKE_CASE module-level strings.
#   * Row parsers are pure functions: dict-in, dict-out, no I/O.
#   * Encryption is intentionally re-exported here so both repo layers
#     import the helpers from a single location.

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Tool-role constants (used by the message layer to dispatch tool results)
# ---------------------------------------------------------------------------

TOOL_ROLES: dict[str, str] = {
    "image_generate": "image_tools",
    "imagine": "image_tools",
    "request": "request_tools",
    "read": "fs_tools",
    "write": "fs_tools",
    "ls": "fs_tools",
    "mkdir": "fs_tools",
    "rm": "fs_tools",
    "bash": "fs_tools",
}
ALL_TOOL_ROLES: list[str] = sorted(set(TOOL_ROLES.values()))


# ---------------------------------------------------------------------------
# Encryption helpers (sync, CPU-bound)
# ---------------------------------------------------------------------------


def encrypt_api_key(api_key: str) -> str:
    """Encrypt an API key with the project-wide encryptor."""
    from app.encryption import encryptor
    return encryptor.encrypt(api_key)


def decrypt_api_key(encrypted_key: str, is_encrypted: bool = True) -> str:
    """Decrypt an API key. Returns sentinel on failure."""
    if not is_encrypted:
        return encrypted_key
    from app.encryption import encryptor
    try:
        return encryptor.decrypt(encrypted_key)
    except Exception:  # noqa: BLE001 - any failure means "can't decrypt"
        return "[DECRYPTION_ERROR]"


DECRYPTION_ERROR = "[DECRYPTION_ERROR]"


# ---------------------------------------------------------------------------
# Schema DDL (executed by init_pg_tables / init_pg_tables_async)
# ---------------------------------------------------------------------------

SCHEMA_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS profiles (
        id SERIAL PRIMARY KEY,
        display_name VARCHAR(255) NOT NULL DEFAULT '',
        partner_name VARCHAR(255) NOT NULL DEFAULT '',
        affection INTEGER NOT NULL DEFAULT 50,
        theme VARCHAR(255) NOT NULL DEFAULT 'default',
        memory_state JSONB NOT NULL DEFAULT '{}',
        session_history JSONB NOT NULL DEFAULT '{}',
        global_knowledge JSONB NOT NULL DEFAULT '{}',
        providers_config JSONB NOT NULL DEFAULT '{}',
        context JSONB NOT NULL DEFAULT '{}',
        image_model VARCHAR(50) NOT NULL DEFAULT 'hunyuan',
        vision_model VARCHAR(100) NOT NULL DEFAULT 'moonshotai/kimi-k2.5',
        timestamp TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL DEFAULT 'New Chat',
        is_active BOOLEAN NOT NULL DEFAULT FALSE,
        message_count INTEGER NOT NULL DEFAULT 0,
        memory_state JSONB NOT NULL DEFAULT '{}',
        timestamp TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        deleted_at TIMESTAMP DEFAULT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS api_keys (
        id SERIAL PRIMARY KEY,
        key_name VARCHAR(255) NOT NULL DEFAULT 'openrouter',
        key_value TEXT NOT NULL,
        key_encrypted BOOLEAN NOT NULL DEFAULT TRUE,
        timestamp TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL,
        role VARCHAR(50) NOT NULL,
        content TEXT NOT NULL,
        content_encrypted BOOLEAN NOT NULL DEFAULT FALSE,
        image_paths TEXT NOT NULL DEFAULT '{}',
        timestamp TIMESTAMP DEFAULT NOW(),
        FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chat_sessions_active ON chat_sessions(is_active)",
    "CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated ON chat_sessions(updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_chat_sessions_deleted ON chat_sessions(deleted_at)",
    "CREATE INDEX IF NOT EXISTS idx_api_keys_name ON api_keys(key_name)",
    # Migration: Add deleted_at column if it doesn't exist (safe to run multiple times)
    "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL",
)


# ---------------------------------------------------------------------------
# Profile SQL
# ---------------------------------------------------------------------------

SQL_PROFILE_SELECT_FIRST = "SELECT * FROM profiles LIMIT 1"

SQL_PROFILE_INSERT_DEFAULT = """
INSERT INTO profiles (display_name, partner_name, affection, theme,
                      memory_state, session_history, global_knowledge,
                      providers_config, context, timestamp, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

DEFAULT_PROFILE_PARAMS = ("", "", 50, "default", "{}", "{}", "{}", "{}", "{}", datetime.now(), datetime.now())

_PROFILE_JSON_FIELDS = (
    "memory", "session_history", "global_knowledge", "providers_config", "context",
)
_PROFILE_TEXT_FIELDS = (
    "display_name", "partner_name", "theme", "image_model", "vision_model",
)


def build_profile_update(updates: dict[str, Any]) -> tuple[str, list[Any]] | None:
    """Build (query, params) for a UPDATE profiles statement.

    Returns None when there are no recognized fields to update. Always
    appends `updated_at` to the SET clause when at least one field changes.
    
    Note: All JSON fields are JSONB columns (no _json suffix).
    """
    set_parts: list[str] = []
    params: list[Any] = []

    for key, value in updates.items():
        if key in _PROFILE_JSON_FIELDS:
            # JSONB columns - no _json suffix
            col_name = "memory_state" if key == "memory" else key
            set_parts.append(f"{col_name} = %s")
            params.append(json.dumps(value) if isinstance(value, dict) else value)
        elif key in _PROFILE_TEXT_FIELDS:
            set_parts.append(f"{key} = %s")
            params.append(str(value))
        elif key == "affection":
            set_parts.append("affection = %s")
            params.append(int(value))

    if not set_parts:
        return None

    set_parts.append("updated_at = %s")
    params.append(datetime.now())
    return f"UPDATE profiles SET {', '.join(set_parts)}", params


def parse_profile_row(row: dict | None) -> dict:
    """Convert a raw profile row into the public dict shape.
    
    All JSON columns are JSONB, so they're already dict - no parse_json needed.
    """
    if not row:
        return {}
    return {
        "id": row.get("id"),
        "display_name": row.get("display_name", ""),
        "partner_name": row.get("partner_name", ""),
        "affection": row.get("affection", 50),
        "theme": row.get("theme", "default"),
        "memory": row.get("memory_state") or {},  # JSONB - already dict
        "session_history": row.get("session_history") or {},  # JSONB
        "global_knowledge": row.get("global_knowledge") or {},  # JSONB
        "providers_config": row.get("providers_config") or {},  # JSONB
        "context": row.get("context") or {},  # JSONB
        "image_model": row.get("image_model", "hunyuan"),
        "vision_model": row.get("vision_model", "moonshotai/kimi-k2.5"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# Chat session SQL
# ---------------------------------------------------------------------------

SQL_SESSION_SELECT_ACTIVE = \
    "SELECT * FROM chat_sessions WHERE is_active = TRUE AND deleted_at IS NULL LIMIT 1"

SQL_SESSION_INSERT = """
INSERT INTO chat_sessions (name, is_active, message_count, memory_state, created_at, updated_at)
VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
"""

SQL_SESSION_SELECT_ALL = \
    "SELECT * FROM chat_sessions WHERE deleted_at IS NULL ORDER BY updated_at DESC"

SQL_SESSION_DEACTIVATE_ALL = \
    "UPDATE chat_sessions SET is_active = FALSE WHERE deleted_at IS NULL"

SQL_SESSION_ACTIVATE_ONE = \
    "UPDATE chat_sessions SET is_active = TRUE, updated_at = %s WHERE id = %s AND deleted_at IS NULL"

SQL_SESSION_RENAME = \
    "UPDATE chat_sessions SET name = %s, updated_at = %s WHERE id = %s AND deleted_at IS NULL"

SQL_SESSION_DELETE = "UPDATE chat_sessions SET deleted_at = NOW() WHERE id = %s"

SQL_SESSION_UPDATE_MEMORY = \
    "UPDATE chat_sessions SET memory_state = %s, updated_at = %s WHERE id = %s"

SQL_SESSION_INCREMENT_COUNT = (
    "UPDATE chat_sessions SET message_count = message_count + 1, "
    "updated_at = %s WHERE id = %s"
)

SQL_SESSION_RESET_COUNT_AND_MEMORY = (
    "UPDATE chat_sessions SET message_count = 0, memory_state = '{}', "
    "updated_at = %s WHERE id = %s"
)


def parse_session_row(row: dict | None) -> dict:
    """Convert a raw chat_sessions row into the public dict shape.
    
    memory_state is JSONB, so it's already dict - no parse_json needed.
    """
    if not row:
        return {}
    return {
        "id": row.get("id"),
        "name": row.get("name", "New Chat"),
        "is_active": row.get("is_active", False),
        "message_count": row.get("message_count", 0),
        "memory": row.get("memory_state") or {},  # JSONB - already dict
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "timestamp": row.get("timestamp"),
    }


# ---------------------------------------------------------------------------
# Session memory (notes view)
# ---------------------------------------------------------------------------

SQL_SESSION_MEMORY_NOTES = """
SELECT content, role, timestamp
FROM messages
WHERE session_id = %s AND role IN ('system', 'memory')
ORDER BY timestamp DESC
LIMIT 50
"""


def parse_session_memory_rows(rows: list[dict]) -> dict:
    """Build the public session-memory shape from a list of note rows."""
    if not rows:
        return {}
    return {
        "notes": [
            {
                "content": r.get("content"),
                "role": r.get("role"),
                "timestamp": str(r.get("timestamp")),
            }
            for r in rows
        ],
        "count": len(rows),
    }


# ---------------------------------------------------------------------------
# API key SQL
# ---------------------------------------------------------------------------

SQL_APIKEY_SELECT_ALL = \
    "SELECT key_name, key_value, key_encrypted FROM api_keys"
SQL_APIKEY_SELECT_BY_NAME = \
    "SELECT key_name, key_value, key_encrypted FROM api_keys WHERE key_name = %s"
SQL_APIKEY_SELECT_ID_BY_NAME = \
    "SELECT id FROM api_keys WHERE key_name = %s"
SQL_APIKEY_UPDATE = \
    "UPDATE api_keys SET key_value = %s, key_encrypted = %s WHERE key_name = %s"
SQL_APIKEY_INSERT = (
    "INSERT INTO api_keys (key_name, key_value, key_encrypted, timestamp) "
    "VALUES (%s, %s, %s, %s)"
)
SQL_APIKEY_DELETE = "DELETE FROM api_keys WHERE key_name = %s"


def decrypt_api_key_rows(rows: list[dict]) -> dict[str, str]:
    """Convert raw api_keys rows into a {name: decrypted_value} mapping.

    Skips entries that fail to decrypt (returns DECRYPTION_ERROR sentinel).
    """
    out: dict[str, str] = {}
    for r in rows:
        name = r.get("key_name")
        if not name:
            continue
        value = r.get("key_value", "")
        encrypted = r.get("key_encrypted", True)
        if encrypted:
            decrypted = decrypt_api_key(value, True)
            if decrypted != DECRYPTION_ERROR:
                out[name] = decrypted
        else:
            out[name] = value
    return out


# ---------------------------------------------------------------------------
# Message SQL
# ---------------------------------------------------------------------------

SQL_MESSAGE_INSERT = """
INSERT INTO messages (session_id, role, content, timestamp, content_encrypted)
VALUES (%s, %s, %s, %s, FALSE) RETURNING id
"""

SQL_MESSAGE_SELECT_ASC_LIMIT = """
SELECT id, session_id, role, content, timestamp
FROM messages
WHERE session_id = %s
ORDER BY timestamp ASC
LIMIT %s
"""

SQL_MESSAGE_SELECT_DESC_LIMIT = """
SELECT id, session_id, role, content, timestamp
FROM messages
WHERE session_id = %s
ORDER BY timestamp DESC
LIMIT %s
"""

SQL_MESSAGE_SELECT_ASC_ALL = """
SELECT id, session_id, role, content, timestamp
FROM messages
WHERE session_id = %s
ORDER BY timestamp ASC
"""

SQL_MESSAGE_DELETE_FOR_SESSION = "DELETE FROM messages WHERE session_id = %s"

SQL_MESSAGE_COUNT_CONVERSATIONAL = (
    "SELECT COUNT(*) as cnt FROM messages "
    "WHERE session_id = %s AND role IN ('user', 'assistant')"
)

SQL_MESSAGE_RECENT_SYSTEM_GLOBAL = """
SELECT content, timestamp
FROM messages
WHERE role = 'system'
ORDER BY timestamp DESC
LIMIT %s
"""

SQL_MESSAGE_RECENT_SYSTEM_FOR_SESSION = """
SELECT content, timestamp
FROM messages
WHERE role = 'system' AND session_id = %s
ORDER BY timestamp DESC
LIMIT %s
"""

SQL_MESSAGE_CONVERSATION_SUMMARY = """
SELECT role, content
FROM messages
WHERE session_id = %s AND role IN ('user', 'assistant')
ORDER BY timestamp ASC
LIMIT %s
"""

SQL_MESSAGE_HISTORY_FOR_AI_ASC_LIMIT = """
SELECT id, role, content, timestamp
FROM messages
WHERE session_id = %s
ORDER BY timestamp ASC
LIMIT %s
"""

SQL_MESSAGE_HISTORY_FOR_AI_DESC_LIMIT = """
SELECT id, role, content, timestamp
FROM messages
WHERE session_id = %s
ORDER BY timestamp DESC
LIMIT %s
"""

SQL_MESSAGE_HISTORY_FOR_AI_ASC_ALL = """
SELECT id, role, content, timestamp
FROM messages
WHERE session_id = %s
ORDER BY timestamp ASC
"""

SQL_MESSAGE_SELECT_ENCRYPTED = """
SELECT id, session_id, role, content, timestamp
FROM messages
WHERE content_encrypted = TRUE
"""

SQL_MESSAGE_SELECT_CONTENT_BY_ID = \
    "SELECT content FROM messages WHERE id = %s"

SQL_MESSAGE_UPDATE_DECRYPTED = (
    "UPDATE messages SET content = %s, content_encrypted = FALSE WHERE id = %s"
)


def parse_message_row(row: dict) -> dict:
    """Convert a raw messages row into the public dict shape."""
    return {
        "id": row.get("id"),
        "session_id": row.get("session_id"),
        "role": row.get("role"),
        "content": row.get("content"),
        "timestamp": str(row.get("timestamp", "")),
    }


def parse_event_row(row: dict) -> dict:
    """Convert a raw event row (system messages list)."""
    return {
        "content": row.get("content", ""),
        "timestamp": str(row.get("timestamp", "")),
    }


def format_conversation_summary(rows: list[dict]) -> str:
    """Render a brief 'User: ... / AI: ...' summary from message rows."""
    lines: list[str] = []
    for r in rows:
        speaker = "User" if r.get("role") == "user" else "AI"
        content = r.get("content", "")
        if len(content) > 100:
            content = content[:100] + "..."
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# AI history formatting (tool-contract parsing for chat_history_for_ai)
# ---------------------------------------------------------------------------

_RX_BASH_COMMAND = re.compile(r'```bash\n\S+\$\s*(/[^\n]{1,500})\n```')
_RX_DETAILS_OPEN = re.compile(r'<details>\s*<summary>[^<]{0,500}</summary>', re.DOTALL)
_RX_DETAILS_CLOSE = re.compile(r'</details>', re.DOTALL)
_RX_BASH_BLOCK = re.compile(r'```bash\n[^`]{0,5000}\n```', re.DOTALL)
_RX_FENCE_OPEN = re.compile(r'```[\w]{0,20}\n?')
_RX_FENCE_CLOSE = re.compile(r'```')
_RX_BLOCKQUOTE = re.compile(r'^>\s*', re.MULTILINE)
_RX_HTML_TAGS = re.compile(r'<[^>]{1,500}>')
_RX_LEADING_NL = re.compile(r'^\n+')
_RX_TRAILING_NL = re.compile(r'\n+$')


def extract_command_from_markdown_contract(content: str) -> str:
    """Pull the /command line out of a tool-contract markdown blob."""
    if not content:
        return content
    m = _RX_BASH_COMMAND.search(content)
    return m.group(1).strip() if m else content


def extract_raw_result_from_markdown_contract(content: str) -> str:
    """Strip tool-contract formatting and return only the raw result text."""
    if not content:
        return content
    result = content
    result = _RX_DETAILS_OPEN.sub("", result)
    result = _RX_DETAILS_CLOSE.sub("", result)
    result = _RX_BASH_BLOCK.sub("", result)
    result = _RX_FENCE_OPEN.sub("", result)
    result = _RX_FENCE_CLOSE.sub("", result)
    result = _RX_BLOCKQUOTE.sub("", result)
    result = _RX_HTML_TAGS.sub("", result)
    result = _RX_LEADING_NL.sub("", result)
    result = _RX_TRAILING_NL.sub("", result)
    return result.strip()


def _format_user_timestamp(ts: Any) -> str:
    try:
        if isinstance(ts, str):
            dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
        else:
            dt = ts
        return dt.strftime("[%Y-%m-%d %H:%M:%S]")
    except Exception:  # noqa: BLE001
        return f"[{ts}]"


def format_ai_history_rows(rows: list[dict]) -> list[dict]:
    """Convert raw message rows into the AI-context message list.

    Behavior preserved exactly from the previous duplicated implementations:
      * 'event_log' rows are skipped.
      * 'user' rows get an appended formatted timestamp.
      * 'assistant' / 'system' rows pass through unchanged.
      * tool-role rows expand into TWO entries: an assistant /command
        line and a tool-role result entry.
    """
    formatted: list[dict] = []
    for msg in rows:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "event_log":
            continue

        if role == "user":
            ts = _format_user_timestamp(msg.get("timestamp", ""))
            formatted.append({"role": role, "content": f"{content} {ts}"})
        elif role in ("assistant", "system"):
            formatted.append({"role": role, "content": content})
        elif role in ALL_TOOL_ROLES:
            formatted.append({
                "role": "assistant",
                "content": extract_command_from_markdown_contract(content),
            })
            formatted.append({
                "role": role,
                "content": extract_raw_result_from_markdown_contract(content),
            })
    return formatted


# ---------------------------------------------------------------------------
# Encryption status SQL
# ---------------------------------------------------------------------------

SQL_ENC_TOTAL_MESSAGES = "SELECT COUNT(*) as cnt FROM messages"
SQL_ENC_ENCRYPTED_MESSAGES = \
    "SELECT COUNT(*) as cnt FROM messages WHERE content_encrypted = TRUE"
SQL_ENC_TOTAL_KEYS = "SELECT COUNT(*) as cnt FROM api_keys"
SQL_ENC_ENCRYPTED_KEYS = \
    "SELECT COUNT(*) as cnt FROM api_keys WHERE key_encrypted = TRUE"


def build_encryption_status(
    total_msg: dict | None,
    encrypted_msg: dict | None,
    total_keys: dict | None,
    encrypted_keys: dict | None,
) -> dict:
    """Assemble the encryption-status response from four count rows."""
    def cnt(row: dict | None) -> int:
        return row.get("cnt", 0) if row else 0

    return {
        "messages": {
            "total": cnt(total_msg),
            "encrypted": cnt(encrypted_msg),
            "policy": "NO_ENCRYPTION",
        },
        "api_keys": {
            "total": cnt(total_keys),
            "encrypted": cnt(encrypted_keys),
            "policy": "FULL_ENCRYPTION",
        },
    }


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


def parse_json(s: str | None) -> dict:
    """Safe JSON parse: returns {} on None / parse failure."""
    if not s:
        return {}
    if not isinstance(s, str):
        # Already-parsed dict shape; pass through.
        return s if isinstance(s, dict) else {}
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return {}


def tool_role_for(tool_name: str) -> str:
    """Return the canonical message-role for *tool_name*."""
    return TOOL_ROLES.get(tool_name, f"{tool_name}_tools")


def format_session_event(content: str, interface: str) -> str:
    """Render the canonical 'connection event' message body."""
    return f"*{content} on {interface}*"


__all__ = [
    # Tool roles
    "TOOL_ROLES", "ALL_TOOL_ROLES", "tool_role_for",
    # Encryption
    "encrypt_api_key", "decrypt_api_key", "DECRYPTION_ERROR",
    # Schema
    "SCHEMA_DDL",
    # Profile
    "SQL_PROFILE_SELECT_FIRST", "SQL_PROFILE_INSERT_DEFAULT",
    "DEFAULT_PROFILE_PARAMS",
    "build_profile_update", "parse_profile_row",
    # Sessions
    "SQL_SESSION_SELECT_ACTIVE", "SQL_SESSION_INSERT", "SQL_SESSION_SELECT_ALL",
    "SQL_SESSION_DEACTIVATE_ALL", "SQL_SESSION_ACTIVATE_ONE",
    "SQL_SESSION_RENAME", "SQL_SESSION_DELETE", "SQL_SESSION_UPDATE_MEMORY",
    "SQL_SESSION_INCREMENT_COUNT", "SQL_SESSION_RESET_COUNT_AND_MEMORY",
    "parse_session_row", "SQL_SESSION_MEMORY_NOTES", "parse_session_memory_rows",
    # API keys
    "SQL_APIKEY_SELECT_ALL", "SQL_APIKEY_SELECT_BY_NAME",
    "SQL_APIKEY_SELECT_ID_BY_NAME", "SQL_APIKEY_UPDATE",
    "SQL_APIKEY_INSERT", "SQL_APIKEY_DELETE", "decrypt_api_key_rows",
    # Messages
    "SQL_MESSAGE_INSERT", "SQL_MESSAGE_SELECT_ASC_LIMIT",
    "SQL_MESSAGE_SELECT_DESC_LIMIT", "SQL_MESSAGE_SELECT_ASC_ALL",
    "SQL_MESSAGE_DELETE_FOR_SESSION", "SQL_MESSAGE_COUNT_CONVERSATIONAL",
    "SQL_MESSAGE_RECENT_SYSTEM_GLOBAL", "SQL_MESSAGE_RECENT_SYSTEM_FOR_SESSION",
    "SQL_MESSAGE_CONVERSATION_SUMMARY", "SQL_MESSAGE_HISTORY_FOR_AI_ASC_LIMIT",
    "SQL_MESSAGE_HISTORY_FOR_AI_DESC_LIMIT", "SQL_MESSAGE_HISTORY_FOR_AI_ASC_ALL",
    "SQL_MESSAGE_SELECT_ENCRYPTED", "SQL_MESSAGE_SELECT_CONTENT_BY_ID",
    "SQL_MESSAGE_UPDATE_DECRYPTED",
    "parse_message_row", "parse_event_row", "format_conversation_summary",
    "format_ai_history_rows",
    # Tool-contract parsers
    "extract_command_from_markdown_contract",
    "extract_raw_result_from_markdown_contract",
    # Encryption status
    "SQL_ENC_TOTAL_MESSAGES", "SQL_ENC_ENCRYPTED_MESSAGES",
    "SQL_ENC_TOTAL_KEYS", "SQL_ENC_ENCRYPTED_KEYS",
    "build_encryption_status",
    # Misc
    "parse_json", "format_session_event",
]
