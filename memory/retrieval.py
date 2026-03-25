# [FILE: memory/retrieval.py]
# [DESCRIPTION: Memory retrieval pipeline - cosine similarity + hybrid scoring]

import math
from datetime import datetime
from app.database import (
    get_db_session, SemanticMemory, EpisodicMemory, ConversationSegment
)
from app.memory.embedder import cosine_similarity, blob_to_vec


def _recency_factor(last_accessed) -> float:
    """Recency score 0.0–1.0, half-life of 24 hours."""
    if not last_accessed:
        return 0.1
    now = datetime.now()
    if isinstance(last_accessed, str):
        try:
            last_accessed = datetime.strptime(last_accessed, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            return 0.1
    delta_hours = (now - last_accessed).total_seconds() / 3600.0
    return math.exp(-delta_hours / 24.0)


def _embed_query(text: str) -> list[float] | None:
    """Embed a query string via Chutes API."""
    try:
        from memory.embedder import embed_text
        return embed_text(text)
    except Exception as e:
        print(f"[WARNING] Query embedding failed: {e}")
        return None


def retrieve_semantic_memories(session_id, query=None, limit=15):
    """
    Retrieve semantic memories by cosine similarity to query.
    
    If query is provided: embed query, rank by cosine similarity.
    If query is None or embedding fails: fall back to importance × confidence.
    """
    with get_db_session() as session:
        memories = session.query(SemanticMemory).filter(
            SemanticMemory.session_id == session_id
        ).all()

        if not memories:
            return []

        query_vec = _embed_query(query) if query else None

        scored = []
        for mem in memories:
            if query_vec and mem.embedding_vector:
                try:
                    mem_vec = blob_to_vec(mem.embedding_vector)
                    sim = cosine_similarity(query_vec, mem_vec)
                    score = sim * 0.6 + (mem.importance or 0.5) * 0.2 + (mem.confidence or 0.5) * 0.2
                except Exception:
                    score = (mem.importance or 0.5) * (mem.confidence or 0.5)
            else:
                # Fallback: importance × confidence
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

        scored.sort(key=lambda x: x['score'], reverse=True)

        top_ids = [m['id'] for m in scored[:limit]]
        if top_ids:
            for mem in session.query(SemanticMemory).filter(
                SemanticMemory.id.in_(top_ids)
            ).all():
                mem.access_count = (mem.access_count or 0) + 1
                mem.last_accessed = datetime.now()
            session.commit()

        return scored[:limit]


def retrieve_episodic_memories(session_id, query=None, limit=5):
    """
    Retrieve episodic memories by cosine similarity + hybrid score.
    
    Score = cosine_sim * 0.5 + importance * 0.25 + recency * 0.25
    """
    with get_db_session() as session:
        memories = session.query(EpisodicMemory).filter(
            EpisodicMemory.session_id == session_id
        ).all()

        if not memories:
            return []

        query_vec = _embed_query(query) if query else None

        scored = []
        for mem in memories:
            recency = _recency_factor(mem.last_accessed)

            if query_vec and mem.embedding:
                try:
                    mem_vec = blob_to_vec(mem.embedding)
                    sim = cosine_similarity(query_vec, mem_vec)
                    score = sim * 0.5 + (mem.importance or 0.5) * 0.25 + recency * 0.25
                except Exception:
                    score = ((mem.importance or 0.5) + (mem.emotional_weight or 0.0) * 0.5 + recency)
            else:
                score = ((mem.importance or 0.5) + (mem.emotional_weight or 0.0) * 0.5 + recency)

            scored.append({
                'id': mem.id,
                'summary': mem.summary,
                'importance': mem.importance,
                'emotional_weight': mem.emotional_weight,
                'score': score,
            })

        scored.sort(key=lambda x: x['score'], reverse=True)

        top_ids = [m['id'] for m in scored[:limit]]
        if top_ids:
            for mem in session.query(EpisodicMemory).filter(
                EpisodicMemory.id.in_(top_ids)
            ).all():
                mem.access_count = (mem.access_count or 0) + 1
                mem.last_accessed = datetime.now()
            session.commit()

        return scored[:limit]


def retrieve_segments(session_id, query=None, limit=5):
    """Retrieve conversation segments by importance or similarity."""
    with get_db_session() as session:
        segments = session.query(ConversationSegment).filter(
            ConversationSegment.session_id == session_id
        ).order_by(ConversationSegment.created_at.desc()).all()

        scored = []
        query_vec = _embed_query(query) if query else None

        for seg in segments:
            if query_vec and seg.embedding:
                try:
                    mem_vec = blob_to_vec(seg.embedding)
                    sim = cosine_similarity(query_vec, mem_vec)
                    score = sim * 0.5 + (seg.importance or 0.5) * 0.5
                except Exception:
                    score = seg.importance or 0.5
            else:
                score = seg.importance or 0.5

            scored.append({
                'id': seg.id,
                'summary': seg.summary,
                'importance': seg.importance,
                'start_message_id': seg.start_message_id,
                'end_message_id': seg.end_message_id,
                'score': score,
            })

        scored.sort(key=lambda x: x['score'], reverse=True)
        return scored[:limit]


def retrieve_memory(session_id, query=None):
    """
    Main retrieval entry point.
    
    Args:
        session_id: current session
        query: optional user query for semantic search
    
    Returns:
        dict with semantic, episodic, segments
    """
    try:
        semantic = retrieve_semantic_memories(session_id, query=query, limit=15)
    except Exception as e:
        print(f"[WARNING] Semantic memory retrieval failed: {e}")
        semantic = []

    try:
        episodic = retrieve_episodic_memories(session_id, query=query, limit=5)
    except Exception as e:
        print(f"[WARNING] Episodic memory retrieval failed: {e}")
        episodic = []

    try:
        segments = retrieve_segments(session_id, query=query, limit=5)
    except Exception as e:
        print(f"[WARNING] Segment retrieval failed: {e}")
        segments = []

    # Supplement: if query contains temporal cues, also scan messages directly
    temporal_messages = []
    if query:
        try:
            from tools.memory_search import _detect_time_window, _search_temporal_messages
            time_window = _detect_time_window(query)
            if time_window:
                start, end = time_window
                temporal_messages = _search_temporal_messages(session_id, start, end)
        except Exception:
            pass

    return {
        'semantic': semantic,
        'episodic': episodic,
        'segments': segments,
        'temporal_messages': temporal_messages,
    }


def format_memory(memory_bundle):
    """Format a memory bundle into a text string for system message injection."""
    parts = []

    semantic = memory_bundle.get('semantic', [])
    if semantic:
        parts.append("Known preferences:")
        for mem in semantic:
            parts.append(f"- {mem['entity']} {mem['relation']} {mem['target']}")

    episodic = memory_bundle.get('episodic', [])
    if episodic:
        parts.append("\nRecent important events:")
        for mem in episodic:
            summary = mem.get('summary', '')
            if len(summary) > 200:
                summary = summary[:200] + '...'
            parts.append(f"- {summary}")

    segments = memory_bundle.get('segments', [])
    if segments:
        parts.append("\nRelevant past context:")
        for seg in segments:
            summary = seg.get('summary', '')
            if len(summary) > 200:
                summary = summary[:200] + '...'
            parts.append(f"- {summary}")

    temporal = memory_bundle.get('temporal_messages', [])
    if temporal:
        parts.append("\nMessages from requested time period:")
        for msg in temporal[:10]:
            ts = msg.get('timestamp', '')[:16]
            role = msg.get('role', '')
            content = msg.get('content', '')[:300]
            parts.append(f"- [{ts}] {role}: {content}")

    return '\n'.join(parts)
