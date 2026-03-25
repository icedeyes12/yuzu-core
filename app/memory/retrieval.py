# [FILE: memory/retrieval.py]
# [DESCRIPTION: Memory retrieval pipeline - cosine similarity + hybrid scoring]

import math
from datetime import datetime, timedelta
from app.database import (
    get_db_session, SemanticMemory, EpisodicMemory, ConversationSegment, Message
)
from app.memory.embedder import cosine_similarity, blob_to_vec


# ── Temporal cue helpers ──────────────────────────────────────────────────────

_TEMPORAL_CUES = [
    "kemarin", "minggu lalu", "waktu itu", "terakhir", "pas aku",
    "last time", "yesterday", "last week", "before", "remember when",
    "dulu", "tadi", "bulan lalu", "tahun lalu", "pernah",
    "last month", "last year", "earlier", "previously", "ago"
]
_MONTH_NAMES = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4,
    "mei": 5, "juni": 6, "juli": 7, "agustus": 8,
    "september": 9, "oktober": 10, "november": 11, "desember": 12,
    "january": 1, "february": 2, "march": 3, "may": 5,
    "june": 6, "july": 7, "august": 8, "october": 10, "december": 12,
}
_RELATIVE_CUES = {
    "kemarin":     lambda now: (now - timedelta(days=1), now),
    "yesterday":   lambda now: (now - timedelta(days=1), now),
    "tadi":        lambda now: (now.replace(hour=0, minute=0, second=0), now),
    "minggu lalu": lambda now: (now - timedelta(weeks=1), now),
    "last week":   lambda now: (now - timedelta(weeks=1), now),
    "bulan lalu":  lambda now: (now - timedelta(days=30), now),
    "last month":  lambda now: (now - timedelta(days=30), now),
    "tahun lalu":  lambda now: (now - timedelta(days=365), now),
    "last year":   lambda now: (now - timedelta(days=365), now),
}


def _detect_month(query):
    ql = query.lower()
    for name, num in _MONTH_NAMES.items():
        if name in ql:
            return num
    return None


def _detect_time_window(query):
    now = datetime.now()
    ql = query.lower()
    month = _detect_month(query)
    if month is not None:
        year = now.year if month <= now.month else now.year - 1
        start = datetime(year, month, 1)
        end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
        return start, end
    for cue, calc in _RELATIVE_CUES.items():
        if cue in ql:
            return calc(now)
    return None


def _search_temporal_messages(session_id, start, end, limit=200):
    results = []
    try:
        start_str = start.strftime('%Y-%m-%d %H:%M:%S')
        end_str = end.strftime('%Y-%m-%d %H:%M:%S')
        with get_db_session() as session:
            messages = (
                session.query(Message)
                .filter(
                    Message.session_id == session_id,
                    Message.role.in_(['user', 'assistant']),
                    Message.timestamp >= start_str,
                    Message.timestamp <= end_str,
                )
                .order_by(Message.timestamp.asc())
                .limit(limit)
                .all()
            )
            for msg in messages:
                content = msg.content
                if msg.content_encrypted:
                    try:
                        from app.encryption import encryptor
                        content = encryptor.decrypt(content)
                    except Exception:
                        content = "[ENCRYPTED]"
                results.append({
                    "timestamp": msg.timestamp,
                    "role": msg.role,
                    "content": content[:500],
                })
    except Exception as e:
        print(f"[retrieval] Temporal scan failed: {e}")
    return results


# ── Fallback scoring — consistent across all memory types ─────────────────────

def _semantic_fallback_score(mem) -> float:
    """Consistent fallback scoring for semantic memories.

    Formula: normalized importance × confidence, weighted by recency.
    Uses the same multiplicative model as the primary scoring path.
    """
    importance = mem.importance or 0.5
    confidence = mem.confidence or 0.5
    recency = _recency_factor(mem.last_accessed)
    return importance * confidence * (0.5 + recency * 0.5)


def _episodic_fallback_score(mem) -> float:
    """Consistent fallback scoring for episodic memories.

    Formula: importance × recency, with emotional weight as a boost.
    Uses the same multiplicative structure as the semantic fallback.
    """
    importance = mem.importance or 0.5
    recency = _recency_factor(mem.last_accessed)
    emotional = mem.emotional_weight or 0.0
    return importance * recency * (1.0 + emotional * 0.3)


# ── Retrieval functions ────────────────────────────────────────────────────────

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
        from app.memory.embedder import embed_text
        return embed_text(text)
    except Exception as e:
        print(f"[WARNING] Query embedding failed: {e}")
        return None


def retrieve_semantic_memories(session_id, query=None, limit=15):
    """
    Retrieve semantic memories by cosine similarity to query.

    Score (with query): cosine_sim × 0.6 + importance × 0.2 + confidence × 0.2
    Score (fallback):    importance × confidence × (0.5 + recency × 0.5)
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
                    score = _semantic_fallback_score(mem)
            else:
                score = _semantic_fallback_score(mem)

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

    Score (with query): cosine_sim × 0.5 + importance × 0.25 + recency × 0.25
    Score (fallback):   importance × recency × (1.0 + emotional_weight × 0.3)
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
                    score = _episodic_fallback_score(mem)
            else:
                score = _episodic_fallback_score(mem)

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

    temporal_messages = []
    if query:
        try:
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
