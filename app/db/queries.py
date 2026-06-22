# FILE: app.db.queries.py
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
    # Image generation
    "image_generate": "image_tools",
    "imagine": "image_tools",
    # HTTP requests
    "http_request": "request_tools",
    "request": "request_tools",
    # Memory tools
    "memory_store": "memory_tools",
    "memory_search": "memory_tools",
    # File system tools
    "read": "fs_tools",
    "write": "fs_tools",
    "ls": "fs_tools",
    "mkdir": "fs_tools",
    "rm": "fs_tools",
    # Shell execution
    "bash": "shell_tools",
    # Python execution
    "python": "python_tools",
    # SQL queries
    "sql": "sql_tools",
    "ask_rei": "ask_rei_tools",
    "fs_tools": "fs_tools",
    "image_tools": "image_tools",
    "request_tools": "request_tools",
    "python_tools": "python_tools",
    "shell_tools": "shell_tools",
    "sql_tools": "sql_tools",
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
#
# Post-Phase-1 multi-tenant schema.  profiles and chat_sessions use UUIDv7
# primary keys (time-ordered, sortable).  All tenant-scoped tables carry a
# user_id FK → profiles(id) ON DELETE CASCADE.  messages.id and
# semantic_facts.id remain SERIAL integer (not changed in the cutover).
#
# Legacy migration columns (legacy_int_id, legacy_session_id, memory_json)
# are NOT included — they are migration artifacts only and must not exist
# on fresh installs.
# ---------------------------------------------------------------------------

SCHEMA_DDL: tuple[str, ...] = (
    # ── Extensions ──
    "CREATE EXTENSION IF NOT EXISTS pgcrypto",
    "CREATE EXTENSION IF NOT EXISTS vector",
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    # ── UUIDv7 generator (time-ordered, lexicographically sortable) ──
    """
    CREATE OR REPLACE FUNCTION generate_uuidv7()
    RETURNS UUID AS $function$
    DECLARE
      unix_ts_ms BIGINT;
      rand_hex TEXT;
    BEGIN
      unix_ts_ms := (EXTRACT(EPOCH FROM clock_timestamp()) * 1000)::BIGINT;
      rand_hex := replace(gen_random_uuid()::text, '-', '');
      RETURN (
        lpad(to_hex(unix_ts_ms), 12, '0')
        || '7'
        || substring(rand_hex, 14, 3)
        || substring(rand_hex, 17, 4)
        || substring(rand_hex, 21, 12)
      )::UUID;
    END;
    $function$ LANGUAGE plpgsql VOLATILE
    """,
    # ── profiles (tenant root — PK is UUID, referenced by all user_id FKs) ──
    """
    CREATE TABLE IF NOT EXISTS profiles (
        id UUID NOT NULL DEFAULT generate_uuidv7() PRIMARY KEY,
        display_name VARCHAR(255) NOT NULL DEFAULT '',
        partner_name VARCHAR(255) NOT NULL DEFAULT '',
        affection INTEGER NOT NULL DEFAULT 50,
        theme VARCHAR(255) NOT NULL DEFAULT 'default',
        memory_state JSONB NOT NULL DEFAULT '{}',
        session_history JSONB NOT NULL DEFAULT '{}',
        global_knowledge JSONB NOT NULL DEFAULT '{}',
        providers_config JSONB NOT NULL DEFAULT '{}',
        context JSONB NOT NULL DEFAULT '{}',
        image_model TEXT NOT NULL DEFAULT 'hunyuan',
        vision_model TEXT NOT NULL DEFAULT 'moonshotai/kimi-k2.5',
        location_lat REAL,
        location_lon REAL,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        timestamp TIMESTAMP DEFAULT NOW()
    )
    """,
    # ── chat_sessions (PK UUID, tenant FK user_id → profiles) ──
    """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id UUID NOT NULL DEFAULT generate_uuidv7() PRIMARY KEY,
        user_id UUID NOT NULL,
        name VARCHAR(255) NOT NULL DEFAULT 'New Chat',
        is_active BOOLEAN NOT NULL DEFAULT FALSE,
        message_count INTEGER NOT NULL DEFAULT 0,
        memory_state JSONB DEFAULT '{}',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        deleted_at TIMESTAMP DEFAULT NULL,
        timestamp TIMESTAMP DEFAULT NOW(),
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    )
    """,
    # ── api_keys (not multi-tenant — stays SERIAL integer PK) ──
    """
    CREATE TABLE IF NOT EXISTS api_keys (
        id SERIAL PRIMARY KEY,
        key_name VARCHAR(255) NOT NULL DEFAULT 'openrouter',
        key_value TEXT NOT NULL,
        key_encrypted BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    # ── messages (id stays SERIAL int; session_id + user_id are UUID FKs) ──
    """
    CREATE TABLE IF NOT EXISTS messages (
        id SERIAL PRIMARY KEY,
        session_id UUID,
        user_id UUID NOT NULL,
        role VARCHAR(50) NOT NULL,
        content TEXT NOT NULL,
        content_encrypted BOOLEAN NOT NULL DEFAULT FALSE,
        image_paths TEXT DEFAULT '[]',
        tool_calls JSONB,
        tool_call_id VARCHAR,
        timestamp VARCHAR NOT NULL,
        FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    )
    """,
    # ── semantic_facts (id stays SERIAL int; user_id UUID FK; embedding vector(4096)) ──
    """
    CREATE TABLE IF NOT EXISTS semantic_facts (
        id SERIAL PRIMARY KEY,
        user_id UUID NOT NULL,
        fact_type VARCHAR NOT NULL,
        content TEXT NOT NULL,
        metadata JSONB,
        embedding vector(4096),
        tsv tsvector,
        pending_review BOOLEAN DEFAULT FALSE,
        invalid_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    )
    """,
    # ── user_identities (OAuth provider linkage — Google sub / GitHub id) ──
    """
    CREATE TABLE IF NOT EXISTS user_identities (
        id UUID NOT NULL DEFAULT generate_uuidv7() PRIMARY KEY,
        user_id UUID NOT NULL,
        provider VARCHAR(32) NOT NULL,
        provider_sub TEXT NOT NULL,
        email TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        UNIQUE (provider, provider_sub),
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    )
    """,
    # ── user_sessions (opaque server-side session tokens — revocable, not JWT) ──
    """
    CREATE TABLE IF NOT EXISTS user_sessions (
        token TEXT PRIMARY KEY,
        user_id UUID NOT NULL,
        created_at TIMESTAMP DEFAULT NOW(),
        expires_at TIMESTAMP NOT NULL,
        revoked_at TIMESTAMP DEFAULT NULL,
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    )
    """,
    # ── Indexes ──
    "CREATE INDEX IF NOT EXISTS idx_chat_sessions_active ON chat_sessions(is_active)",
    "CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated ON chat_sessions(updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_chat_sessions_deleted ON chat_sessions(deleted_at)",
    "CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON chat_sessions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_api_keys_name ON api_keys(key_name)",
    "CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_session_user ON messages(session_id, user_id)",
    "CREATE INDEX IF NOT EXISTS idx_semantic_facts_user_id ON semantic_facts(user_id)",
    "CREATE INDEX IF NOT EXISTS semantic_facts_content_idx ON semantic_facts USING gin (content gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS semantic_facts_tsv_idx ON semantic_facts USING gin (tsv)",
    "CREATE INDEX IF NOT EXISTS semantic_facts_pending_review_idx ON semantic_facts(pending_review) WHERE pending_review = TRUE",
    "CREATE INDEX IF NOT EXISTS idx_user_identities_user_id ON user_identities(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_user_sessions_expires ON user_sessions(expires_at)",
    # ── Migrations for existing DBs (idempotent) ──
    # Phase 1.3: add user_id to tenant-scoped tables (already done via migration SQL)
    # Phase 1.7: drop NOT NULL on legacy mapping columns so new UUID rows can omit them
    # Wrapped in DO blocks because legacy_* columns don't exist on fresh installs
    """
    DO $$ BEGIN
      ALTER TABLE chat_sessions ALTER COLUMN legacy_int_id DROP NOT NULL;
    EXCEPTION WHEN undefined_column THEN NULL;
    END $$;
    """,
    """
    DO $$ BEGIN
      ALTER TABLE messages ALTER COLUMN legacy_session_id DROP NOT NULL;
    EXCEPTION WHEN undefined_column THEN NULL;
    END $$;
    """,
    """
    DO $$ BEGIN
      ALTER TABLE profiles ALTER COLUMN legacy_int_id DROP NOT NULL;
    EXCEPTION WHEN undefined_column THEN NULL;
    END $$;
    """,
)


# ---------------------------------------------------------------------------
# Profile SQL
# ---------------------------------------------------------------------------

SQL_PROFILE_SELECT_FIRST = "SELECT * FROM profiles LIMIT 1"

# ── Multi-tenant scoped variants (Phase 2.3+2.4) ──
SQL_PROFILE_SELECT_BY_ID = "SELECT * FROM profiles WHERE id = %s"

SQL_PROFILE_INSERT_DEFAULT = """
INSERT INTO profiles (display_name, partner_name, affection, theme,
                      memory_state, session_history, global_knowledge,
                      providers_config, context, timestamp, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

DEFAULT_PROFILE_PARAMS = (
    "",
    "",
    50,
    "default",
    "{}",
    "{}",
    "{}",
    "{}",
    "{}",
)

_PROFILE_JSON_FIELDS = (
    "memory",
    "session_history",
    "global_knowledge",
    "providers_config",
    "context",
)
_PROFILE_TEXT_FIELDS = (
    "display_name",
    "partner_name",
    "theme",
    "image_model",
    "vision_model",
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
        "image_model": row.get("image_model", "qwen_image"),
        "vision_model": row.get("vision_model", "moonshotai/kimi-k2.5"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# Chat session SQL
# ---------------------------------------------------------------------------

SQL_SESSION_SELECT_ACTIVE = (
    "SELECT * FROM chat_sessions WHERE is_active = TRUE AND deleted_at IS NULL LIMIT 1"
)

SQL_SESSION_SELECT_ACTIVE_FOR_USER = "SELECT * FROM chat_sessions WHERE user_id = %s AND is_active = TRUE AND deleted_at IS NULL LIMIT 1"

SQL_SESSION_INSERT = """
INSERT INTO chat_sessions (user_id, name, is_active, message_count, memory_state, created_at, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
"""

SQL_SESSION_SELECT_ALL = (
    "SELECT * FROM chat_sessions WHERE deleted_at IS NULL ORDER BY updated_at DESC"
)

SQL_SESSION_SELECT_ALL_FOR_USER = "SELECT * FROM chat_sessions WHERE user_id = %s AND deleted_at IS NULL ORDER BY updated_at DESC"

SQL_SESSION_DEACTIVATE_ALL = (
    "UPDATE chat_sessions SET is_active = FALSE WHERE deleted_at IS NULL"
)

SQL_SESSION_DEACTIVATE_FOR_USER = "UPDATE chat_sessions SET is_active = FALSE WHERE user_id = %s AND deleted_at IS NULL"

SQL_SESSION_ACTIVATE_ONE = "UPDATE chat_sessions SET is_active = TRUE, updated_at = %s WHERE id = %s AND deleted_at IS NULL"

SQL_SESSION_ACTIVATE_ONE_SCOPED = "UPDATE chat_sessions SET is_active = TRUE, updated_at = %s WHERE id = %s AND user_id = %s AND deleted_at IS NULL"

SQL_SESSION_RENAME = "UPDATE chat_sessions SET name = %s, updated_at = %s WHERE id = %s AND deleted_at IS NULL"

SQL_SESSION_RENAME_SCOPED = "UPDATE chat_sessions SET name = %s, updated_at = %s WHERE id = %s AND user_id = %s AND deleted_at IS NULL"

SQL_SESSION_DELETE = "UPDATE chat_sessions SET deleted_at = NOW() WHERE id = %s"

SQL_SESSION_DELETE_SCOPED = (
    "UPDATE chat_sessions SET deleted_at = NOW() WHERE id = %s AND user_id = %s"
)

SQL_SESSION_OWNERSHIP_CHECK = (
    "SELECT user_id FROM chat_sessions WHERE id = %s AND deleted_at IS NULL"
)

SQL_SESSIONS_RECENT_ACTIVE = """
SELECT id, name, updated_at, message_count, is_active
FROM chat_sessions
WHERE deleted_at IS NULL AND id != %s
ORDER BY updated_at DESC
LIMIT %s
"""

SQL_SESSION_UPDATE_MEMORY = (
    "UPDATE chat_sessions SET memory_state = %s, updated_at = %s WHERE id = %s"
)

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

SQL_APIKEY_SELECT_ALL = "SELECT key_name, key_value, key_encrypted FROM api_keys"
SQL_APIKEY_SELECT_BY_NAME = (
    "SELECT key_name, key_value, key_encrypted FROM api_keys WHERE key_name = %s"
)
SQL_APIKEY_SELECT_ID_BY_NAME = "SELECT id FROM api_keys WHERE key_name = %s"
SQL_APIKEY_UPDATE = (
    "UPDATE api_keys SET key_value = %s, key_encrypted = %s WHERE key_name = %s"
)
SQL_APIKEY_INSERT = (
    "INSERT INTO api_keys (key_name, key_value, key_encrypted, created_at) "
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
INSERT INTO messages (session_id, user_id, role, content, image_paths, timestamp, content_encrypted)
VALUES (%s, %s, %s, %s, %s, NOW(), FALSE) RETURNING id, timestamp
"""

SQL_MESSAGE_SELECT_ASC_LIMIT = """
SELECT id, session_id, role, content, image_paths, timestamp
FROM messages
WHERE session_id = %s
ORDER BY timestamp ASC
LIMIT %s
"""

SQL_MESSAGE_SELECT_DESC_LIMIT = """
SELECT id, session_id, role, content, image_paths, timestamp
FROM messages
WHERE session_id = %s
ORDER BY timestamp DESC
LIMIT %s
"""

SQL_MESSAGE_SELECT_ASC_ALL = """
SELECT id, session_id, role, content, image_paths, timestamp
FROM messages
WHERE session_id = %s
ORDER BY timestamp ASC
"""

# Query messages after a specific ID (for memory pipeline ID-based tracking)
SQL_MESSAGE_SELECT_AFTER_ID = """
SELECT id, session_id, role, content, image_paths, timestamp
FROM messages
WHERE session_id = %s AND id > %s
ORDER BY id ASC
LIMIT %s
"""

SQL_MESSAGE_UPDATE = "UPDATE messages SET content = %s, image_paths = %s WHERE id = %s"

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
SELECT id, role, content, image_paths, timestamp
FROM messages
WHERE session_id = %s AND role IN ('user', 'assistant')
ORDER BY timestamp ASC
LIMIT %s
"""

SQL_MESSAGE_HISTORY_FOR_AI_DESC_LIMIT = """
SELECT id, role, content, image_paths, timestamp
FROM messages
WHERE session_id = %s AND role IN ('user', 'assistant')
ORDER BY timestamp DESC
LIMIT %s
"""

SQL_MESSAGE_HISTORY_FOR_AI_ASC_ALL = """
SELECT id, role, content, image_paths, timestamp
FROM messages
WHERE session_id = %s AND role IN ('user', 'assistant')
ORDER BY timestamp ASC
"""

SQL_MESSAGE_SELECT_ENCRYPTED = """
SELECT id, session_id, role, content, timestamp
FROM messages
WHERE content_encrypted = TRUE
"""

SQL_MESSAGE_SELECT_CONTENT_BY_ID = "SELECT content FROM messages WHERE id = %s"

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
        "image_paths": parse_json(row.get("image_paths", "[]")),
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

_RX_BASH_COMMAND = re.compile(r"```bash\n\S+\$\s*(/[^\n]{1,500})\n```")
_RX_DETAILS_OPEN = re.compile(r"<details>\s*<summary>[^<]{0,500}</summary>", re.DOTALL)
_RX_DETAILS_CLOSE = re.compile(r"</details>", re.DOTALL)
_RX_BASH_BLOCK = re.compile(r"```bash\n[^`]{0,5000}\n```", re.DOTALL)
_RX_FENCE_OPEN = re.compile(r"```[\w]{0,20}\n?")
_RX_FENCE_CLOSE = re.compile(r"```")
_RX_BLOCKQUOTE = re.compile(r"^>\s*", re.MULTILINE)
_RX_HTML_TAGS = re.compile(r"<[^>]{1,500}>")
_RX_LEADING_NL = re.compile(r"^\n+")
_RX_TRAILING_NL = re.compile(r"\n+$")


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


def format_ai_history_rows(
    rows: list[dict], include_image_paths: bool = False
) -> list[dict]:
    """Format message rows for AI consumption.

    Filters out system messages to prevent log/context pollution.
    """
    if not rows:
        return []

    # Defensive filter: exclude system messages
    filtered_rows = [r for r in rows if r.get("role") != "system"]

    if not filtered_rows:
        return []

    formatted: list[dict] = []
    for msg in filtered_rows:
        role = msg.get("role", "")
        content = msg.get("content", "")
        image_paths = parse_json(msg.get("image_paths", "[]"))

        if role == "event_log":
            continue

        if role == "user":
            ts = _format_user_timestamp(msg.get("timestamp", ""))
            entry = {
                "role": role,
                "content": f"{content} {ts}",
            }
        elif role in ("assistant", "system"):
            entry = {"role": role, "content": content}
        elif role in ALL_TOOL_ROLES:
            # Strip tool-contract markdown and keep only the raw result
            # so the AI can actually read the tool output.
            raw = extract_raw_result_from_markdown_contract(content)
            entry = {"role": role, "content": raw}
        else:
            entry = {"role": role, "content": content}

        if include_image_paths and image_paths:
            entry["image_paths"] = image_paths

        formatted.append(entry)
    return formatted


# ---------------------------------------------------------------------------
# Encryption status SQL
# ---------------------------------------------------------------------------

SQL_ENC_TOTAL_MESSAGES = "SELECT COUNT(*) as cnt FROM messages"
SQL_ENC_ENCRYPTED_MESSAGES = (
    "SELECT COUNT(*) as cnt FROM messages WHERE content_encrypted = TRUE"
)
SQL_ENC_TOTAL_KEYS = "SELECT COUNT(*) as cnt FROM api_keys"
SQL_ENC_ENCRYPTED_KEYS = (
    "SELECT COUNT(*) as cnt FROM api_keys WHERE key_encrypted = TRUE"
)


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
# Auth — identity mapping + server-side sessions (Phase 2)
# ---------------------------------------------------------------------------

SQL_IDENTITY_LOOKUP = """
SELECT user_id FROM user_identities
WHERE provider = %s AND provider_sub = %s
"""

SQL_IDENTITY_COUNT = "SELECT count(*) AS count FROM user_identities"

SQL_IDENTITY_INSERT = """
INSERT INTO user_identities (user_id, provider, provider_sub, email)
VALUES (%s, %s, %s, %s)
"""

SQL_PROFILE_INSERT_DEFAULT_RETURNING = """
INSERT INTO profiles (display_name, partner_name, affection, theme,
                      memory_state, session_history, global_knowledge,
                      providers_config, context, timestamp, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
RETURNING id
"""

SQL_SESSION_TOKEN_CREATE = """
INSERT INTO user_sessions (token, user_id, created_at, expires_at)
VALUES (%s, %s, %s, %s)
"""

SQL_SESSION_TOKEN_VALIDATE = """
SELECT user_id FROM user_sessions
WHERE token = %s
  AND expires_at > NOW()
  AND revoked_at IS NULL
"""

SQL_SESSION_TOKEN_REVOKE = """
UPDATE user_sessions SET revoked_at = %s WHERE token = %s
"""

# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


def parse_json(s: str | None) -> Any:
    """Safe JSON parse: returns {} on None / parse failure."""
    if not s:
        return {}
    if not isinstance(s, str):
        # Already-parsed shape; pass through.
        return s
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
    "TOOL_ROLES",
    "ALL_TOOL_ROLES",
    "tool_role_for",
    # Encryption
    "encrypt_api_key",
    "decrypt_api_key",
    "DECRYPTION_ERROR",
    # Schema
    "SCHEMA_DDL",
    # Profile
    "SQL_PROFILE_SELECT_FIRST",
    "SQL_PROFILE_SELECT_BY_ID",
    "SQL_SESSION_SELECT_ACTIVE_FOR_USER",
    "SQL_SESSION_SELECT_ALL_FOR_USER",
    "SQL_SESSION_DEACTIVATE_FOR_USER",
    "SQL_SESSION_ACTIVATE_ONE_SCOPED",
    "SQL_SESSION_RENAME_SCOPED",
    "SQL_SESSION_DELETE_SCOPED",
    "SQL_SESSION_OWNERSHIP_CHECK",
    "SQL_PROFILE_INSERT_DEFAULT",
    "DEFAULT_PROFILE_PARAMS",
    "build_profile_update",
    "parse_profile_row",
    # Sessions
    "SQL_SESSION_SELECT_ACTIVE",
    "SQL_SESSION_INSERT",
    "SQL_SESSIONS_RECENT_ACTIVE",
    "SQL_SESSION_SELECT_ALL",
    "SQL_SESSION_DEACTIVATE_ALL",
    "SQL_SESSION_ACTIVATE_ONE",
    "SQL_SESSION_RENAME",
    "SQL_SESSION_DELETE",
    "SQL_SESSION_UPDATE_MEMORY",
    "SQL_SESSION_INCREMENT_COUNT",
    "SQL_SESSION_RESET_COUNT_AND_MEMORY",
    "parse_session_row",
    "SQL_SESSION_MEMORY_NOTES",
    "parse_session_memory_rows",
    # API keys
    "SQL_APIKEY_SELECT_ALL",
    "SQL_APIKEY_SELECT_BY_NAME",
    "SQL_APIKEY_SELECT_ID_BY_NAME",
    "SQL_APIKEY_UPDATE",
    "SQL_APIKEY_INSERT",
    "SQL_APIKEY_DELETE",
    "decrypt_api_key_rows",
    # Messages
    "SQL_MESSAGE_INSERT",
    "SQL_MESSAGE_SELECT_ASC_LIMIT",
    "SQL_MESSAGE_SELECT_DESC_LIMIT",
    "SQL_MESSAGE_SELECT_ASC_ALL",
    "SQL_MESSAGE_DELETE_FOR_SESSION",
    "SQL_MESSAGE_COUNT_CONVERSATIONAL",
    "SQL_MESSAGE_RECENT_SYSTEM_GLOBAL",
    "SQL_MESSAGE_RECENT_SYSTEM_FOR_SESSION",
    "SQL_MESSAGE_CONVERSATION_SUMMARY",
    "SQL_MESSAGE_HISTORY_FOR_AI_ASC_LIMIT",
    "SQL_MESSAGE_HISTORY_FOR_AI_DESC_LIMIT",
    "SQL_MESSAGE_HISTORY_FOR_AI_ASC_ALL",
    "SQL_MESSAGE_SELECT_ENCRYPTED",
    "SQL_MESSAGE_SELECT_CONTENT_BY_ID",
    "SQL_MESSAGE_UPDATE_DECRYPTED",
    "parse_message_row",
    "parse_event_row",
    "format_conversation_summary",
    "format_ai_history_rows",
    # Tool-contract parsers
    "extract_command_from_markdown_contract",
    "extract_raw_result_from_markdown_contract",
    # Encryption status
    "SQL_ENC_TOTAL_MESSAGES",
    "SQL_ENC_ENCRYPTED_MESSAGES",
    "SQL_ENC_TOTAL_KEYS",
    "SQL_ENC_ENCRYPTED_KEYS",
    "build_encryption_status",
    # Auth
    "SQL_IDENTITY_LOOKUP",
    "SQL_IDENTITY_COUNT",
    "SQL_IDENTITY_INSERT",
    "SQL_PROFILE_INSERT_DEFAULT_RETURNING",
    "SQL_SESSION_TOKEN_CREATE",
    "SQL_SESSION_TOKEN_VALIDATE",
    "SQL_SESSION_TOKEN_REVOKE",
    # Misc
    "parse_json",
    "format_session_event",
]
