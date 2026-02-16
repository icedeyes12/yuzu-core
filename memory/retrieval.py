# [FILE: memory/retrieval.py]
# [DESCRIPTION: Memory retrieval pipeline - scoring + selection]

import math
from datetime import datetime
from database import (
    get_db_session, SemanticMemory, EpisodicMemory, ConversationSegment
)


def _recency_factor(last_accessed):
    """Calculate a recency score between 0.0 and 1.0.

    More recent access = higher score.
    """
    if not last_accessed:
        return 0.1
    now = datetime.now()
    if isinstance(last_accessed, str):
        try:
            last_accessed = datetime.strptime(last_accessed, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            return 0.1
    delta_hours = (now - last_accessed).total_seconds() / 3600.0
    # Exponential decay: half-life of 24 hours
    return math.exp(-delta_hours / 24.0)


def retrieve_semantic_memories(session_id, limit=15):
    """Retrieve top semantic memories by importance × confidence.

    Returns list of dicts with entity, relation, target, score.
    """
    with get_db_session() as session:
        memories = session.query(SemanticMemory).filter(
            SemanticMemory.session_id == session_id
        ).all()

        scored = []
        for mem in memories:
            score = (mem.importance or 0.5) * (mem.confidence or 0.5)
            scored.append({
                'id': mem.id,
                'entity': mem.entity,
                'relation': mem.relation,
                'target': mem.target,
                'confidence': mem.confidence,
                'importance': mem.importance,
                'score': score,
            })

        # Sort by score descending
        scored.sort(key=lambda x: x['score'], reverse=True)

        # Update access count for retrieved memories
        top_ids = [m['id'] for m in scored[:limit]]
        if top_ids:
            for mem in session.query(SemanticMemory).filter(
                SemanticMemory.id.in_(top_ids)
            ).all():
                mem.access_count = (mem.access_count or 0) + 1
                mem.last_accessed = datetime.now()
            session.commit()

        return scored[:limit]


def retrieve_episodic_memories(session_id, limit=5):
    """Retrieve top episodic memories by composite score.

    Score = importance + emotional_weight * 0.5 + recency_factor
    """
    with get_db_session() as session:
        memories = session.query(EpisodicMemory).filter(
            EpisodicMemory.session_id == session_id
        ).all()

        scored = []
        for mem in memories:
            recency = _recency_factor(mem.last_accessed)
            score = (
                (mem.importance or 0.5)
                + (mem.emotional_weight or 0.0) * 0.5
                + recency
            )
            scored.append({
                'id': mem.id,
                'summary': mem.summary,
                'importance': mem.importance,
                'emotional_weight': mem.emotional_weight,
                'score': score,
            })

        scored.sort(key=lambda x: x['score'], reverse=True)

        # Update access count for retrieved memories
        top_ids = [m['id'] for m in scored[:limit]]
        if top_ids:
            for mem in session.query(EpisodicMemory).filter(
                EpisodicMemory.id.in_(top_ids)
            ).all():
                mem.access_count = (mem.access_count or 0) + 1
                mem.last_accessed = datetime.now()
            session.commit()

        return scored[:limit]


def retrieve_segments(session_id, limit=5):
    """Retrieve top conversation segments by importance (most recent first).

    Returns list of dicts with summary and score.
    """
    with get_db_session() as session:
        segments = session.query(ConversationSegment).filter(
            ConversationSegment.session_id == session_id
        ).order_by(ConversationSegment.created_at.desc()).all()

        scored = []
        for seg in segments:
            scored.append({
                'id': seg.id,
                'summary': seg.summary,
                'importance': seg.importance,
                'start_message_id': seg.start_message_id,
                'end_message_id': seg.end_message_id,
            })

        # Sort by importance descending, then by recency (id desc)
        scored.sort(key=lambda x: (x['importance'], x['id']), reverse=True)
        return scored[:limit]


def retrieve_memory(session_id):
    """Main retrieval entry point.

    Returns a structured memory bundle:
    {
        "semantic": [...],
        "episodic": [...],
        "segments": [...]
    }
    """
    try:
        semantic = retrieve_semantic_memories(session_id, limit=15)
    except Exception:
        semantic = []

    try:
        episodic = retrieve_episodic_memories(session_id, limit=5)
    except Exception:
        episodic = []

    try:
        segments = retrieve_segments(session_id, limit=5)
    except Exception:
        segments = []

    return {
        'semantic': semantic,
        'episodic': episodic,
        'segments': segments,
    }


def format_memory(memory_bundle):
    """Format a memory bundle into a text string for system message injection.

    Returns a human-readable text block.
    """
    parts = []

    # Semantic memories
    semantic = memory_bundle.get('semantic', [])
    if semantic:
        parts.append("Known preferences:")
        for mem in semantic:
            parts.append(f"- {mem['entity']} {mem['relation']} {mem['target']}")

    # Episodic memories
    episodic = memory_bundle.get('episodic', [])
    if episodic:
        parts.append("\nRecent important events:")
        for mem in episodic:
            summary = mem.get('summary', '')
            # Truncate long summaries for context
            if len(summary) > 200:
                summary = summary[:200] + '...'
            parts.append(f"- {summary}")

    # Segments
    segments = memory_bundle.get('segments', [])
    if segments:
        parts.append("\nRelevant past context:")
        for seg in segments:
            summary = seg.get('summary', '')
            if len(summary) > 200:
                summary = summary[:200] + '...'
            parts.append(f"- {summary}")

    return '\n'.join(parts)
