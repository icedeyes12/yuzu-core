# [FILE: memory/migrate_history.py]
# [DESCRIPTION: Migration script to extract memories from old message history]

from database import Database, get_db_session, Message, ChatSession
from memory.extractor import (
    extract_semantic_facts, upsert_semantic_memory, generate_episodic_summary,
    create_episodic_memory, calculate_emotional_weight,
)
from memory.segmenter import segment_session


def migrate_session(session_id, batch_size=20):
    """Scan old messages in a session and extract initial memories.

    Steps:
    1. Extract semantic facts from user messages.
    2. Create conversation segments.

    Args:
        session_id: The session to migrate.
        batch_size: Number of messages per batch for extraction.

    Returns:
        dict with counts of extracted items.
    """
    semantic_count = 0
    segment_count = 0

    # Get all user/assistant messages
    with get_db_session() as session:
        messages = session.query(Message).filter(
            Message.session_id == session_id,
            Message.role.in_(['user', 'assistant']),
        ).order_by(Message.id.asc()).all()

        msg_list = [
            {'role': m.role, 'content': m.content, 'timestamp': m.timestamp}
            for m in messages
        ]

    # Process in batches for semantic extraction
    for i in range(0, len(msg_list), batch_size):
        batch = msg_list[i:i + batch_size]
        facts = extract_semantic_facts(batch)
        for fact in facts:
            try:
                upsert_semantic_memory(
                    session_id,
                    fact['entity'],
                    fact['relation'],
                    fact['target'],
                )
                semantic_count += 1
            except Exception as e:
                print(f"[WARNING] Semantic upsert failed during migration: {e}")

    # Create segments
    try:
        segment_count = segment_session(session_id)
    except Exception as e:
        print(f"[WARNING] Segmentation failed during migration: {e}")

    return {
        'semantic_count': semantic_count,
        'segment_count': segment_count,
    }


def migrate_all_sessions():
    """Migrate all existing sessions.

    Returns:
        dict with total counts.
    """
    total_semantic = 0
    total_segments = 0

    with get_db_session() as session:
        sessions = session.query(ChatSession).all()
        session_ids = [s.id for s in sessions]

    for sid in session_ids:
        try:
            result = migrate_session(sid)
            total_semantic += result['semantic_count']
            total_segments += result['segment_count']
        except Exception as e:
            print(f"[WARNING] Session {sid} migration failed: {e}")

    return {
        'total_semantic': total_semantic,
        'total_segments': total_segments,
        'sessions_processed': len(session_ids),
    }
