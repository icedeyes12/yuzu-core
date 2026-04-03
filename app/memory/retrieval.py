# FILE: app/memory/retrieval.py
# DESCRIPTION: Memory retrieval with PostgreSQL pgvector.
#              Simplified to 2 types: static (global) and dynamic (per-session).
#
# No more semantic/episodic/segments - just static and dynamic.

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
    """Recency score 0.0-1.0, half-life of 24 hours."""
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


def _score_fact(r: dict) -> float:
    """Hybrid score: similarity * 0.6 + importance * 0.2 + confidence * 0.2"""
    meta = r.get("metadata", {})
    distance = r.get("distance", 0.0)
    similarity = 1.0 - distance
    importance = meta.get("importance", 0.5)
    confidence = meta.get("confidence", 0.5)
    return similarity * 0.6 + importance * 0.2 + confidence * 0.2


def _parse_fact_content(r: dict) -> dict:
    """Parse fact content and metadata into standardized format."""
    meta = r.get("metadata", {})
    content = r.get("content", "")

    # Try to parse as "entity relation target" format
    parts = content.split(" ", 2)
    entity = meta.get("entity", parts[0] if len(parts) > 0 else "User")
    relation = meta.get("relation", parts[1] if len(parts) > 1 else "unknown")
    target = meta.get("target", parts[2] if len(parts) > 2 else content)

    return {
        "id": r.get("id"),
        "content": content,
        "entity": entity,
        "relation": relation,
        "target": target,
        "confidence": meta.get("confidence", 0.5),
        "importance": meta.get("importance", 0.5),
        "score": _score_fact(r),
        "last_accessed": r.get("last_accessed"),
    }


# ── Retrieval functions ──────────────────────────────────────────────────────

def retrieve_static_memories(query=None, limit=15):
    """
    Retrieve static (global) memories - no session filter.
    Returns list of parsed facts sorted by score.
    """
    query_vec = _embed_query(query) if query else None

    if query_vec:
        results = search_similar(
            embedding=query_vec,
            fact_type=FACT_TYPE_STATIC,
            limit=limit,
        )
    else:
        results = get_facts_by_session(session_id=None, fact_type=FACT_TYPE_STATIC, limit=limit)

    if not results:
        return []

    parsed = [_parse_fact_content(r) for r in results]
    parsed = sorted(parsed, key=lambda x: x["score"], reverse=True)[:limit]

    if parsed:
        update_last_accessed([m["id"] for m in parsed])

    return parsed


def retrieve_dynamic_memories(session_id: int, query=None, limit=10):
    """
    Retrieve dynamic (per-session) memories.
    Returns list of parsed facts sorted by score.
    """
    query_vec = _embed_query(query) if query else None

    if query_vec:
        results = search_similar(
            embedding=query_vec,
            session_id=session_id,
            fact_type=FACT_TYPE_DYNAMIC,
            limit=limit,
        )
    else:
        results = get_facts_by_session(session_id=session_id, fact_type=FACT_TYPE_DYNAMIC, limit=limit)

    if not results:
        return []

    parsed = [_parse_fact_content(r) for r in results]
    parsed = sorted(parsed, key=lambda x: x["score"], reverse=True)[:limit]

    if parsed:
        update_last_accessed([m["id"] for m in parsed])

    return parsed


# Legacy aliases for backward compat
retrieve_semantic_memories = retrieve_static_memories
retrieve_episodic_memories = retrieve_dynamic_memories
retrieve_segments = retrieve_dynamic_memories


def retrieve_memory(session_id: int, query=None):
    """
    Main retrieval entry point.

    Returns:
        dict with static, dynamic, temporal_messages
    """
    try:
        static = retrieve_static_memories(query=query, limit=15)
    except Exception as e:
        print(f"[WARNING] Static memory retrieval failed: {e}")
        static = []

    try:
        dynamic = retrieve_dynamic_memories(session_id, query=query, limit=10)
    except Exception as e:
        print(f"[WARNING] Dynamic memory retrieval failed: {e}")
        dynamic = []

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
        "static": static,
        "dynamic": dynamic,
        "temporal_messages": temporal_messages,
    }


def format_memory(memory_bundle):
    """Format a memory bundle into a text string for system message injection."""
    parts = []

    # Static memories - global facts
    static = memory_bundle.get("static", [])
    if static:
        parts.append("Known preferences:")
        for mem in static[:10]:
            parts.append(f"- {mem['entity']} {mem['relation']} {mem['target']}")

    # Dynamic memories - session-specific facts
    dynamic = memory_bundle.get("dynamic", [])
    if dynamic:
        parts.append("\nSession memories:")
        for mem in dynamic[:5]:
            content = mem.get("content") or mem.get("target") or ""
            if len(content) > 150:
                content = content[:150] + "..."
            parts.append(f"- {content}")

    # Temporal messages
    temporal = memory_bundle.get("temporal_messages", [])
    if temporal:
        parts.append("\nMessages from requested time period:")
        for msg in temporal[:10]:
            ts = msg.get("timestamp", "")[:16]
            role = msg.get("role", "")
            content = msg.get("content", "")[:200]
            parts.append(f"- [{ts}] {role}: {content}")

    return "\n".join(parts)
