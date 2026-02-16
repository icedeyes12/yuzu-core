# [FILE: memory/review.py]
# [DESCRIPTION: FSRS-style review and decay system for memory]

import math
from datetime import datetime
from database import get_db_session, SemanticMemory, EpisodicMemory


def _hours_since(dt):
    """Calculate hours since a given datetime."""
    if not dt:
        return 720.0  # Default: 30 days
    now = datetime.now()
    if isinstance(dt, str):
        try:
            dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            return 720.0
    return max((now - dt).total_seconds() / 3600.0, 0.0)


def decay_semantic_memories(session_id=None):
    """Apply decay to semantic memories.

    importance *= exp(-time_since_last_access / stability)

    Stability is derived from access_count (more access = more stable).
    """
    with get_db_session() as session:
        query = session.query(SemanticMemory)
        if session_id is not None:
            query = query.filter(SemanticMemory.session_id == session_id)
        memories = query.all()

        for mem in memories:
            hours = _hours_since(mem.last_accessed)
            # Stability: higher access count = higher stability
            stability = max(24.0 * (1 + (mem.access_count or 0) * 0.5), 24.0)
            decay_factor = math.exp(-hours / stability)
            mem.importance = max((mem.importance or 0.5) * decay_factor, 0.01)

        session.commit()


def decay_episodic_memories(session_id=None):
    """Apply decay to episodic memories.

    importance *= exp(-time_since_last_access / stability)
    """
    with get_db_session() as session:
        query = session.query(EpisodicMemory)
        if session_id is not None:
            query = query.filter(EpisodicMemory.session_id == session_id)
        memories = query.all()

        for mem in memories:
            hours = _hours_since(mem.last_accessed)
            stability = max(48.0 * (1 + (mem.access_count or 0) * 0.3), 48.0)
            decay_factor = math.exp(-hours / stability)
            mem.importance = max((mem.importance or 0.5) * decay_factor, 0.01)

        session.commit()


def reinforce_memory(memory_id, memory_type='semantic'):
    """Increase importance when a memory is retrieved.

    Args:
        memory_id: ID of the memory to reinforce.
        memory_type: 'semantic' or 'episodic'.
    """
    with get_db_session() as session:
        if memory_type == 'semantic':
            mem = session.query(SemanticMemory).filter(
                SemanticMemory.id == memory_id
            ).first()
        else:
            mem = session.query(EpisodicMemory).filter(
                EpisodicMemory.id == memory_id
            ).first()

        if mem:
            mem.importance = min((mem.importance or 0.5) + 0.05, 1.0)
            mem.access_count = (mem.access_count or 0) + 1
            mem.last_accessed = datetime.now()
            session.commit()


def run_decay(session_id=None):
    """Run full decay cycle on all memory types.

    Can be called periodically (e.g., on startup or on schedule).
    """
    try:
        decay_semantic_memories(session_id)
    except Exception:
        pass
    try:
        decay_episodic_memories(session_id)
    except Exception:
        pass
