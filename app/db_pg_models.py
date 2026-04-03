# FILE: app/db_pg_models.py
# DESCRIPTION: PostgreSQL models for Profile, ChatSession, APIKey, Message.
#              Uses psycopg2 raw SQL. ALL tables in PostgreSQL.
#
# Architecture: Hybrid Library (NOT Hybrid Database)
#   - SQLAlchemy-style ORM operations via raw psycopg2
#   - All data in PostgreSQL, no SQLite
#
# Schema:
#   profiles (
#     id, display_name, partner_name, affection, theme,
#     memory_json, session_history_json, global_knowledge_json,
#     providers_config_json, context, image_model, vision_model,
#     timestamp, updated_at
#   )
#   chat_sessions (
#     id, name, is_active, message_count, memory_json,
#     timestamp, updated_at
#   )
#   api_keys (
#     id, key_name, key_value, key_encrypted, timestamp
#   )

from __future__ import annotations

import json
from datetime import datetime

from app.db_pg import PgSession, pg_fetchone, pg_fetchall, pg_execute


# ── Schema Initialization ─────────────────────────────────────────────────────

def init_pg_tables():
    """Create PostgreSQL tables if they don't exist."""
    queries = [
        """
        CREATE TABLE IF NOT EXISTS profiles (
            id SERIAL PRIMARY KEY,
            display_name VARCHAR(255) NOT NULL DEFAULT 'bani',
            partner_name VARCHAR(255) NOT NULL DEFAULT 'Yuzu',
            affection INTEGER NOT NULL DEFAULT 85,
            theme VARCHAR(255) NOT NULL DEFAULT 'default',
            memory_json TEXT NOT NULL DEFAULT '{}',
            session_history_json TEXT NOT NULL DEFAULT '{}',
            global_knowledge_json TEXT NOT NULL DEFAULT '{}',
            providers_config_json TEXT NOT NULL DEFAULT '{}',
            context TEXT NOT NULL DEFAULT '{}',
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
            memory_json TEXT NOT NULL DEFAULT '{}',
            timestamp TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
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
        """
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_active ON chat_sessions(is_active)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated ON chat_sessions(updated_at)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_api_keys_name ON api_keys(key_name)
        """,
    ]

    with PgSession() as s:
        for q in queries:
            s.execute(q)
    print("[db_pg_models] PostgreSQL tables initialized")


# ── Encryption helpers (reuse from encryption.py) ───────────────────────────────

def _encrypt_api_key(api_key: str) -> str:
    """Encrypt an API key."""
    from app.encryption import encryptor
    return encryptor.encrypt(api_key)


def _decrypt_api_key(encrypted_key: str, is_encrypted: bool = True) -> str:
    """Decrypt an API key."""
    if not is_encrypted:
        return encrypted_key
    from app.encryption import encryptor
    try:
        return encryptor.decrypt(encrypted_key)
    except Exception:
        return "[DECRYPTION_ERROR]"


# ── Profile Operations ─────────────────────────────────────────────────────────

def get_profile() -> dict:
    """Get the user profile. Creates default if not exists."""
    row = pg_fetchone("SELECT * FROM profiles LIMIT 1")
    if not row:
        # Create default profile
        now = datetime.now()
        pg_execute(
            """
            INSERT INTO profiles (display_name, partner_name, affection, theme,
                                  memory_json, session_history_json, global_knowledge_json,
                                  providers_config_json, context, timestamp, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            ('bani', 'Yuzu', 85, 'default', '{}', '{}', '{}', '{}', '{}', now, now)
        )
        row = pg_fetchone("SELECT * FROM profiles LIMIT 1")

    if not row:
        return {}

    return {
        'id': row.get('id'),
        'display_name': row.get('display_name', 'bani'),
        'partner_name': row.get('partner_name', 'Yuzu'),
        'affection': row.get('affection', 85),
        'theme': row.get('theme', 'default'),
        'memory': _parse_json(row.get('memory_json', '{}')),
        'session_history': _parse_json(row.get('session_history_json', '{}')),
        'global_knowledge': _parse_json(row.get('global_knowledge_json', '{}')),
        'providers_config': _parse_json(row.get('providers_config_json', '{}')),
        'context': _parse_json(row.get('context', '{}')),
        'image_model': row.get('image_model', 'hunyuan'),
        'vision_model': row.get('vision_model', 'moonshotai/kimi-k2.5'),
        'created_at': row.get('created_at'),
        'updated_at': row.get('updated_at'),
    }


def update_profile(updates: dict) -> bool:
    """Update the user profile."""
    if not updates:
        return False

    # Build SET clause
    set_parts = []
    params = []
    for key, value in updates.items():
        if key in ('memory', 'session_history', 'global_knowledge', 'providers_config', 'context'):
            # JSON fields
            set_parts.append(f"{key}_json = %s")
            params.append(json.dumps(value) if isinstance(value, dict) else str(value))
        elif key in ('display_name', 'partner_name', 'theme', 'image_model', 'vision_model'):
            set_parts.append(f"{key} = %s")
            params.append(str(value))
        elif key == 'affection':
            set_parts.append("affection = %s")
            params.append(int(value))

    if not set_parts:
        return False

    set_parts.append("updated_at = %s")
    params.append(datetime.now())

    query = f"UPDATE profiles SET {', '.join(set_parts)}"
    try:
        pg_execute(query, params)
        return True
    except Exception as e:
        print(f"[db_pg_models] update_profile failed: {e}")
        return False


def get_context() -> dict:
    """Get the user context."""
    profile = get_profile()
    return profile.get('context', {})


def update_context(context_dict: dict) -> bool:
    """Update the user context."""
    return update_profile({'context': context_dict})


def get_memory() -> dict:
    """Get the user memory."""
    profile = get_profile()
    return profile.get('memory', {})


def update_memory(memory_dict: dict) -> bool:
    """Update the user memory."""
    return update_profile({'memory': memory_dict})


# ── ChatSession Operations ─────────────────────────────────────────────────────

def get_active_session() -> dict:
    """Get the currently active session. Creates one if none."""
    row = pg_fetchone(
        "SELECT * FROM chat_sessions WHERE is_active = TRUE LIMIT 1"
    )

    if not row:
        # Create new active session
        now = datetime.now()
        pg_execute(
            """
            INSERT INTO chat_sessions (name, is_active, message_count, memory_json, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            """,
            ('New Chat', True, 0, '{}', now, now)
        )
        row = pg_fetchone(
            "SELECT * FROM chat_sessions WHERE is_active = TRUE LIMIT 1"
        )

    if not row:
        return {}

    return {
        'id': row.get('id'),
        'name': row.get('name', 'New Chat'),
        'is_active': row.get('is_active', False),
        'message_count': row.get('message_count', 0),
        'memory': _parse_json(row.get('memory_json', '{}')),
        'created_at': row.get('created_at'),
        'updated_at': row.get('updated_at'),
    }


def get_all_sessions() -> list[dict]:
    """Get all sessions ordered by updated_at."""
    rows = pg_fetchall(
        "SELECT * FROM chat_sessions ORDER BY updated_at DESC"
    )
    return [
        {
            'id': r.get('id'),
            'name': r.get('name', 'New Chat'),
            'is_active': r.get('is_active', False),
            'message_count': r.get('message_count', 0),
            'memory': _parse_json(r.get('memory_json', '{}')),
            'timestamp': r.get('timestamp'),
            'updated_at': r.get('updated_at'),
        }
        for r in rows
    ]


def create_session(name: str = "New Chat") -> int | None:
    """Create a new chat session. Returns the new session id."""
    now = datetime.now()
    try:
        with PgSession() as s:
            row = s.execute_returning(
                """
                INSERT INTO chat_sessions (name, is_active, message_count, memory_json, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (name, False, 0, '{}', now, now)
            )
            return row.get('id') if row else None
    except Exception as e:
        print(f"[db_pg_models] create_session failed: {e}")
        return None


def switch_session(session_id: int) -> bool:
    """Switch to a different session."""
    try:
        with PgSession() as s:
            s.execute("UPDATE chat_sessions SET is_active = FALSE")
            s.execute(
                "UPDATE chat_sessions SET is_active = TRUE, updated_at = %s WHERE id = %s",
                (datetime.now(), session_id)
            )
        return True
    except Exception as e:
        print(f"[db_pg_models] switch_session failed: {e}")
        return False


def rename_session(session_id: int, new_name: str) -> bool:
    """Rename a session."""
    try:
        pg_execute(
            "UPDATE chat_sessions SET name = %s, updated_at = %s WHERE id = %s",
            (new_name, datetime.now(), session_id)
        )
        return True
    except Exception as e:
        print(f"[db_pg_models] rename_session failed: {e}")
        return False


def delete_session(session_id: int) -> bool:
    """Delete a session. Returns True if deleted."""
    try:
        with PgSession() as s:
            s.execute("DELETE FROM chat_sessions WHERE id = %s", (session_id,))
        return True
    except Exception as e:
        print(f"[db_pg_models] delete_session failed: {e}")
        return False


def update_session_memory(session_id: int, memory: dict) -> bool:
    """Update session memory_json."""
    try:
        pg_execute(
            "UPDATE chat_sessions SET memory_json = %s, updated_at = %s WHERE id = %s",
            (json.dumps(memory), datetime.now(), session_id)
        )
        return True
    except Exception as e:
        print(f"[db_pg_models] update_session_memory failed: {e}")
        return False


def get_session_memory(session_id: int) -> dict:
    """Get session memory from messages table - returns system/memory notes for the session."""
    rows = pg_fetchall(
        """
        SELECT content, role, timestamp
        FROM messages
        WHERE session_id = %s AND role IN ('system', 'memory')
        ORDER BY timestamp DESC
        LIMIT 50
        """,
        (session_id,)
    )
    if not rows:
        return {}
    return {
        'notes': [{'content': r.get('content'), 'role': r.get('role'), 'timestamp': str(r.get('timestamp'))} for r in rows],
        'count': len(rows)
    }


def get_chat_history(session_id: int, limit: int | None = None, recent: bool = False) -> list[dict]:
    """Get chat history for a session - returns messages ordered by timestamp."""
    if limit and recent:
        query = """
            SELECT id, session_id, role, content, timestamp
            FROM messages
            WHERE session_id = %s
            ORDER BY timestamp DESC
            LIMIT %s
        """
        rows = pg_fetchall(query, (session_id, limit))
        return list(reversed(rows))
    elif limit:
        query = """
            SELECT id, session_id, role, content, timestamp
            FROM messages
            WHERE session_id = %s
            ORDER BY timestamp ASC
            LIMIT %s
        """
        rows = pg_fetchall(query, (session_id, limit))
    else:
        query = """
            SELECT id, session_id, role, content, timestamp
            FROM messages
            WHERE session_id = %s
            ORDER BY timestamp ASC
        """
        rows = pg_fetchall(query, (session_id,))
    
    return [
        {
            'id': r.get('id'),
            'session_id': r.get('session_id'),
            'role': r.get('role'),
            'content': r.get('content'),
            'timestamp': str(r.get('timestamp', '')),
        }
        for r in rows
    ]


def increment_message_count(session_id: int) -> bool:
    """Increment the message count for a session."""
    try:
        pg_execute(
            "UPDATE chat_sessions SET message_count = message_count + 1, updated_at = %s WHERE id = %s",
            (datetime.now(), session_id)
        )
        return True
    except Exception as e:
        print(f"[db_pg_models] increment_message_count failed: {e}")
        return False


# ── APIKey Operations ──────────────────────────────────────────────────────────

def get_api_keys(key_name: str | None = None) -> dict[str, str]:
    """Get API keys (decrypted)."""
    if key_name:
        rows = pg_fetchall(
            "SELECT key_name, key_value, key_encrypted FROM api_keys WHERE key_name = %s",
            (key_name,)
        )
    else:
        rows = pg_fetchall("SELECT key_name, key_value, key_encrypted FROM api_keys")

    result = {}
    for r in rows:
        name = r.get('key_name')
        value = r.get('key_value', '')
        encrypted = r.get('key_encrypted', True)
        if encrypted:
            decrypted = _decrypt_api_key(value, True)
            if decrypted != "[DECRYPTION_ERROR]":
                result[name] = decrypted
        else:
            result[name] = value

    return result


def get_api_key(key_name: str) -> str | None:
    """Get a single API key."""
    keys = get_api_keys(key_name)
    return keys.get(key_name)


def add_api_key(key_name: str, key_value: str) -> bool:
    """Add or update an API key."""
    encrypted = _encrypt_api_key(key_value)
    is_encrypted = encrypted != key_value

    try:
        existing = pg_fetchone(
            "SELECT id FROM api_keys WHERE key_name = %s", (key_name,)
        )
        if existing:
            pg_execute(
                "UPDATE api_keys SET key_value = %s, key_encrypted = %s WHERE key_name = %s",
                (encrypted, is_encrypted, key_name)
            )
        else:
            pg_execute(
                "INSERT INTO api_keys (key_name, key_value, key_encrypted, timestamp) VALUES (%s, %s, %s, %s)",
                (key_name, encrypted, is_encrypted, datetime.now())
            )
        return True
    except Exception as e:
        print(f"[db_pg_models] add_api_key failed: {e}")
        return False


def remove_api_key(key_name: str) -> bool:
    """Remove an API key."""
    try:
        pg_execute("DELETE FROM api_keys WHERE key_name = %s", (key_name,))
        return True
    except Exception as e:
        print(f"[db_pg_models] remove_api_key failed: {e}")
        return False


# ── Message Operations ────────────────────────────────────────────────────────

# Tool-specific role mapping: each tool gets its own dedicated message role
TOOL_ROLES = {
    'image_generate': 'image_tools',
    'imagine': 'image_tools',
    'request': 'request_tools',
}

# All tool roles for use in queries (unique values only)
ALL_TOOL_ROLES = list(set(TOOL_ROLES.values()))


def add_message(session_id: int, role: str, content: str, image_paths: str | None = None) -> int | None:
    """Add a message to a session. Returns the new message id."""
    now = datetime.now()
    try:
        with PgSession() as s:
            row = s.execute_returning(
                """
                INSERT INTO messages (session_id, role, content, timestamp, content_encrypted)
                VALUES (%s, %s, %s, %s, FALSE) RETURNING id
                """,
                (session_id, role, content, now)
            )
            if row:
                increment_message_count(session_id)
                return row.get('id')
        return None
    except Exception as e:
        print(f"[db_pg_models] add_message failed: {e}")
        return None


def get_session_messages(session_id: int, limit: int = 100) -> list[dict]:
    """Get messages for a session, ordered by timestamp."""
    rows = pg_fetchall(
        """
        SELECT id, session_id, role, content, timestamp
        FROM messages
        WHERE session_id = %s
        ORDER BY timestamp ASC
        LIMIT %s
        """,
        (session_id, limit)
    )
    return [
        {
            'id': r.get('id'),
            'session_id': r.get('session_id'),
            'role': r.get('role'),
            'content': r.get('content'),
            'timestamp': str(r.get('timestamp', '')),
        }
        for r in rows
    ]


def get_recent_messages(session_id: int, limit: int = 20) -> list[dict]:
    """Get recent messages for a session."""
    return get_session_messages(session_id, limit)


def clear_session_messages(session_id: int) -> bool:
    """Delete all messages for a session."""
    try:
        pg_execute("DELETE FROM messages WHERE session_id = %s", (session_id,))
        pg_execute(
            "UPDATE chat_sessions SET message_count = 0, memory_json = '{}', updated_at = %s WHERE id = %s",
            (datetime.now(), session_id)
        )
        return True
    except Exception as e:
        print(f"[db_pg_models] clear_session_messages failed: {e}")
        return False


def get_message_count(session_id: int) -> int:
    """Get message count for a session (user + assistant only)."""
    row = pg_fetchone(
        "SELECT COUNT(*) as cnt FROM messages WHERE session_id = %s AND role IN ('user', 'assistant')",
        (session_id,)
    )
    return row.get('cnt', 0) if row else 0


def add_session_event(session_id: int, content: str, interface: str = "terminal") -> int | None:
    """Add a session event message."""
    event_content = f"*{content} on {interface}*"
    return add_message(session_id, 'system', event_content)


def get_recent_sessions(limit: int = 20) -> list[dict]:
    """Get recent session events across all sessions."""
    rows = pg_fetchall(
        """
        SELECT content, timestamp
        FROM messages
        WHERE role = 'system'
        ORDER BY timestamp DESC
        LIMIT %s
        """,
        (limit,)
    )
    return [
        {
            'content': r.get('content', ''),
            'timestamp': str(r.get('timestamp', '')),
        }
        for r in rows
    ]


def get_recent_sessions_for_session(session_id: int, limit: int = 20) -> list[dict]:
    """Get recent session events for a specific session."""
    rows = pg_fetchall(
        """
        SELECT content, timestamp
        FROM messages
        WHERE role = 'system' AND session_id = %s
        ORDER BY timestamp DESC
        LIMIT %s
        """,
        (session_id, limit)
    )
    return [
        {
            'content': r.get('content', ''),
            'timestamp': str(r.get('timestamp', '')),
        }
        for r in rows
    ]


def get_session_conversation_summary(session_id: int, limit: int = 20) -> str:
    """Get a summary of recent conversation."""
    rows = pg_fetchall(
        """
        SELECT role, content
        FROM messages
        WHERE session_id = %s AND role IN ('user', 'assistant')
        ORDER BY timestamp ASC
        LIMIT %s
        """,
        (session_id, limit)
    )
    lines = []
    for r in rows:
        role = 'User' if r.get('role') == 'user' else 'AI'
        content = r.get('content', '')
        if len(content) > 100:
            content = content[:100] + '...'
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def add_image_tools_message(session_id: int, image_url: str) -> int | None:
    """Add an image tools message."""
    return add_message(session_id, 'image_tools', image_url)


def add_tool_result(session_id: int, tool_name: str, result_content: str) -> int | None:
    """Store tool result in database with tool-specific role."""
    role = TOOL_ROLES.get(tool_name, f'{tool_name}_tools')
    return add_message(session_id, role, result_content)


def add_system_note(session_id: int, content: str) -> int | None:
    """Add a system note message."""
    return add_message(session_id, 'system', content)


def add_memory_note(session_id: int, content: str) -> int | None:
    """Add a memory note (alias for add_system_note)."""
    return add_system_note(session_id, content)


def _extract_command_from_markdown_contract(content: str) -> str:
    """Extract command from markdown contract."""
    import re
    if not content:
        return content
    m = re.search(r'```bash\n\S+\$\s*(/[^\n]+)\n```', content)
    if m:
        return m.group(1).strip()
    return content


def _extract_raw_result_from_markdown_contract(content: str) -> str:
    """Extract raw result from markdown contract, stripping formatting."""
    import re
    if not content:
        return content

    result = content
    result = re.sub(r'<details>\s*<summary>.*?</summary>', '', result, flags=re.DOTALL)
    result = re.sub(r'</details>', '', result, flags=re.DOTALL)
    result = re.sub(r'```bash\n.*?\n```', '', result, flags=re.DOTALL)
    result = re.sub(r'```[\w]*\n?', '', result)
    result = re.sub(r'```', '', result)
    result = re.sub(r'^>\s*', '', result, flags=re.MULTILINE)
    result = re.sub(r'<[^>]+>', '', result)
    result = re.sub(r'^\n+', '', result)
    result = re.sub(r'\n+$', '', result)
    return result.strip()


def get_chat_history_for_ai(session_id: int, limit: int | None = None, recent: bool = False) -> list[dict]:
    """
    Build message context for AI provider.
    
    Returns chronologically ordered messages with tool results parsed into
    separate assistant command + tool role entries.
    """
    if limit and recent:
        query = """
            SELECT id, role, content, timestamp
            FROM messages
            WHERE session_id = %s
            ORDER BY timestamp DESC
            LIMIT %s
        """
        rows = pg_fetchall(query, (session_id, limit))
        rows = list(reversed(rows))
    elif limit:
        query = """
            SELECT id, role, content, timestamp
            FROM messages
            WHERE session_id = %s
            ORDER BY timestamp ASC
            LIMIT %s
        """
        rows = pg_fetchall(query, (session_id, limit))
    else:
        query = """
            SELECT id, role, content, timestamp
            FROM messages
            WHERE session_id = %s
            ORDER BY timestamp ASC
        """
        rows = pg_fetchall(query, (session_id,))

    formatted_messages = []
    for msg in rows:
        content = msg.get('content', '')
        role = msg.get('role', '')
        
        # Skip event_log roles
        if role == 'event_log':
            continue

        if role == 'user':
            ts = msg.get('timestamp', '')
            try:
                if isinstance(ts, str):
                    dt = datetime.strptime(ts[:19], '%Y-%m-%d %H:%M:%S')
                else:
                    dt = ts
                formatted_timestamp = dt.strftime('[%Y-%m-%d %H:%M:%S]')
            except Exception:
                formatted_timestamp = f"[{ts}]"
            formatted_messages.append({
                'role': role,
                'content': f"{content} {formatted_timestamp}"
            })
        elif role in ('assistant', 'system'):
            formatted_messages.append({
                'role': role,
                'content': content
            })
        elif role in ALL_TOOL_ROLES:
            # Parse canonical markdown contract
            command_line = _extract_command_from_markdown_contract(content)
            raw_result = _extract_raw_result_from_markdown_contract(content)
            # Append TWO entries: assistant command + tool result
            formatted_messages.append({
                'role': 'assistant',
                'content': command_line
            })
            formatted_messages.append({
                'role': role,
                'content': raw_result
            })

    return formatted_messages


def get_encryption_status() -> dict:
    """Get encryption status summary."""
    total_msg = pg_fetchone("SELECT COUNT(*) as cnt FROM messages")
    encrypted_msg = pg_fetchone("SELECT COUNT(*) as cnt FROM messages WHERE content_encrypted = TRUE")
    total_keys = pg_fetchone("SELECT COUNT(*) as cnt FROM api_keys")
    encrypted_keys = pg_fetchone("SELECT COUNT(*) as cnt FROM api_keys WHERE key_encrypted = TRUE")
    
    return {
        'messages': {
            'total': total_msg.get('cnt', 0) if total_msg else 0,
            'encrypted': encrypted_msg.get('cnt', 0) if encrypted_msg else 0,
            'policy': 'NO_ENCRYPTION'
        },
        'api_keys': {
            'total': total_keys.get('cnt', 0) if total_keys else 0,
            'encrypted': encrypted_keys.get('cnt', 0) if encrypted_keys else 0,
            'policy': 'FULL_ENCRYPTION'
        }
    }


def get_all_encrypted_messages() -> list[dict]:
    """Get all encrypted messages (for migration)."""
    rows = pg_fetchall(
        """
        SELECT id, session_id, role, content, timestamp
        FROM messages
        WHERE content_encrypted = TRUE
        """
    )
    return [
        {
            'id': r.get('id'),
            'session_id': r.get('session_id'),
            'role': r.get('role'),
            'content': r.get('content'),
            'timestamp': str(r.get('timestamp', '')),
        }
        for r in rows
    ]


def batch_decrypt_messages(message_ids: list[int]) -> dict:
    """Batch decrypt messages."""
    decrypted_count = 0
    failed_count = 0
    
    for msg_id in message_ids:
        try:
            row = pg_fetchone("SELECT content FROM messages WHERE id = %s", (msg_id,))
            if row and row.get('content'):
                from app.encryption import encryptor
                decrypted = encryptor.decrypt(row['content'])
                pg_execute(
                    "UPDATE messages SET content = %s, content_encrypted = FALSE WHERE id = %s",
                    (decrypted, msg_id)
                )
                decrypted_count += 1
        except Exception as e:
            failed_count += 1
            print(f"Failed to decrypt message {msg_id}: {e}")
    
    return {'decrypted': decrypted_count, 'failed': failed_count, 'total': len(message_ids)}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_json(s: str | None) -> dict:
    """Parse JSON string safely."""
    if not s:
        return {}
    try:
        return json.loads(s) if isinstance(s, str) else s
    except (json.JSONDecodeError, TypeError):
        return {}