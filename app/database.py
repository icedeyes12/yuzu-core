# FILE: app/database.py
# DESCRIPTION: SQLAlchemy database models and operations with FastAPI support

import json
import os
from datetime import datetime
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Text, DateTime, Float, LargeBinary, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

# SQLAlchemy setup
Base = declarative_base()

# Tool-specific role mapping: each tool gets its own dedicated message role
TOOL_ROLES = {
    'image_generate': 'image_tools',
    'imagine': 'image_tools',
    'request': 'request_tools',
}

# All tool roles for use in queries (unique values only)
ALL_TOOL_ROLES = list(set(TOOL_ROLES.values()))

class Profile(Base):
    __tablename__ = 'profiles'
    
    id = Column(Integer, primary_key=True)
    display_name = Column(String(255), nullable=False, default='bani')
    partner_name = Column(String(255), nullable=False, default='Yuzu')
    affection = Column(Integer, nullable=False, default=85)
    theme = Column(String(255), nullable=False, default='default')
    memory_json = Column(Text, nullable=False, default='{}')
    session_history_json = Column(Text, nullable=False, default='{}')
    global_knowledge_json = Column(Text, nullable=False, default='{}')
    providers_config_json = Column(Text, nullable=False, default='{}')
    context = Column(Text, nullable=False, default='{}')
    image_model = Column(String(50), nullable=False, default='hunyuan')
    vision_model = Column(String(100), nullable=False, default='moonshotai/kimi-k2.5')
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class ChatSession(Base):
    __tablename__ = 'chat_sessions'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, default='New Chat')
    is_active = Column(Boolean, nullable=False, default=False)
    message_count = Column(Integer, nullable=False, default=0)
    memory_json = Column(Text, nullable=False, default='{}')
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class Message(Base):
    __tablename__ = 'messages'
    
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, nullable=False)
    role = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    content_encrypted = Column(Boolean, nullable=False, default=False)
    timestamp = Column(String(255), nullable=False)
    image_paths = Column(Text, nullable=True)

class APIKey(Base):
    __tablename__ = 'api_keys'
    
    id = Column(Integer, primary_key=True)
    key_name = Column(String(255), nullable=False, default='openrouter')
    key_value = Column(Text, nullable=False)
    key_encrypted = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.now)

class SemanticMemory(Base):
    __tablename__ = 'semantic_memories'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, nullable=True)
    entity = Column(Text, nullable=False)
    relation = Column(Text, nullable=False)
    target = Column(Text, nullable=False)
    confidence = Column(Float, default=0.5)
    importance = Column(Float, default=0.5)
    embedding_vector = Column(LargeBinary, nullable=True)
    stability = Column(Float, default=24.0)
    difficulty = Column(Float, default=0.5)
    source_episodic_ids = Column(Text, nullable=True)
    last_accessed = Column(DateTime, nullable=True)
    access_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)

class EpisodicMemory(Base):
    __tablename__ = 'episodic_memories'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, nullable=True)
    summary = Column(Text, nullable=False)
    embedding = Column(LargeBinary, nullable=True)
    importance = Column(Float, default=0.5)
    emotional_weight = Column(Float, default=0.0)
    last_accessed = Column(DateTime, nullable=True)
    access_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)

class ConversationSegment(Base):
    __tablename__ = 'conversation_segments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, nullable=True)
    start_message_id = Column(Integer, nullable=True)
    end_message_id = Column(Integer, nullable=True)
    summary = Column(Text, nullable=True)
    embedding = Column(LargeBinary, nullable=True)
    importance = Column(Float, default=0.5)
    access_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)

# Indexes for performance
Index('idx_messages_session_id', Message.session_id)
Index('idx_messages_timestamp', Message.timestamp)
Index('idx_messages_role', Message.role)
Index('idx_chat_sessions_active', ChatSession.is_active)
Index('idx_chat_sessions_updated', ChatSession.updated_at)
Index('idx_api_keys_name', APIKey.key_name)
Index('idx_semantic_session', SemanticMemory.session_id)
Index('idx_semantic_entity', SemanticMemory.entity)
Index('idx_semantic_confidence', SemanticMemory.confidence)
Index('idx_semantic_importance', SemanticMemory.importance)
Index('idx_episodic_session', EpisodicMemory.session_id)
Index('idx_episodic_importance', EpisodicMemory.importance)
Index('idx_segments_session', ConversationSegment.session_id)

# ---------------------------------------------------------------------------
# Database Engine & Session Factory (FastAPI Compatible)
# ---------------------------------------------------------------------------

_db_path = None
_engine = None
_SessionLocal = None

def _get_db_path():
    global _db_path
    if _db_path is None:
        _db_path = os.path.join(os.path.dirname(__file__), 'yuzu_core.db')
    return _db_path

def get_engine():
    """Get or create the SQLAlchemy engine (singleton)."""
    global _engine
    if _engine is None:
        db_path = _get_db_path()
        _engine = create_engine(
            f'sqlite:///{db_path}',
            poolclass=StaticPool,
            connect_args={'check_same_thread': False}
        )
    return _engine

def get_session_factory():
    """Get or create the session factory (singleton)."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return _SessionLocal

@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Context manager for database sessions (legacy support)."""
    SessionLocal = get_session_factory()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

# ---------------------------------------------------------------------------
# FastAPI Dependency Injection
# ---------------------------------------------------------------------------

def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a database session.
    
    Usage:
        from fastapi import Depends
        from app.database import get_db
        
        @app.get("/api/items")
        def get_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    """
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------------------------------------------------------------------------
# Database Initialization
# ---------------------------------------------------------------------------

def init_db():
    """
    Initialize database with safety guards.
    
    SAFETY RULES:
    - NEVER drops tables
    - NEVER recreates database
    - Only runs safe migrations
    - Aborts if database corruption detected
    """
    db_path = _get_db_path()
    db_existed_before = os.path.exists(db_path)
    db_size_before = os.path.getsize(db_path) if db_existed_before else 0
    
    print(f"[DB INIT] Database path: {os.path.abspath(db_path)}")
    print(f"[DB INIT] File existed before: {db_existed_before}")
    print(f"[DB INIT] File size before: {db_size_before} bytes")
    
    # SAFETY CHECK: Abort if database file exists but is empty
    if db_existed_before and db_size_before == 0:
        print("[DB ERROR] Database file exists but is empty (0 bytes)")
        print("[DB ERROR] This indicates corruption. Aborting to prevent data loss.")
        raise RuntimeError("Database file corrupted (0 bytes). Check for backups or remove the file.")
    
    # Create tables if they don't exist
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    
    print("[DB INIT] Database initialized successfully")
    
    # Run migrations
    _run_migrations(engine)
    
    # Migrate API keys if needed
    with get_db_session() as session:
        migrate_api_keys_from_files(session)


def _run_migrations(engine):
    """Run all pending migrations."""
    from sqlalchemy import inspect as sa_inspect, text
    
    inspector = sa_inspect(engine)
    
    # Migration: Add context column to profiles
    columns = [col['name'] for col in inspector.get_columns('profiles')]
    if 'context' not in columns:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE profiles ADD COLUMN context TEXT DEFAULT '{}'"))
            conn.commit()
    
    # Migration: Add image_paths column to messages
    columns = [col['name'] for col in inspector.get_columns('messages')]
    if 'image_paths' not in columns:
        with engine.connect() as conn:
            conn.execute(text('ALTER TABLE messages ADD COLUMN image_paths TEXT'))
            conn.commit()
    
    # Migration: Add image_model column to profiles
    if 'image_model' not in [col['name'] for col in inspector.get_columns('profiles')]:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE profiles ADD COLUMN image_model TEXT DEFAULT 'hunyuan'"))
            conn.commit()
    
    # Migration: Add vision_model column to profiles
    if 'vision_model' not in [col['name'] for col in inspector.get_columns('profiles')]:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE profiles ADD COLUMN vision_model TEXT DEFAULT 'moonshotai/kimi-k2.5'"))
            conn.commit()
    
    # Migration: Add embedding_vector to semantic_memories
    if 'embedding_vector' not in [col['name'] for col in inspector.get_columns('semantic_memories')]:
        with engine.connect() as conn:
            conn.execute(text('ALTER TABLE semantic_memories ADD COLUMN embedding_vector BLOB'))
            conn.commit()
    
    # Migration: Add source_episodic_ids, stability, difficulty
    columns = [col['name'] for col in inspector.get_columns('semantic_memories')]
    if 'source_episodic_ids' not in columns:
        with engine.connect() as conn:
            conn.execute(text('ALTER TABLE semantic_memories ADD COLUMN source_episodic_ids TEXT'))
            conn.commit()
    if 'stability' not in columns:
        with engine.connect() as conn:
            conn.execute(text('ALTER TABLE semantic_memories ADD COLUMN stability FLOAT DEFAULT 24.0'))
            conn.commit()
    if 'difficulty' not in columns:
        with engine.connect() as conn:
            conn.execute(text('ALTER TABLE semantic_memories ADD COLUMN difficulty FLOAT DEFAULT 0.5'))
            conn.commit()


def migrate_api_keys_from_files(session):
    """Migrate API keys from various key files to database"""
    key_files = {
        'ce.key': 'cerebras',
        'cu.key': 'chutes',
        'or.key': 'openrouter'
    }
    migrated_count = 0
    
    for key_file, key_name in key_files.items():
        if os.path.exists(key_file):
            try:
                with open(key_file, 'r') as f:
                    api_key = f.read().strip()
                
                if api_key:
                    existing_key = session.query(APIKey).filter_by(key_name=key_name).first()
                    if not existing_key:
                        encrypted_key = Database._encrypt_api_key(api_key)
                        new_api_key = APIKey(
                            key_name=key_name,
                            key_value=encrypted_key,
                            key_encrypted=True
                        )
                        session.add(new_api_key)
                        
                        # Create backup of original file
                        backup_file = f"{key_file}.backup"
                        os.rename(key_file, backup_file)
                        
                        migrated_count += 1
                        
            except Exception:
                pass
    
    session.commit()
    return migrated_count



# ---------------------------------------------------------------------------
# Database Utility Class
# ---------------------------------------------------------------------------

class Database:
    """Static helper class for common database operations."""
    
    @staticmethod
    def _encrypt_api_key(api_key):
        """Encrypt an API key."""
        from app.encryption import encryptor
        return encryptor.encrypt(api_key)
    
    @staticmethod
    def _decrypt_api_key(encrypted_key, is_encrypted=True):
        """Decrypt an API key."""
        if not is_encrypted:
            return encrypted_key
        from app.encryption import encryptor
        try:
            return encryptor.decrypt(encrypted_key)
        except Exception:
            return "[DECRYPTION_ERROR]"
    
    @staticmethod
    def get_profile():
        """Get the user profile."""
        with get_db_session() as session:
            profile = session.query(Profile).first()
            if not profile:
                profile = Profile()
                session.add(profile)
                session.commit()
                session.refresh(profile)
            
            return {
                'id': profile.id,
                'display_name': profile.display_name,
                'partner_name': profile.partner_name,
                'affection': profile.affection,
                'theme': profile.theme,
                'memory': json.loads(profile.memory_json),
                'session_history': json.loads(profile.session_history_json),
                'global_knowledge': json.loads(profile.global_knowledge_json),
                'providers_config': json.loads(profile.providers_config_json),
                'context': json.loads(profile.context),
                'image_model': profile.image_model,
                'vision_model': profile.vision_model,
                'created_at': profile.created_at,
                'updated_at': profile.updated_at
            }
    
    @staticmethod
    def update_profile(updates):
        """Update the user profile."""
        with get_db_session() as session:
            profile = session.query(Profile).first()
            if not profile:
                return
            
            for key, value in updates.items():
                if hasattr(profile, key):
                    setattr(profile, key, value)
                elif key == 'memory':
                    profile.memory_json = json.dumps(value)
                elif key == 'session_history':
                    profile.session_history_json = json.dumps(value)
                elif key == 'global_knowledge':
                    profile.global_knowledge_json = json.dumps(value)
                elif key == 'providers_config':
                    profile.providers_config_json = json.dumps(value)
                elif key == 'context':
                    profile.context = json.dumps(value)
            
            profile.updated_at = datetime.now()
            session.commit()
    
    @staticmethod
    def get_context():
        """Get the user context."""
        with get_db_session() as session:
            profile = session.query(Profile).first()
            if profile:
                try:
                    return json.loads(profile.context or '{}')
                except (json.JSONDecodeError, TypeError):
                    return {}
            return {}
    
    @staticmethod
    def update_context(context_dict):
        """Update the user context."""
        with get_db_session() as session:
            profile = session.query(Profile).first()
            if not profile:
                return
            profile.context = json.dumps(context_dict)
            profile.updated_at = datetime.now()
            session.commit()
    
    @staticmethod
    def get_api_keys(key_name=None):
        """Get API keys (decrypted)."""
        with get_db_session() as session:
            query = session.query(APIKey)
            if key_name:
                query = query.filter(APIKey.key_name == key_name)
            
            keys = query.all()
            decrypted_keys = {}
            
            for key in keys:
                if key.key_encrypted:
                    decrypted_key = Database._decrypt_api_key(key.key_value, True)
                    if decrypted_key != "[DECRYPTION_ERROR]":
                        decrypted_keys[key.key_name] = decrypted_key
                else:
                    decrypted_keys[key.key_name] = key.key_value
            
            return decrypted_keys
    
    @staticmethod
    def get_api_key(key_name):
        """Get a single API key."""
        keys = Database.get_api_keys(key_name)
        return keys.get(key_name)
    
    @staticmethod
    def add_api_key(key_name, key_value):
        """Add or update an API key."""
        with get_db_session() as session:
            encrypted_key = Database._encrypt_api_key(key_value)
            is_encrypted = encrypted_key != key_value
            
            existing = session.query(APIKey).filter(APIKey.key_name == key_name).first()
            if existing:
                existing.key_value = encrypted_key
                existing.key_encrypted = is_encrypted
            else:
                new_key = APIKey(
                    key_name=key_name,
                    key_value=encrypted_key,
                    key_encrypted=is_encrypted
                )
                session.add(new_key)
            
            session.commit()
            return True
    
    @staticmethod
    def remove_api_key(key_name):
        """Remove an API key."""
        with get_db_session() as session:
            deleted = session.query(APIKey).filter(APIKey.key_name == key_name).delete()
            session.commit()
            return deleted > 0


    @staticmethod
    def create_session(name="New Chat"):
        """Create a new chat session."""
        with get_db_session() as session:
            chat_session = ChatSession(
                name=name,
                is_active=False
            )
            session.add(chat_session)
            session.commit()
            return chat_session.id

    @staticmethod
    def get_active_session():
        """Get the currently active session."""
        with get_db_session() as session:
            active_session = session.query(ChatSession).filter_by(is_active=True).first()
            
            if not active_session:
                active_session = ChatSession(
                    name='New Chat',
                    is_active=True
                )
                session.add(active_session)
                session.commit()
            
            return {
                'id': active_session.id,
                'name': active_session.name,
                'is_active': active_session.is_active,
                'message_count': active_session.message_count,
                'memory': json.loads(active_session.memory_json),
                'created_at': active_session.created_at,
                'updated_at': active_session.updated_at
            }

    @staticmethod
    def get_all_sessions():
        """Get all sessions ordered by updated_at."""
        with get_db_session() as session:
            sessions = session.query(ChatSession).order_by(ChatSession.updated_at.desc()).all()
            return [{
                'id': s.id,
                'name': s.name,
                'is_active': s.is_active,
                'message_count': s.message_count,
                'memory': json.loads(s.memory_json),
                'created_at': s.created_at,
                'updated_at': s.updated_at
            } for s in sessions]

    @staticmethod
    def switch_session(session_id):
        """Switch to a different session."""
        with get_db_session() as session:
            session.query(ChatSession).update({'is_active': False})
            
            target = session.query(ChatSession).filter_by(id=session_id).first()
            if target:
                target.is_active = True
                target.updated_at = datetime.now()
                session.commit()
                return True
            return False

    @staticmethod
    def rename_session(session_id, new_name):
        """Rename a session."""
        with get_db_session() as session:
            chat_session = session.query(ChatSession).filter_by(id=session_id).first()
            if chat_session:
                chat_session.name = new_name
                chat_session.updated_at = datetime.now()
                session.commit()
                return True
            return False

    @staticmethod
    def delete_session(session_id):
        """Delete a session."""
        with get_db_session() as session:
            chat_session = session.query(ChatSession).filter_by(id=session_id).first()
            if not chat_session:
                return False
            
            was_active = chat_session.is_active
            session.delete(chat_session)
            
            if was_active:
                new_active = session.query(ChatSession).order_by(ChatSession.updated_at.desc()).first()
                if new_active:
                    new_active.is_active = True
            
            session.commit()
            return True

    @staticmethod
    def get_session_memory(session_id):
        """Get session memory."""
        with get_db_session() as session:
            chat_session = session.query(ChatSession).filter_by(id=session_id).first()
            if chat_session:
                return json.loads(chat_session.memory_json)
            return {
                'session_context': '',
                'last_summarized': 'Never',
                'last_summary_count': 0,
                'last_message_time': None
            }

    @staticmethod
    def update_session_memory(session_id, memory_update):
        """Update session memory."""
        with get_db_session() as session:
            chat_session = session.query(ChatSession).filter_by(id=session_id).first()
            if chat_session:
                current_memory = json.loads(chat_session.memory_json)
                current_memory.update(memory_update)
                chat_session.memory_json = json.dumps(current_memory)
                session.commit()
                return True
            return False

    @staticmethod
    def add_message(role, content, session_id=None, timestamp=None, image_paths=None):
        """Add a message to the conversation."""
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if session_id is None:
            active_session = Database.get_active_session()
            session_id = active_session['id']
        
        with get_db_session() as session:
            new_message = Message(
                session_id=session_id,
                role=role,
                content=content,
                timestamp=timestamp
            )
            if image_paths:
                new_message.image_paths = json.dumps(image_paths)
            
            session.add(new_message)
            
            # Update session message count
            chat_session = session.query(ChatSession).filter_by(id=session_id).first()
            if chat_session:
                chat_session.message_count += 1
                chat_session.updated_at = datetime.now()
            
            session.commit()
            return new_message.id

    @staticmethod
    def get_chat_history(session_id=None, limit=1000, recent=False):
        """Get chat history for a session."""
        if session_id is None:
            active_session = Database.get_active_session()
            session_id = active_session['id']
        
        with get_db_session() as session:
            query = session.query(Message).filter_by(session_id=session_id)
            
            if recent and limit:
                messages = query.order_by(Message.timestamp.desc()).limit(limit).all()
                messages = list(reversed(messages))
            elif limit:
                messages = query.order_by(Message.timestamp.asc()).limit(limit).all()
            else:
                messages = query.order_by(Message.timestamp.asc()).all()
            
            return [{
                'id': m.id,
                'role': m.role,
                'content': m.content,
                'timestamp': m.timestamp,
                'image_paths': json.loads(m.image_paths) if m.image_paths else None
            } for m in messages if m.role in ['user', 'assistant', 'system']]

    @staticmethod
    def clear_chat_history(session_id=None):
        """Clear chat history for a session."""
        if session_id is None:
            active_session = Database.get_active_session()
            session_id = active_session['id']
        
        with get_db_session() as session:
            session.query(Message).filter_by(session_id=session_id).delete()
            
            chat_session = session.query(ChatSession).filter_by(id=session_id).first()
            if chat_session:
                chat_session.message_count = 0
                chat_session.memory_json = '{}'
                chat_session.updated_at = datetime.now()
            
            session.commit()
