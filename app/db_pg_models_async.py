# FILE: app/db_pg_models_async.py
# DESCRIPTION: Async PostgreSQL models for Profile, ChatSession, APIKey, Message.
#              Full async implementation using psycopg v3 AsyncConnectionPool.
#
# Architecture: Hybrid Library (NOT Hybrid Database)
#   - SQLAlchemy-style ORM operations via raw psycopg v3 async
#   - All data in PostgreSQL, no SQLite
#
# NOTE: Sync wrappers in db_pg_models.py call these async functions.
#       Web routes should import from this file for true async I/O.

from __future__ import annotations

import json
from datetime import datetime

from app.db_pg import AsyncPgSession, pg_fetchone_async, pg_fetchall_async, pg_execute_async


# ── Schema Initialization ─────────────────────────────────────────────────────

async def init_pg_tables_async():
    """Create PostgreSQL tables if they don't exist."""
    queries = [
        """
        CREATE TABLE IF NOT EXISTS profiles (
            id SERIAL PRIMARY KEY,
            display_name VARCHAR(255) NOT NULL DEFAULT '',
            partner_name VARCHAR(255) NOT NULL DEFAULT '',
            affection INTEGER NOT NULL DEFAULT 50,
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
        "CREATE INDEX IF NOT EXISTS idx_chat_sessions_active ON chat_sessions(is_active)",
        "CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated ON chat_sessions(updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_api_keys_name ON api_keys(key_name)",
    ]

    async with AsyncPgSession() as s:
        for q in queries:
            await s.execute(q)
    print("[db_pg_models_async] PostgreSQL tables initialized")


# ── Encryption helpers (sync, CPU-bound) ─────────────────────────────────────

def _encrypt_api_key(api_key: str) -> str:
    """Encrypt an API key (sync, CPU-bound)."""
    from app.encryption import encryptor
    return encryptor.encrypt(api_key)


def _decrypt_api_key(encrypted_key: str, is_encrypted: bool = True) -> str:
    """Decrypt an API key (sync, CPU-bound)."""
    if not is_encrypted:
        return encrypted_key
    from app.encryption import encryptor
    try:
        return encryptor.decrypt(encrypted_key)
    except Exception:
        return "[DECRYPTION_ERROR]"


# ── Profile Operations (async) ───────────────────────────────────────────────

async def get_profile_async() -> dict:
    """Get the user profile. Creates default if not exists."""
    row = await pg_fetchone_async("SELECT * FROM profiles LIMIT 1")
    if not row:
        now = datetime.now()
        await pg_execute_async(
            """
            INSERT INTO profiles (display_name, partner_name, affection, theme,
                                  memory_json, session_history_json, global_knowledge_json,
                                  providers_config_json, context, timestamp, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            ('', '', 50, 'default', '{}', '{}', '{}', '{}', '{}', now, now)
        )
        row = await pg_fetchone_async("SELECT * FROM profiles LIMIT 1")

    if not row:
        return {}

    return {
        'id': row.get('id'),
        'display_name': row.get('display_name', ''),
        'partner_name': row.get('partner_name', ''),
        'affection': row.get('affection', 50),
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


async def update_profile_async(updates: dict) -> bool:
    """Update the user profile."""
    if not updates:
        return False

    set_parts = []
    params = []
    for key, value in updates.items():
        if key in ('memory', 'session_history', 'global_knowledge', 'providers_config', 'context'):
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
        await pg_execute_async(query, params)
        return True
    except Exception as e:
        print(f"[db_pg_models_async] update_profile_async failed: {e}")
        return False


async def get_context_async() -> dict:
    """Get the user context."""
    profile = await get_profile_async()
    return profile.get('context', {})


async def update_context_async(context_dict: dict) -> bool:
    """Update the user context."""
    return await update_profile_async({'context': context_dict})


async def get_memory_async() -> dict:
    """Get the user memory."""
    profile = await get_profile_async()
    return profile.get('memory', {})


async def update_memory_async(memory_dict: dict) -> bool:
    """Update the user memory."""
    return await update_profile_async({'memory': memory_dict})


# ── ChatSession Operations (async) ─────────────────────────────────────────────

async def get_active_session_async() -> dict:
    """Get the currently active session. Creates one if none."""
    row = await pg_fetchone_async(
        "SELECT * FROM chat_sessions WHERE is_active = TRUE LIMIT 1"
    )

    if not row:
        now = datetime.now()
        await pg_execute_async(
            """
            INSERT INTO chat_sessions (name, is_active, message_count, memory_json, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            """,
            ('New Chat', True, 0, '{}', now, now)
        )
        row = await pg_fetchone_async(
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


async def get_all_sessions_async() -> list[dict]:
    """Get all sessions ordered by updated_at."""
    rows = await pg_fetchall_async(
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


async def create_session_async(name: str = "New Chat") -> int | None:
    """Create a new chat session. Returns the new session id."""
    now = datetime.now()
    try:
        async with AsyncPgSession() as s:
            row = await s.execute_returning(
                """
                INSERT INTO chat_sessions (name, is_active, message_count, memory_json, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (name, False, 0, '{}', now, now)
            )
            return row.get('id') if row else None
    except Exception as e:
        print(f"[db_pg_models_async] create_session_async failed: {e}")
        return None


async def switch_session_async(session_id: int) -> bool:
    """Switch to a different session."""
    try:
        async with AsyncPgSession() as s:
            await s.execute("UPDATE chat_sessions SET is_active = FALSE")
            await s.execute(
                "UPDATE chat_sessions SET is_active = TRUE, updated_at = %s WHERE id = %s",
                (datetime.now(), session_id)
            )
        return True
    except Exception as e:
        print(f"[db_pg_models_async] switch_session_async failed: {e}")
        return False


async def rename_session_async(session_id: int, new_name: str) -> bool:
    """Rename a session."""
    try:
        await pg_execute_async(
            "UPDATE chat_sessions SET name = %s, updated_at = %s WHERE id = %s",
            (new_name, datetime.now(), session_id)
        )
        return True
    except Exception as e:
        print(f"[db_pg_models_async] rename_session_async failed: {e}")
        return False


async def delete_session_async(session_id: int) -> bool:
    """Delete a session. Returns True if deleted."""
    try:
        async with AsyncPgSession() as s:
            await s.execute("DELETE FROM chat_sessions WHERE id = %s", (session_id,))
        return True
    except Exception as e:
        print(f"[db_pg_models_async] delete_session_async failed: {e}")
        return False


async def update_session_memory_async(session_id: int, memory: dict) -> bool:
    """Update session memory_json."""
    try:
        await pg_execute_async(
            "UPDATE chat_sessions SET memory_json = %s, updated_at = %s WHERE id = %s",
            (json.dumps(memory), datetime.now(), session_id)
        )
        return True
    except Exception as e:
        print(f"[db_pg_models_async] update_session_memory_async failed: {e}")
        return False


async def get_session_memory_async(session_id: int) -> dict:
    """Get session memory from messages table."""
    rows = await pg_fetchall_async(
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


async def get_chat_history_async(session_id: int, limit: int | None = None, recent: bool = False) -> list[dict]:
    """Get chat history for a session."""
    if limit and recent:
        query = """
            SELECT id, session_id, role, content, timestamp
            FROM messages
            WHERE session_id = %s
            ORDER BY timestamp DESC
            LIMIT %s
        """
        rows = await pg_fetchall_async(query, (session_id, limit))
        rows = list(reversed(rows))
    elif limit:
        query = """
            SELECT id, session_id, role, content, timestamp
            FROM messages
            WHERE session_id = %s
            ORDER BY timestamp ASC
            LIMIT %s
        """
        rows = await pg_fetchall_async(query, (session_id, limit))
    else:
        query = """
            SELECT id, session_id, role, content, timestamp
            FROM messages
            WHERE session_id = %s
            ORDER BY timestamp ASC
        """
        rows = await pg_fetchall_async(query, (session_id,))
    
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


async def increment_message_count_async(session_id: int) -> bool:
    """Increment the message count for a session."""
    try:
        await pg_execute_async(
            "UPDATE chat_sessions SET message_count = message_count + 1, updated_at = %s WHERE id = %s",
            (datetime.now(), session_id)
        )
        return True
    except Exception as e:
        print(f"[db_pg_models_async] increment_message_count_async failed: {e}")
        return False


# ── APIKey Operations (async) ──────────────────────────────────────────────────

async def get_api_keys_async(key_name: str | None = None) -> dict[str, str]:
    """Get API keys (decrypted)."""
    if key_name:
        rows = await pg_fetchall_async(
            "SELECT key_name, key_value, key_encrypted FROM api_keys WHERE key_name = %s",
            (key_name,)
        )
    else:
        rows = await pg_fetchall_async("SELECT key_name, key_value, key_encrypted FROM api_keys")

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


async def get_api_key_async(key_name: str) -> str | None:
    """Get a single API key."""
    keys = await get_api_keys_async(key_name)
    return keys.get(key_name)


async def add_api_key_async(key_name: str, key_value: str) -> bool:
    """Add or update an API key."""
    encrypted = _encrypt_api_key(key_value)
    is_encrypted = encrypted != key_value

    try:
        existing = await pg_fetchone_async(
            "SELECT id FROM api_keys WHERE key_name = %s", (key_name,)
        )
        if existing:
            await pg_execute_async(
                "UPDATE api_keys SET key_value = %s, key_encrypted = %s WHERE key_name = %s",
                (encrypted, is_encrypted, key_name)
            )
        else:
            await pg_execute_async(
                "INSERT INTO api_keys (key_name, key_value, key_encrypted, timestamp) VALUES (%s, %s, %s, %s)",
                (key_name, encrypted, is_encrypted, datetime.now())
            )
        return True
    except Exception as e:
        print(f"[db_pg_models_async] add_api_key_async failed: {e}")
        return False


async def remove_api_key_async(key_name: str) -> bool:
    """Remove an API key."""
    try:
        await pg_execute_async("DELETE FROM api_keys WHERE key_name = %s", (key_name,))
        return True
    except Exception as e:
        print(f"[db_pg_models_async] remove_api_key_async failed: {e}")
        return False


# ── Message Operations (async) ────────────────────────────────────────────────

TOOL_ROLES = {
    'image_generate': 'image_tools',
    'imagine': 'image_tools',
    'request': 'request_tools',
}
ALL_TOOL_ROLES = list(set(TOOL_ROLES.values()))


async def add_message_async(session_id: int, role: str, content: str, image_paths: str | None = None) -> int | None:
    """Add a message to a session. Returns the new message id."""
    now = datetime.now()
    try:
        async with AsyncPgSession() as s:
            row = await s.execute_returning(
                """
                INSERT INTO messages (session_id, role, content, timestamp, content_encrypted)
                VALUES (%s, %s, %s, %s, FALSE) RETURNING id
                """,
                (session_id, role, content, now)
            )
            if row:
                await increment_message_count_async(session_id)
                return row.get('id')
        return None
    except Exception as e:
        print(f"[db_pg_models_async] add_message_async failed: {e}")
        return None


async def get_session_messages_async(session_id: int, limit: int = 100) -> list[dict]:
    """Get messages for a session, ordered by timestamp."""
    rows = await pg_fetchall_async(
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


async def get_recent_messages_async(session_id: int, limit: int = 20) -> list[dict]:
    """Get recent messages for a session."""
    return await get_session_messages_async(session_id, limit)


async def clear_session_messages_async(session_id: int) -> bool:
    """Delete all messages for a session."""
    try:
        await pg_execute_async("DELETE FROM messages WHERE session_id = %s", (session_id,))
        await pg_execute_async(
            "UPDATE chat_sessions SET message_count = 0, memory_json = '{}', updated_at = %s WHERE id = %s",
            (datetime.now(), session_id)
        )
        return True
    except Exception as e:
        print(f"[db_pg_models_async] clear_session_messages_async failed: {e}")
        return False


async def get_message_count_async(session_id: int) -> int:
    """Get message count for a session (user + assistant only)."""
    row = await pg_fetchone_async(
        "SELECT COUNT(*) as cnt FROM messages WHERE session_id = %s AND role IN ('user', 'assistant')",
        (session_id,)
    )
    return row.get('cnt', 0) if row else 0


async def add_session_event_async(session_id: int, content: str, interface: str = "terminal") -> int | None:
    """Add a session event message."""
    event_content = f"*{content} on {interface}*"
    return await add_message_async(session_id, 'system', event_content)


async def get_recent_sessions_async(limit: int = 20) -> list[dict]:
    """Get recent session events across all sessions."""
    rows = await pg_fetchall_async(
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


async def get_recent_sessions_for_session_async(session_id: int, limit: int = 20) -> list[dict]:
    """Get recent session events for a specific session."""
    rows = await pg_fetchall_async(
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


async def get_session_conversation_summary_async(session_id: int, limit: int = 20) -> str:
    """Get a summary of recent conversation."""
    rows = await pg_fetchall_async(
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


async def add_image_tools_message_async(session_id: int, image_url: str) -> int | None:
    """Add an image tools message."""
    return await add_message_async(session_id, 'image_tools', image_url)


async def add_tool_result_async(session_id: int, tool_name: str, result_content: str) -> int | None:
    """Store tool result in database with tool-specific role."""
    role = TOOL_ROLES.get(tool_name, f'{tool_name}_tools')
    return await add_message_async(session_id, role, result_content)


async def add_system_note_async(session_id: int, content: str) -> int | None:
    """Add a system note message."""
    return await add_message_async(session_id, 'system', content)


async def add_memory_note_async(session_id: int, content: str) -> int | None:
    """Add a memory note (alias for add_system_note_async)."""
    return await add_system_note_async(session_id, content)


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


async def get_chat_history_for_ai_async(session_id: int, limit: int | None = None, recent: bool = False) -> list[dict]:
    """Build message context for AI provider."""
    if limit and recent:
        query = """
            SELECT id, role, content, timestamp
            FROM messages
            WHERE session_id = %s
            ORDER BY timestamp DESC
            LIMIT %s
        """
        rows = await pg_fetchall_async(query, (session_id, limit))
        rows = list(reversed(rows))
    elif limit:
        query = """
            SELECT id, role, content, timestamp
            FROM messages
            WHERE session_id = %s
            ORDER BY timestamp ASC
            LIMIT %s
        """
        rows = await pg_fetchall_async(query, (session_id, limit))
    else:
        query = """
            SELECT id, role, content, timestamp
            FROM messages
            WHERE session_id = %s
            ORDER BY timestamp ASC
        """
        rows = await pg_fetchall_async(query, (session_id,))

    formatted_messages = []
    for msg in rows:
        content = msg.get('content', '')
        role = msg.get('role', '')
        
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
            command_line = _extract_command_from_markdown_contract(content)
            raw_result = _extract_raw_result_from_markdown_contract(content)
            formatted_messages.append({
                'role': 'assistant',
                'content': command_line
            })
            formatted_messages.append({
                'role': role,
                'content': raw_result
            })

    return formatted_messages


async def get_encryption_status_async() -> dict:
    """Get encryption status summary."""
    total_msg = await pg_fetchone_async("SELECT COUNT(*) as cnt FROM messages")
    encrypted_msg = await pg_fetchone_async("SELECT COUNT(*) as cnt FROM messages WHERE content_encrypted = TRUE")
    total_keys = await pg_fetchone_async("SELECT COUNT(*) as cnt FROM api_keys")
    encrypted_keys = await pg_fetchone_async("SELECT COUNT(*) as cnt FROM api_keys WHERE key_encrypted = TRUE")
    
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


async def get_all_encrypted_messages_async() -> list[dict]:
    """Get all encrypted messages (for migration)."""
    rows = await pg_fetchall_async(
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


async def batch_decrypt_messages_async(message_ids: list[int]) -> dict:
    """Batch decrypt messages."""
    decrypted_count = 0
    failed_count = 0
    
    for msg_id in message_ids:
        try:
            row = await pg_fetchone_async("SELECT content FROM messages WHERE id = %s", (msg_id,))
            if row and row.get('content'):
                from app.encryption import encryptor
                decrypted = encryptor.decrypt(row['content'])
                await pg_execute_async(
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
