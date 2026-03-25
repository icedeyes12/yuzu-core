FILE: app/memory/review.py
DESCRIPTION: FSRS-style review and decay system for memory

import math
import os
import json
from datetime import datetime
from app.database import get_db_session, SemanticMemory, EpisodicMemory

_DECAY_STATE_FILE = os.path.join(os.path.dirname(__file__), '.decay_state.json')


def _get_last_decay_time():
    """Return the last time decay ran (epoch), or None if never run."""
    if not os.path.exists(_DECAY_STATE_FILE):
        return None
    try:
        with open(_DECAY_STATE_FILE) as f:
            return json.load(f).get('last_decay')
    except (ValueError, IOError):
        return None


def _set_last_decay_time():
    """Record current time as last decay timestamp."""
    try:
        with open(_DECAY_STATE_FILE, 'w') as f:
            json.dump({'last_decay': datetime.now().isoformat()}, f)
    except IOError as e:
        print(f"[WARNING] Could not write decay state: {e}")


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


def run_decay(session_id=None, force=False):
    """Run full decay cycle on all memory types.

    Skips if decay ran within the last 6 hours unless force=True.
    """
    if not force:
        last = _get_last_decay_time()
        if last:
            try:
                last_dt = datetime.strptime(last, '%Y-%m-%dT%H:%M:%S.%f')
                hours_since = (datetime.now() - last_dt).total_seconds() / 3600.0
                if hours_since < 6.0:
                    print(f"[decay] Skipped — ran {hours_since:.1f}h ago (min interval: 6h)")
                    return
            except (ValueError, TypeError):
                pass

    print("[decay] Running memory decay...")
    try:
        decay_semantic_memories(session_id)
    except Exception as e:
        print(f"[WARNING] Semantic decay failed: {e}")
    try:
        decay_episodic_memories(session_id)
    except Exception as e:
        print(f"[WARNING] Episodic decay failed: {e}")

    _set_last_decay_time()
    print("[decay] Done.")