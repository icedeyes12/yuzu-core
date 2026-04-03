# FILE: app/database.py
# DESCRIPTION: Legacy database interface - delegates to PostgreSQL via db_pg_models.
#              ALL operations now use PostgreSQL. NO SQLite connection.
#
# Architecture: Hybrid Library (NOT Hybrid Database)
#   - SQLAlchemy-style ORM operations via raw psycopg2
#   - All data in PostgreSQL, no SQLite
#
# Migration Status:
#   ✅ Profile, ChatSession, APIKey -> PostgreSQL (via db_pg_models)
#   ✅ Message -> PostgreSQL (via db_pg_models)
#   ❌ SemanticMemory, EpisodicMemory, ConversationSegment -> deprecated (use db_memory.py)

from __future__ import annotations


# Import ALL PostgreSQL operations
from app.db_pg_models import (
    # Profile operations
    get_profile as _pg_get_profile,
    update_profile as _pg_update_profile,
    get_context as _pg_get_context,
    update_context as _pg_update_context,
    # APIKey operations
    get_api_keys as _pg_get_api_keys,
    get_api_key as _pg_get_api_key,
    add_api_key as _pg_add_api_key,
    remove_api_key as _pg_remove_api_key,
    # ChatSession operations
    get_active_session as _pg_get_active_session,
    get_all_sessions as _pg_get_all_sessions,
    create_session as _pg_create_session,
    switch_session as _pg_switch_session,
    rename_session as _pg_rename_session,
    delete_session as _pg_delete_session,
    get_session_memory as _pg_get_session_memory,
    update_session_memory as _pg_update_session_memory,
    increment_message_count as _pg_increment_message_count,
    # Message operations
    add_message as _pg_add_message,
    get_session_messages as _pg_get_session_messages,
    get_chat_history as _pg_get_chat_history,
    clear_session_messages as _pg_clear_session_messages,
    get_message_count as _pg_get_message_count,
    add_session_event as _pg_add_session_event,
    get_recent_sessions as _pg_get_recent_sessions,
    get_recent_sessions_for_session as _pg_get_recent_sessions_for_session,
    get_session_conversation_summary as _pg_get_session_conversation_summary,
    add_image_tools_message as _pg_add_image_tools_message,
    add_tool_result as _pg_add_tool_result,
    add_system_note as _pg_add_system_note,
    get_chat_history_for_ai as _pg_get_chat_history_for_ai,
    get_encryption_status as _pg_get_encryption_status,
    get_all_encrypted_messages as _pg_get_all_encrypted_messages,
    batch_decrypt_messages as _pg_batch_decrypt_messages,
    # Schema init
    init_pg_tables as _init_pg_tables,
    # Tool roles (for backward compat)
    TOOL_ROLES,
    ALL_TOOL_ROLES,
)


# ---------------------------------------------------------------------------
# Database Initialization
# ---------------------------------------------------------------------------

def init_db():
    """
    Initialize database.
    
    ALL tables in PostgreSQL. NO SQLite connection.
    """
    print("[DB INIT] Initializing PostgreSQL tables...")
    try:
        _init_pg_tables()
        print("[DB INIT] PostgreSQL tables initialized successfully")
    except Exception as e:
        print(f"[DB INIT] PostgreSQL initialization failed: {e}")
        raise


# ---------------------------------------------------------------------------
# FastAPI Dependency Injection (kept for backward compat)
# ---------------------------------------------------------------------------

def get_db():
    """
    FastAPI dependency stub. No longer needed but kept for backward compat.
    """
    yield None


# ---------------------------------------------------------------------------
# Database Utility Class (Legacy Interface)
# ---------------------------------------------------------------------------

class Database:
    """
    Static helper class for database operations.
    
    ALL operations delegate to PostgreSQL via db_pg_models.
    NO SQLite connection.
    """
    
    @staticmethod
    def _encrypt_api_key(api_key: str) -> str:
        """Encrypt an API key."""
        from app.encryption import encryptor
        return encryptor.encrypt(api_key)
    
    @staticmethod
    def _decrypt_api_key(encrypted_key: str, is_encrypted: bool = True) -> str:
        """Decrypt an API key."""
        if not is_encrypted:
            return encrypted_key
        from app.encryption import encryptor
        try:
            return encryptor.decrypt(encrypted_key)
        except Exception:
            return "[DECRYPTION_ERROR]"
    
    # ── Profile Operations ───────────────────────────────────────────────────
    
    @staticmethod
    def get_profile() -> dict:
        """Get the user profile."""
        return _pg_get_profile()
    
    @staticmethod
    def update_profile(updates: dict) -> bool:
        """Update the user profile."""
        return _pg_update_profile(updates)
    
    @staticmethod
    def get_context() -> dict:
        """Get the user context."""
        return _pg_get_context()
    
    @staticmethod
    def update_context(context_dict: dict) -> bool:
        """Update the user context."""
        return _pg_update_context(context_dict)
    
    # ── APIKey Operations ────────────────────────────────────────────────────
    
    @staticmethod
    def get_api_keys(key_name: str | None = None) -> dict[str, str]:
        """Get API keys (decrypted)."""
        return _pg_get_api_keys(key_name)
    
    @staticmethod
    def get_api_key(key_name: str) -> str | None:
        """Get a single API key."""
        return _pg_get_api_key(key_name)
    
    @staticmethod
    def add_api_key(key_name: str, key_value: str) -> bool:
        """Add or update an API key."""
        return _pg_add_api_key(key_name, key_value)
    
    @staticmethod
    def remove_api_key(key_name: str) -> bool:
        """Remove an API key."""
        return _pg_remove_api_key(key_name)

    # ── ChatSession Operations ───────────────────────────────────────────────

    @staticmethod
    def create_session(name: str = "New Chat") -> int | None:
        """Create a new chat session."""
        return _pg_create_session(name)

    @staticmethod
    def get_active_session() -> dict:
        """Get the currently active session."""
        return _pg_get_active_session()

    @staticmethod
    def get_all_sessions() -> list[dict]:
        """Get all sessions ordered by updated_at."""
        return _pg_get_all_sessions()

    @staticmethod
    def switch_session(session_id: int) -> bool:
        """Switch to a different session."""
        return _pg_switch_session(session_id)

    @staticmethod
    def rename_session(session_id: int, new_name: str) -> bool:
        """Rename a session."""
        return _pg_rename_session(session_id, new_name)

    @staticmethod
    def delete_session(session_id: int) -> bool:
        """Delete a session."""
        return _pg_delete_session(session_id)

    @staticmethod
    def get_session_memory(session_id: int) -> dict:
        """Get session memory."""
        return _pg_get_session_memory(session_id)

    @staticmethod
    def update_session_memory(session_id: int, memory: dict) -> bool:
        """Update session memory."""
        return _pg_update_session_memory(session_id, memory)

    @staticmethod
    def increment_message_count(session_id: int) -> bool:
        """Increment the message count for a session."""
        return _pg_increment_message_count(session_id)

    # ── Message Operations ──────────────────────────────────────────────────

    @staticmethod
    def add_message(role: str, content: str, session_id: int | None = None, image_paths: str | None = None) -> int | None:
        """Add a message to a session."""
        if session_id is None:
            active_session = Database.get_active_session()
            session_id = active_session['id']
        return _pg_add_message(session_id, role, content, image_paths)

    @staticmethod
    def get_messages(session_id: int | None = None, limit: int | None = None) -> list[dict]:
        """Get messages for a session."""
        if session_id is None:
            active_session = Database.get_active_session()
            session_id = active_session['id']
        return _pg_get_session_messages(session_id, limit or 100)

    @staticmethod
    def get_chat_history(session_id: int | None = None, limit: int | None = None, recent: bool = False) -> list[dict]:
        """Get chat history for a session."""
        if session_id is None:
            active_session = Database.get_active_session()
            session_id = active_session['id']
        return _pg_get_chat_history(session_id, limit, recent)

    @staticmethod
    def clear_session(session_id: int | None = None) -> bool:
        """Clear all messages for a session."""
        if session_id is None:
            active_session = Database.get_active_session()
            session_id = active_session['id']
        return _pg_clear_session_messages(session_id)

    @staticmethod
    def clear_chat_history(session_id: int | None = None) -> bool:
        """Clear chat history (alias for clear_session)."""
        return Database.clear_session(session_id)

    @staticmethod
    def add_session_event(content: str, interface: str = "terminal") -> int | None:
        """Add a session event message."""
        active_session = Database.get_active_session()
        return _pg_add_session_event(active_session['id'], content, interface)

    @staticmethod
    def get_recent_sessions(limit: int = 20) -> list[dict]:
        """Get recent session events across all sessions."""
        return _pg_get_recent_sessions(limit)

    @staticmethod
    def get_recent_sessions_for_session(session_id: int, limit: int = 20) -> list[dict]:
        """Get recent session events for a specific session."""
        return _pg_get_recent_sessions_for_session(session_id, limit)

    @staticmethod
    def get_session_messages_count(session_id: int) -> int:
        """Get message count for a session."""
        return _pg_get_message_count(session_id)

    @staticmethod
    def get_session_conversation_summary(session_id: int, limit: int = 20) -> str:
        """Get a summary of recent conversation."""
        return _pg_get_session_conversation_summary(session_id, limit)

    @staticmethod
    def get_encryption_status() -> dict:
        """Get encryption status summary."""
        return _pg_get_encryption_status()

    @staticmethod
    def get_all_encrypted_messages() -> list[dict]:
        """Get all encrypted messages (for migration)."""
        return _pg_get_all_encrypted_messages()

    @staticmethod
    def batch_decrypt_messages(message_ids: list[int]) -> dict:
        """Batch decrypt messages."""
        return _pg_batch_decrypt_messages(message_ids)

    @staticmethod
    def get_chat_history_for_ai(session_id: int | None = None, limit: int | None = None, recent: bool = False) -> list[dict]:
        """Build message context for AI provider."""
        if session_id is None:
            active_session = Database.get_active_session()
            session_id = active_session['id']
        return _pg_get_chat_history_for_ai(session_id, limit, recent)

    @staticmethod
    def add_image_tools_message(image_url: str, session_id: int | None = None) -> int | None:
        """Add an image tools message."""
        if session_id is None:
            active_session = Database.get_active_session()
            session_id = active_session['id']
        return _pg_add_image_tools_message(session_id, image_url)

    @staticmethod
    def add_tool_result(tool_name: str, result_content: str, session_id: int | None = None) -> int | None:
        """Store tool result in database with tool-specific role."""
        if session_id is None:
            active_session = Database.get_active_session()
            session_id = active_session['id']
        return _pg_add_tool_result(session_id, tool_name, result_content)

    @staticmethod
    def add_system_note(content: str, session_id: int | None = None) -> int | None:
        """Add a system note message."""
        if session_id is None:
            active_session = Database.get_active_session()
            session_id = active_session['id']
        return _pg_add_system_note(session_id, content)

    @staticmethod
    def add_memory_note(content: str, session_id: int | None = None) -> int | None:
        """Add a memory note (alias for add_system_note)."""
        return Database.add_system_note(content, session_id)


# ---------------------------------------------------------------------------
# Backward Compatibility Exports
# ---------------------------------------------------------------------------

# These are imported by other modules
TOOL_ROLES = TOOL_ROLES
ALL_TOOL_ROLES = ALL_TOOL_ROLES

# No longer needed but kept for import compatibility
Base = None
Profile = None
ChatSession = None
Message = None
APIKey = None
SemanticMemory = None
EpisodicMemory = None
ConversationSegment = None