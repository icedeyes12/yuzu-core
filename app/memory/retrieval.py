# FILE: app/memory/retrieval.py
# DESCRIPTION: Memory retrieval pipeline with PostgreSQL pgvector search + hybrid scoring

import math
from datetime import datetime, timedelta
from app.memory.db_memory import (
    search_similar,
    get_facts_by_session,
    update_last_accessed,
    FACT_TYPE_STATIC,
    FACT_TYPE_DYNAMIC,
)
from app.db_pg_models import get_session_messages


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
    """Search messages within a time window using PostgreSQL."""
    results = []
    try:
        start_str = start.strftime('%Y-%m-%d %H:%M:%S')
        end_str = end.strftime('%Y-%m-%d %H:%M:%S')
        
        messages = get_session_messages(session_id, limit=limit)
        
        for msg in messages:
            # Filter by timestamp
            ts = msg.get("timestamp", "")
            if ts < start_str or ts > end_str:
                continue
                
            content = msg.get("content", "")
            if msg.get("content_encrypted"):
                try:
                    from app.encryption import encryptor
                    content = encryptor.decrypt(content)
                except Exception:
                    content = "[ENCRYPTED]"
                    
            results.append({
                "timestamp": ts,
                "role": msg.get("role"),
                "content": content[:500],
            })
    except Exception as e:
        print(f"[retrieval] Temporal scan failed: {e}")
    return results


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


# ── Retrieval functions ────────────────────────────────────────────────────────

def retrieve_semantic_memories(session_id, query=None, limit=15):
    """
    Retrieve semantic memories using PostgreSQL pgvector search.
    
    Args:
        session_id: current session
        query: optional user query for semantic search
        limit: max results
        
    Returns:
        list of dicts with entity, relation, target, confidence, importance, score
    """
    query_vec = _embed_query(query) if query else None
    
    if query_vec:
        # Vector search via PostgreSQL
        results = search_similar(
            embedding=query_vec,
            session_id=session_id,
            fact_type=FACT_TYPE_STATIC,
            metadata_filter={"source_table": "semantic_memories"},
            limit=limit,
        )
        
        scored = []
        for r in results:
            meta = r.get("metadata", {})
            # Hybrid scoring: similarity * 0.6 + importance * 0.2 + confidence * 0.2
            distance = r.get("distance", 0.0)
            similarity = 1.0 - distance  # Convert distance to similarity
            importance = meta.get("importance", 0.5)
            confidence = meta.get("confidence", 0.5)
            score = similarity * 0.6 + importance * 0.2 + confidence * 0.2
            
            # Parse content as "entity relation target" format
            content = r.get("content", "")
            parts = content.split(" ", 2)
            entity = parts[0] if len(parts) > 0 else "User"
            relation = parts[1] if len(parts) > 1 else "unknown"
            target = parts[2] if len(parts) > 2 else content
            
            scored.append({
                "id": r.get("id"),
                "entity": meta.get("entity", entity),
                "relation": meta.get("relation", relation),
                "target": meta.get("target", target),
                "confidence": confidence,
                "importance": importance,
                "score": score,
            })
        
        # Update last_accessed for retrieved memories
        if scored:
            update_last_accessed([m["id"] for m in scored])
        
        return sorted(scored, key=lambda x: x["score"], reverse=True)[:limit]
    
    # Fallback: get all static facts for session
    facts = get_facts_by_session(session_id, fact_type=FACT_TYPE_STATIC, limit=limit)
    return [
        {
            "id": f.get("id"),
            "entity": f.get("metadata", {}).get("entity", "User"),
            "relation": f.get("metadata", {}).get("relation", "unknown"),
            "target": f.get("metadata", {}).get("target", f.get("content", "")),
            "confidence": f.get("metadata", {}).get("confidence", 0.5),
            "importance": f.get("metadata", {}).get("importance", 0.5),
            "score": f.get("metadata", {}).get("importance", 0.5),
        }
        for f in facts
    ]


def retrieve_episodic_memories(session_id, query=None, limit=5):
    """
    Retrieve episodic memories using PostgreSQL pgvector search.
    
    Args:
        session_id: current session
        query: optional user query for semantic search
        limit: max results
        
    Returns:
        list of dicts with summary, importance, emotional_weight, score
    """
    query_vec = _embed_query(query) if query else None
    
    if query_vec:
        results = search_similar(
            embedding=query_vec,
            session_id=session_id,
            fact_type=FACT_TYPE_DYNAMIC,
            metadata_filter={"source_table": "episodic_memories"},
            limit=limit,
        )
        
        scored = []
        for r in results:
            meta = r.get("metadata", {})
            distance = r.get("distance", 0.0)
            similarity = 1.0 - distance
            importance = meta.get("importance", 0.5)
            recency = _recency_factor(r.get("last_accessed"))
            score = similarity * 0.5 + importance * 0.25 + recency * 0.25
            
            scored.append({
                "id": r.get("id"),
                "summary": r.get("content"),
                "importance": importance,
                "emotional_weight": meta.get("emotional_weight", 0.0),
                "score": score,
            })
        
        if scored:
            update_last_accessed([m["id"] for m in scored])
        
        return sorted(scored, key=lambda x: x["score"], reverse=True)[:limit]
    
    # Fallback
    facts = get_facts_by_session(session_id, fact_type=FACT_TYPE_DYNAMIC, limit=limit)
    return [
        {
            "id": f.get("id"),
            "summary": f.get("content"),
            "importance": f.get("metadata", {}).get("importance", 0.5),
            "emotional_weight": f.get("metadata", {}).get("emotional_weight", 0.0),
            "score": f.get("metadata", {}).get("importance", 0.5),
        }
        for f in facts
        if f.get("metadata", {}).get("source_table") == "episodic_memories"
    ]


def retrieve_segments(session_id, query=None, limit=5):
    """
    Retrieve conversation segments using PostgreSQL pgvector search.
    
    Args:
        session_id: current session
        query: optional user query for semantic search
        limit: max results
        
    Returns:
        list of dicts with summary, importance, start_message_id, end_message_id, score
    """
    query_vec = _embed_query(query) if query else None
    
    if query_vec:
        results = search_similar(
            embedding=query_vec,
            session_id=session_id,
            fact_type=FACT_TYPE_DYNAMIC,
            metadata_filter={"source_table": "conversation_segments"},
            limit=limit,
        )
        
        scored = []
        for r in results:
            meta = r.get("metadata", {})
            distance = r.get("distance", 0.0)
            similarity = 1.0 - distance
            importance = meta.get("importance", 0.5)
            score = similarity * 0.5 + importance * 0.5
            
            scored.append({
                "id": r.get("id"),
                "summary": r.get("content"),
                "importance": importance,
                "start_message_id": meta.get("start_message_id"),
                "end_message_id": meta.get("end_message_id"),
                "score": score,
            })
        
        if scored:
            update_last_accessed([m["id"] for m in scored])
        
        return sorted(scored, key=lambda x: x["score"], reverse=True)[:limit]
    
    # Fallback
    facts = get_facts_by_session(session_id, fact_type=FACT_TYPE_DYNAMIC, limit=limit)
    return [
        {
            "id": f.get("id"),
            "summary": f.get("content"),
            "importance": f.get("metadata", {}).get("importance", 0.5),
            "start_message_id": f.get("metadata", {}).get("start_message_id"),
            "end_message_id": f.get("metadata", {}).get("end_message_id"),
            "score": f.get("metadata", {}).get("importance", 0.5),
        }
        for f in facts
        if f.get("metadata", {}).get("source_table") == "conversation_segments"
    ]


def retrieve_memory(session_id, query=None):
    """
    Main retrieval entry point.

    Args:
        session_id: current session
        query: optional user query for semantic search

    Returns:
        dict with semantic, episodic, segments, temporal_messages
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
        "semantic": semantic,
        "episodic": episodic,
        "segments": segments,
        "temporal_messages": temporal_messages,
    }


def format_memory(memory_bundle):
    """Format a memory bundle into a text string for system message injection."""
    parts = []

    semantic = memory_bundle.get("semantic", [])
    if semantic:
        parts.append("Known preferences:")
        for mem in semantic:
            parts.append(f"- {mem['entity']} {mem['relation']} {mem['target']}")

    episodic = memory_bundle.get("episodic", [])
    if episodic:
        parts.append("\nRecent important events:")
        for mem in episodic:
            summary = mem.get("summary") or ""
            if len(summary) > 200:
                summary = summary[:200] + "..."
            parts.append(f"- {summary}")

    segments = memory_bundle.get("segments", [])
    if segments:
        parts.append("\nRelevant past context:")
        for seg in segments:
            summary = seg.get("summary") or ""
            if len(summary) > 200:
                summary = summary[:200] + "..."
            parts.append(f"- {summary}")

    temporal = memory_bundle.get("temporal_messages", [])
    if temporal:
        parts.append("\nMessages from requested time period:")
        for msg in temporal[:10]:
            ts = msg.get("timestamp", "")[:16]
            role = msg.get("role", "")
            content = msg.get("content", "")[:300]
            parts.append(f"- [{ts}] {role}: {content}")

    return "\n".join(parts)