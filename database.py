# [FILE: database.py]
# [VERSION: 2.1]
# [DATE: 2026-01-06]
# [PROJECT: HKKM - Yuzu Companion]
# [DESCRIPTION: SQLAlchemy database]
# [AUTHOR: Project Lead: Bani Baskara]
# [TEAM: Deepseek, GPT, Qwen, Aihara]
# [REPOSITORY: https://guthib.com/icedeyes12]
# [LICENSE: MIT]

import json
import os
import hashlib
from datetime import datetime
from contextlib import contextmanager
from encryption import encryptor
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Text, DateTime, Float, LargeBinary, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.pool import StaticPool

# SQLAlchemy setup
Base = declarative_base()

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
    content_encrypted = Column(Boolean, nullable=False, default=False)  # Kept for compatibility
    timestamp = Column(String(255), nullable=False)
    image_paths = Column(Text, nullable=True)  # JSON list of cached image paths

class APIKey(Base):
    __tablename__ = 'api_keys'
    
    id = Column(Integer, primary_key=True)
    key_name = Column(String(255), nullable=False, default='openrouter')
    key_value = Column(Text, nullable=False)
    key_encrypted = Column(Boolean, nullable=False, default=True)  # API keys tetap terenkripsi
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
Index('idx_episodic_session', EpisodicMemory.session_id)
Index('idx_episodic_importance', EpisodicMemory.importance)
Index('idx_segments_session', ConversationSegment.session_id)

def get_db_path():
    return os.path.join(os.path.dirname(__file__), 'yuzu_core.db')

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
                    # Check if key already exists in database
                    existing_key = session.query(APIKey).filter_by(key_name=key_name).first()
                    
                    if existing_key:
                        pass
                    else:
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
                        
            except Exception as e:
                pass
    
    return migrated_count

def _migrate_add_context_column(engine):
    """Add context column to profiles table if it does not exist."""
    from sqlalchemy import inspect as sa_inspect, text
    inspector = sa_inspect(engine)
    columns = [col['name'] for col in inspector.get_columns('profiles')]
    if 'context' not in columns:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE profiles ADD COLUMN context TEXT DEFAULT '{}'"))
            conn.commit()

def _migrate_add_image_paths_column(engine):
    """Add image_paths column to messages table if it does not exist."""
    from sqlalchemy import inspect as sa_inspect, text
    inspector = sa_inspect(engine)
    columns = [col['name'] for col in inspector.get_columns('messages')]
    if 'image_paths' not in columns:
        with engine.connect() as conn:
            conn.execute(text('ALTER TABLE messages ADD COLUMN image_paths TEXT'))
            conn.commit()

def _migrate_add_image_model_column(engine):
    """Add image_model column to profiles table if it does not exist."""
    from sqlalchemy import inspect as sa_inspect, text
    inspector = sa_inspect(engine)
    columns = [col['name'] for col in inspector.get_columns('profiles')]
    if 'image_model' not in columns:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE profiles ADD COLUMN image_model TEXT DEFAULT 'hunyuan'"))
            conn.commit()

def _migrate_add_vision_model_column(engine):
    """Add vision_model column to profiles table if it does not exist."""
    from sqlalchemy import inspect as sa_inspect, text
    inspector = sa_inspect(engine)
    columns = [col['name'] for col in inspector.get_columns('profiles')]
    if 'vision_model' not in columns:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE profiles ADD COLUMN vision_model TEXT DEFAULT 'moonshotai/kimi-k2.5'"))
            conn.commit()

def init_db():
    """
    Initialize database with safety guards.
    
    SAFETY RULES:
    - NEVER drops tables
    - NEVER recreates database
    - Only runs safe migrations
    - Aborts if database corruption detected
    """
    db_path = get_db_path()
    db_existed_before = os.path.exists(db_path)
    db_size_before = os.path.getsize(db_path) if db_existed_before else 0
    
    print(f"[DB INIT] Database path: {os.path.abspath(db_path)}")
    print(f"[DB INIT] File existed before: {db_existed_before}")
    print(f"[DB INIT] File size before: {db_size_before} bytes")
    
    # SAFETY CHECK: Abort if database file exists but is empty
    if db_existed_before and db_size_before == 0:
        print("[DB ERROR] Database file exists but is empty (0 bytes)")
        print("[DB ERROR] This indicates corruption. Aborting to prevent data loss.")
        print("[DB ERROR] To recover:")
        print("[DB ERROR]   1. Check for backup files (*.db.backup)")
        print(f"[DB ERROR]   2. Remove corrupted file: rm {db_path}")
        print("[DB ERROR]   3. Restore from backup if available")
        print("[DB ERROR]   4. Or restart with fresh database")
        raise RuntimeError("Database file corrupted (0 bytes). Manual intervention required.")
    
    engine = get_engine()
    
    # Check table count before operations
    from sqlalchemy import inspect as sa_inspect
    inspector = sa_inspect(engine)
    tables_before = inspector.get_table_names()
    table_count_before = len(tables_before)
    
    print(f"[DB INIT] Tables before: {table_count_before}")
    if db_existed_before and table_count_before == 0:
        print("[DB CRITICAL] Database file existed but contains no tables")
        print("[DB CRITICAL] This may indicate data loss or corruption")
    
    # SAFE OPERATION: Only creates tables that don't exist
    Base.metadata.create_all(engine)
    
    # Migrate existing databases: add image_paths column if missing
    try:
        _migrate_add_image_paths_column(engine)
    except Exception as e:
        print(f"[WARNING] image_paths migration skipped: {e}")
    
    # Migrate existing databases: add context column if missing
    try:
        _migrate_add_context_column(engine)
    except Exception as e:
        print(f"[WARNING] context migration skipped: {e}")
    
    # Migrate existing databases: add image_model column if missing
    try:
        _migrate_add_image_model_column(engine)
    except Exception as e:
        print(f"[WARNING] image_model migration skipped: {e}")
    
    # Migrate existing databases: add vision_model column if missing
    try:
        _migrate_add_vision_model_column(engine)
    except Exception as e:
        print(f"[WARNING] vision_model migration skipped: {e}")
    
    with get_db_session() as session:
        # Create default profile and session if needed
        if session.query(Profile).count() == 0:
            profile = Profile(
                display_name='user',
                partner_name='Yuzu', 
                affection=50,
                providers_config_json=json.dumps({
                    'preferred_provider': 'ollama',
                    'preferred_model': 'glm-4.6:cloud',
                    'providers': {
                        'ollama': {'enabled': True, 'base_url': 'http://127.0.0.1:11434'},
                        'cerebras': {'enabled': True},
                        'openrouter': {'enabled': True},
                        'chutes': {'enabled': True}
                    }
                })
            )
            session.add(profile)
            
            chat_session = ChatSession(
                name='New Chat',
                is_active=True
            )
            session.add(chat_session)
            
            # Migrate API keys from files
            migrate_api_keys_from_files(session)
            
            session.commit()
    
    # AUDIT LOG: Report final state
    with get_db_session() as session:
        profile_count = session.query(Profile).count()
        session_count = session.query(ChatSession).count()
        message_count = session.query(Message).count()
        apikey_count = session.query(APIKey).count()
        
        print(f"[DB AUDIT] Database initialization complete")
        print(f"[DB AUDIT] Profiles: {profile_count}")
        print(f"[DB AUDIT] Chat Sessions: {session_count}")
        print(f"[DB AUDIT] Messages: {message_count}")
        print(f"[DB AUDIT] API Keys: {apikey_count}")
        
        db_size_after = os.path.getsize(db_path)
        print(f"[DB AUDIT] File size after: {db_size_after} bytes")

# Database engine and session management
_engine = None
_SessionLocal = None

def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            f'sqlite:///{get_db_path()}',
            poolclass=StaticPool,
            connect_args={'check_same_thread': False},
            echo=False
        )
    return _engine

def get_session_local():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal

@contextmanager
def get_db_session():
    session = get_session_local()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def verify_password(stored_password, provided_password):
    return stored_password == hashlib.sha256(provided_password.encode('utf-8')).hexdigest()

class Database:
    @staticmethod
    def _encrypt_content(content):
        """
        DEPRECATED: Tidak lagi mengenkripsi pesan
        Hanya untuk backward compatibility
        """
        return content  # Return as-is, no encryption

    @staticmethod
    def _decrypt_content(content, is_encrypted):
        """
        DEPRECATED: Tidak perlu dekripsi pesan
        Hanya untuk backward compatibility
        """
        return content  # Return as-is, no decryption needed
    
    @staticmethod
    def _encrypt_api_key(key_value):
        """Hanya API key yang tetap terenkripsi"""
        try:
            return encryptor.encrypt(key_value)
        except Exception as e:
            print(f"[WARNING] API key encryption failed: {e}")
            return key_value
    
    @staticmethod
    def _decrypt_api_key(key_value, is_encrypted):
        """Dekripsi hanya untuk API key"""
        if not is_encrypted:
            return key_value
        
        try:
            return encryptor.decrypt(key_value)
        except Exception as e:
            print(f"[ERROR] API key decryption failed: {e}")
            return "[DECRYPTION_ERROR]"

    @staticmethod
    def get_profile():
        with get_db_session() as session:
            profile = session.query(Profile).first()
            if profile:
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
                    'context': json.loads(profile.context or '{}'),
                    'image_model': profile.image_model or 'hunyuan',
                    'vision_model': profile.vision_model if hasattr(profile, 'vision_model') and profile.vision_model else 'moonshotai/kimi-k2.5',
                    'created_at': profile.created_at,
                    'updated_at': profile.updated_at
                }
            return None

    @staticmethod
    def update_profile(updates):
        with get_db_session() as session:
            profile = session.query(Profile).first()
            if not profile:
                return
            
            for key, value in updates.items():
                if key in ['memory', 'session_history', 'global_knowledge', 'providers_config']:
                    setattr(profile, f"{key}_json", json.dumps(value))
                elif key == 'context':
                    setattr(profile, 'context', json.dumps(value))
                else:
                    setattr(profile, key, value)
            
            profile.updated_at = datetime.now()
            session.commit()

    @staticmethod
    def get_context():
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
        with get_db_session() as session:
            profile = session.query(Profile).first()
            if not profile:
                return
            profile.context = json.dumps(context_dict)
            profile.updated_at = datetime.now()
            session.commit()

    @staticmethod
    def get_api_keys(key_name=None):
        with get_db_session() as session:
            query = session.query(APIKey)
            if key_name:
                query = query.filter(APIKey.key_name == key_name)
            
            keys = query.all()
            decrypted_keys = {}
            
            for key in keys:
                # Hanya decrypt jika ini API key (bukan pesan)
                if key.key_encrypted:
                    decrypted_key = Database._decrypt_api_key(key.key_value, True)
                    if decrypted_key != "[DECRYPTION_ERROR]":
                        decrypted_keys[key.key_name] = decrypted_key
                else:
                    decrypted_keys[key.key_name] = key.key_value
            
            return decrypted_keys

    @staticmethod
    def get_api_key(key_name):
        keys = Database.get_api_keys(key_name)
        return keys.get(key_name)

    @staticmethod
    def add_api_key(key_name, key_value):
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
        with get_db_session() as session:
            deleted = session.query(APIKey).filter(APIKey.key_name == key_name).delete()
            session.commit()
            return deleted > 0

    @staticmethod
    def create_session(name="New Chat"):
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
        with get_db_session() as session:
            sessions = session.query(ChatSession).order_by(ChatSession.updated_at.desc()).all()
            result = []
            
            for session_obj in sessions:
                result.append({
                    'id': session_obj.id,
                    'name': session_obj.name,
                    'is_active': session_obj.is_active,
                    'message_count': session_obj.message_count,
                    'memory': json.loads(session_obj.memory_json),
                    'created_at': session_obj.created_at,
                    'updated_at': session_obj.updated_at
                })
            
            return result

    @staticmethod
    def switch_session(session_id):
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
        with get_db_session() as session:
            chat_session = session.query(ChatSession).filter_by(id=session_id).first()
            if chat_session and chat_session.memory_json:
                try:
                    return json.loads(chat_session.memory_json)
                except json.JSONDecodeError:
                    return {}
            return {}

    @staticmethod
    def update_session_memory(session_id, memory_data):
        with get_db_session() as session:
            chat_session = session.query(ChatSession).filter_by(id=session_id).first()
            if chat_session:
                chat_session.memory_json = json.dumps(memory_data)
                chat_session.updated_at = datetime.now()
                session.commit()

    @staticmethod
    def add_message(role, content, session_id=None, image_paths=None):
        if session_id is None:
            active_session = Database.get_active_session()
            session_id = active_session['id']
        
        with get_db_session() as session:
            local_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # TIDAK LAGI mengenkripsi pesan, simpan langsung
            message = Message(
                session_id=session_id,
                role=role,
                content=content,  # Langsung simpan tanpa enkripsi
                content_encrypted=False,  # Selalu False untuk pesan baru
                timestamp=local_time,
                image_paths=json.dumps(image_paths) if image_paths else None
            )
            session.add(message)
            
            # Update session message count
            chat_session = session.query(ChatSession).filter_by(id=session_id).first()
            if chat_session and role in ['user', 'assistant']:
                chat_session.message_count += 1
                chat_session.updated_at = datetime.now()
            
            session.commit()

    @staticmethod
    def add_image_tools_message(image_url, session_id=None):
        if session_id is None:
            active_session = Database.get_active_session()
            session_id = active_session['id']
        
        with get_db_session() as session:
            local_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            message = Message(
                session_id=session_id,
                role='image_tools',
                content=image_url,
                content_encrypted=False,
                timestamp=local_time
            )
            session.add(message)
            session.commit()

    @staticmethod
    def add_tool_result(tool_name, result_content, session_id=None):
        """
        Store formatted tool result in database.
        
        Args:
            tool_name (str): Name of the tool that was executed
            result_content (str): Raw result content from tool execution
            session_id (int, optional): Session ID. Defaults to active session if None.
        """
        if session_id is None:
            active_session = Database.get_active_session()
            session_id = active_session['id']
        
        with get_db_session() as session:
            local_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Format tool result
            formatted_content = f"🔧 TOOL RESULT — {tool_name.upper()}\n\n{result_content}\n\n---"
            
            message = Message(
                session_id=session_id,
                role='tool',
                content=formatted_content,
                content_encrypted=False,
                timestamp=local_time
            )
            session.add(message)
            session.commit()

    @staticmethod
    def add_system_note(content, session_id=None):
        if session_id is None:
            active_session = Database.get_active_session()
            session_id = active_session['id']
        
        with get_db_session() as session:
            local_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            message = Message(
                session_id=session_id,
                role='system',
                content=content,
                content_encrypted=False,
                timestamp=local_time
            )
            session.add(message)
            session.commit()

    @staticmethod
    def add_memory_note(content, session_id=None):
        Database.add_system_note(content, session_id)
        
    @staticmethod
    def get_chat_history(session_id=None, limit=None, recent=False):
        if session_id is None:
            active_session = Database.get_active_session()
            session_id = active_session['id']
        
        with get_db_session() as session:
            query = session.query(Message).filter(
                Message.session_id == session_id,
                Message.role.in_(['user', 'assistant', 'image_tools'])
            )
            
            if recent and limit:
                messages = query.order_by(Message.timestamp.desc()).limit(limit).all()
                messages = list(reversed(messages))
            elif limit:
                messages = query.order_by(Message.timestamp.asc()).limit(limit).all()
            else:
                messages = query.order_by(Message.timestamp.asc()).all()
            
            # Tidak perlu dekripsi karena pesan tidak terenkripsi
            result_messages = []
            for msg in messages:
                # Untuk pesan lama yang masih terenkripsi (backward compatibility)
                content = msg.content
                if msg.content_encrypted:
                    # Coba dekripsi jika masih terenkripsi (legacy data)
                    try:
                        content = encryptor.decrypt(content)
                    except:
                        content = "[ENCRYPTED_LEGACY_DATA]"
                
                result_messages.append({
                    'role': msg.role,
                    'content': content,
                    'timestamp': msg.timestamp,
                    'image_paths': json.loads(msg.image_paths) if msg.image_paths else []
                })
            
            return result_messages

    @staticmethod
    def get_chat_history_for_ai(session_id=None, limit=None, recent=False):
        if session_id is None:
            active_session = Database.get_active_session()
            session_id = active_session['id']
        
        with get_db_session() as session:
            query = session.query(Message).filter(
                Message.session_id == session_id,
                Message.role.in_(['user', 'assistant', 'system'])
            )
            
            if recent and limit:
                messages = query.order_by(Message.timestamp.desc()).limit(limit).all()
                messages = list(reversed(messages))
            elif limit:
                messages = query.order_by(Message.timestamp.asc()).limit(limit).all()
            else:
                messages = query.order_by(Message.timestamp.asc()).all()
            
            formatted_messages = []
            for msg in messages:
                # Ambil content tanpa enkripsi
                content = msg.content
                if msg.content_encrypted:
                    # Legacy: coba dekripsi jika masih terenkripsi
                    try:
                        content = encryptor.decrypt(content)
                    except:
                        content = "[ENCRYPTED_LEGACY_DATA]"
                
                # Format timestamp
                try:
                    dt = datetime.strptime(msg.timestamp, '%Y-%m-%d %H:%M:%S')
                    formatted_timestamp = dt.strftime('[%Y-%m-%d %H:%M:%S]')
                except:
                    formatted_timestamp = f"[{msg.timestamp}]"
                
                # Format untuk AI (tambahkan timestamp untuk pesan user)
                if msg.role == 'user':
                    ai_formatted_content = f"{content} {formatted_timestamp}"
                else:
                    ai_formatted_content = content
                
                formatted_messages.append({
                    'role': msg.role,
                    'content': ai_formatted_content,
                    'original_content': content,
                    'timestamp': msg.timestamp
                })
            
            return formatted_messages

    @staticmethod
    def clear_chat_history(session_id=None):
        if session_id is None:
            active_session = Database.get_active_session()
            session_id = active_session['id']
        
        with get_db_session() as session:
            session.query(Message).filter(Message.session_id == session_id).delete()
            
            chat_session = session.query(ChatSession).filter_by(id=session_id).first()
            if chat_session:
                chat_session.message_count = 0
                chat_session.updated_at = datetime.now()
            
            session.commit()

    @staticmethod
    def add_session_event(content, interface="terminal"):
        active_session = Database.get_active_session()
        session_id = active_session['id']
        
        event_content = f"*{content} on {interface}*"
        Database.add_message('system', event_content, session_id)

    @staticmethod
    def get_recent_sessions(limit=20):
        with get_db_session() as session:
            messages = session.query(Message).filter(
                Message.role == 'system',
                Message.content.like('*%')
            ).order_by(Message.timestamp.desc()).limit(limit).all()
            
            events = []
            for msg in messages:
                content = msg.content
                if msg.content_encrypted:
                    try:
                        content = encryptor.decrypt(content)
                    except:
                        content = "[ENCRYPTED_LEGACY_DATA]"
                
                events.append({
                    'content': content,
                    'timestamp': msg.timestamp
                })
            
            return events

    @staticmethod
    def get_recent_sessions_for_session(session_id, limit=20):
        with get_db_session() as session:
            messages = session.query(Message).filter(
                Message.role == 'system',
                Message.session_id == session_id,
                Message.content.like('*%')
            ).order_by(Message.timestamp.desc()).limit(limit).all()
            
            events = []
            for msg in messages:
                content = msg.content
                if msg.content_encrypted:
                    try:
                        content = encryptor.decrypt(content)
                    except:
                        content = "[ENCRYPTED_LEGACY_DATA]"
                
                events.append({
                    'content': content,
                    'timestamp': msg.timestamp
                })
            
            return events

    @staticmethod
    def get_session_messages_count(session_id):
        with get_db_session() as session:
            count = session.query(Message).filter(
                Message.session_id == session_id,
                Message.role.in_(['user', 'assistant'])
            ).count()
            return count

    @staticmethod
    def get_session_conversation_summary(session_id, limit=20):
        with get_db_session() as session:
            messages = session.query(Message).filter(
                Message.session_id == session_id,
                Message.role.in_(['user', 'assistant'])
            ).order_by(Message.timestamp.asc()).limit(limit).all()
            
            summary_parts = []
            for msg in messages:
                role_label = "User" if msg.role == 'user' else "AI"
                content = msg.content
                
                # Handle legacy encrypted data
                if msg.content_encrypted:
                    try:
                        content = encryptor.decrypt(content)
                    except:
                        content = "[ENCRYPTED_DATA]"
                
                # Truncate if too long
                content = content[:100]
                if len(msg.content) > 100:
                    content += "..."
                
                summary_parts.append(f"{role_label}: {content}")
            
            return "\n".join(summary_parts)

    @staticmethod
    def get_encryption_status():
        with get_db_session() as session:
            total_messages = session.query(Message).count()
            encrypted_messages = session.query(Message).filter(Message.content_encrypted == True).count()
            
            total_keys = session.query(APIKey).count()
            encrypted_keys = session.query(APIKey).filter(APIKey.key_encrypted == True).count()
            
            return {
                'messages': {
                    'total_messages': total_messages,
                    'encrypted_messages': encrypted_messages,
                    'encryption_policy': 'NO_ENCRYPTION'  # Policy baru
                },
                'api_keys': {
                    'total_keys': total_keys,
                    'encrypted_keys': encrypted_keys,
                    'encryption_policy': 'FULL_ENCRYPTION'  # API key tetap terenkripsi
                },
                'summary': {
                    'message_encryption': 'DISABLED',
                    'api_key_encryption': 'ENABLED',
                    'legacy_encrypted_messages': encrypted_messages
                }
            }

    @staticmethod
    def get_all_encrypted_messages():
        """Get all messages that are still encrypted (for migration purposes)"""
        with get_db_session() as session:
            messages = session.query(Message).filter(Message.content_encrypted == True).all()
            
            result = []
            for msg in messages:
                result.append({
                    'id': msg.id,
                    'session_id': msg.session_id,
                    'role': msg.role,
                    'content': msg.content,
                    'timestamp': msg.timestamp
                })
            
            return result

    @staticmethod
    def batch_decrypt_messages(message_ids):
        """Batch decrypt messages (for migration tool)"""
        decrypted_count = 0
        failed_count = 0
        
        with get_db_session() as session:
            for msg_id in message_ids:
                try:
                    msg = session.query(Message).filter(Message.id == msg_id).first()
                    if msg and msg.content_encrypted:
                        # Decrypt the content
                        decrypted_content = encryptor.decrypt(msg.content)
                        
                        # Update the message
                        msg.content = decrypted_content
                        msg.content_encrypted = False
                        
                        decrypted_count += 1
                        
                        # Commit every 100 messages
                        if decrypted_count % 100 == 0:
                            session.commit()
                            
                except Exception as e:
                    failed_count += 1
                    print(f"Failed to decrypt message {msg_id}: {e}")
                    continue
            
            # Final commit
            session.commit()
        
        return {
            'decrypted': decrypted_count,
            'failed': failed_count,
            'total': len(message_ids)
        }

# Initialize database
init_db()