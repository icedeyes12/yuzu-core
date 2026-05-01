from __future__ import annotations
# FILE: app/memory/retrieval.py
# DESCRIPTION: Memory retrieval with PostgreSQL pgvector.
#              Simplified to 2 types: static (global) and dynamic (per-session).
#
# No more semantic/episodic/segments - just static and dynamic.


import logging
import math
from datetime import datetime, timedelta

from app.memory.db_memory import (
    search_similar,
    search_trgm,
    search_tsv,
    get_facts_by_session,
    update_last_accessed,
    # Async versions
    search_similar_async,
    get_facts_by_session_async,
    update_last_accessed_async,
)
from app.memory.db_memory_queries import (
    FACT_TYPE_STATIC, FACT_TYPE_DYNAMIC,
)
from app.db_pg_models import get_session_messages

logger = logging.getLogger(__name__)


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
        logger.warning(f"Temporal scan failed: {e}")
    return results


def _recency_factor(last_accessed) -> float:
    """Recency score 0.0-1.0, half-life of 24 hours."""
    if not last_accessed:
        return 0.1
    now = datetime.now()
    if isinstance(last_accessed, str):
        try:
            last_accessed = datetime.strptime(last_accessed, '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            try:
                last_accessed = datetime.strptime(last_accessed, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return 0.1
    delta_hours = (now - last_accessed).total_seconds() / 3600.0
    return math.exp(-delta_hours / 24.0)


def _fsrs_retrievability(r: dict) -> float:
    """
    FSRS retrievability for episodic facts.

    Uses fsrs library if available for proper retrievability calculation.
    Falls back to manual exponential decay if fsrs not installed.

    Only applies to episodic facts (source_table='episodic_memories').
    """
    meta = r.get("metadata", {}) or {}
    source_table = meta.get("source_table", "")
    if source_table != "episodic_memories":
        return 1.0  # no FSRS re-rank for non-episodic facts

    # Try fsrs library first
    try:
        from fsrs import Card
        fsrs_available = True
    except ImportError:
        fsrs_available = False

    if fsrs_available:
        from fsrs import Card
        from app.memory.memory_review import _get_fsrs

        fsrs = _get_fsrs()
        if fsrs:
            stability = meta.get("stability", 1.0)
            difficulty = meta.get("difficulty", 1.0)
            last_reviewed = meta.get("last_reviewed_at")
            state = meta.get("state", 2)  # default to review state
            reps = meta.get("reps", 0)
            lapses = meta.get("lapses", 0)

            now = datetime.now()
            if last_reviewed:
                try:
                    last_dt = datetime.fromisoformat(last_reviewed.replace("Z", "+00:00").replace("+00:00", ""))
                    days_elapsed = max((now - last_dt).total_seconds() / 86400.0, 0.0)
                except Exception:
                    days_elapsed = 0.0
            else:
                days_elapsed = 0.0

            try:
                card = Card(
                    stability=stability,
                    difficulty=difficulty,
                    elapsed_days=days_elapsed,
                    scheduled_days=stability,
                    reps=reps,
                    lapses=lapses,
                    state=state,
                    last_review=last_reviewed,
                )
                # Get retrievability from fsrs
                retrievability = fsrs.retrievability(card, days_elapsed)
                return max(retrievability, 0.1)
            except Exception as e:
                logger.debug(f"FSRS retrievability calculation failed: {e}")
                # Fall through to manual calculation

    # Manual fallback: exponential decay
    last_accessed = r.get("last_accessed")
    if not last_accessed:
        return 0.1  # never accessed → low retrievability

    now = datetime.now()
    if isinstance(last_accessed, str):
        try:
            last_accessed = datetime.strptime(last_accessed, '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            try:
                last_accessed = datetime.strptime(last_accessed, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return 0.1

    delta_hours = (now - last_accessed).total_seconds() / 3600.0
    stability = meta.get("stability", 24.0)  # hours; default half-life 24h
    stability = max(stability, 0.1)  # prevent div-by-zero

    retrievability = math.exp(-delta_hours / stability)
    return retrievability


def _episodic_score_adjustment(r: dict) -> float:
    """
    Compute FSRS re-rank multiplier for episodic facts.
    final = base_score * (0.5 + 0.5 * retrievability)
    - freshly accessed (retrievability ~1): multiplier = 1.0 → no change
    - decayed (retrievability ~0): multiplier = 0.5 → score halved
    """
    retrievability = _fsrs_retrievability(r)
    return 0.5 + 0.5 * retrievability


def _embed_query(text: str) -> list[float] | None:
    """Embed a query string via Chutes API."""
    try:
        from app.memory.embedder import embed_text
        return embed_text(text)
    except Exception as e:
        logger.warning(f"Query embedding failed: {e}")
        return None


def _hybrid_rrf_merge(channel_results: dict[str, list[dict]], k: int = 60) -> list[dict]:
    """
    N-channel Reciprocal Rank Fusion — merges ranked lists from multiple search channels.

    RRF score = Σ 1.0 / (k + rank)  per channel
    Results sorted by fused score descending.

    Args:
        channel_results: {channel_name: [(id, score, rank), ...], ...}
                         Each channel's list should be pre-sorted by rank (1 = best).
    """
    if not channel_results:
        return []

    item_map: dict[int, dict] = {}
    rrf_scores: dict[int, float] = {}

    for channel_name, results in channel_results.items():
        if not results:
            continue
        for rank, item in enumerate(results, start=1):
            item_id = item.get("id")
            if item_id is None:
                continue
            # Keep the richer item dict
            if item_id not in item_map:
                item_map[item_id] = item
            # Accumulate RRF score from this channel
            rrf_scores[item_id] = rrf_scores.get(item_id, 0.0) + 1.0 / (k + rank)

    # Tie-break: higher score first, then lower id
    fused = [
        (item_id, rrf_scores[item_id], item_map[item_id].get("score", 0.0))
        for item_id in item_map
    ]
    fused.sort(key=lambda x: (-x[1], -x[2], x[0]))

    return [item_map[item_id] for item_id, _, _ in fused]


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
        "category": meta.get("category"),
        "confidence": meta.get("confidence", 0.5),
        "importance": meta.get("importance", 0.5),
        "score": _score_fact(r),
        "last_accessed": r.get("last_accessed"),
    }


# ── Retrieval functions ──────────────────────────────────────────────────────


def _enrich_with_trgm_score(results: list[dict], keyword: str) -> list[dict]:
    """Add trigram similarity score to results for hybrid scoring."""
    if not results or not keyword:
        return results
    trgm_scores = {r["id"]: r.get("similarity", 0.0) for r in results}
    for r in results:
        r["trgm_score"] = trgm_scores.get(r["id"], 0.0)
    return results


def retrieve_static_memories(query=None, limit=15):
    """
    Retrieve static (global) memories — no session filter.
    3-channel hybrid: vector + trigram + tsvector, merged via RRF.
    """
    if not query:
        results = get_facts_by_session(session_id=None, fact_type=FACT_TYPE_STATIC, limit=limit)
        parsed = [_parse_fact_content(r) for r in results]
        parsed = sorted(parsed, key=lambda x: x["score"], reverse=True)[:limit]
        if parsed:
            update_last_accessed([m["id"] for m in parsed])
        return parsed

    query_vec = _embed_query(query)
    keyword = query.strip()

    # Channel 1: vector (pgvector)
    vec_results = search_similar(
        embedding=query_vec,
        fact_type=FACT_TYPE_STATIC,
        limit=limit,
    ) if query_vec else []

    # Channel 2: trigram fuzzy (pg_trgm)
    trgm_results = search_trgm(
        query=keyword,
        fact_type=FACT_TYPE_STATIC,
        limit=limit,
    )

    # Channel 3: tsvector full-text (pg_trgm tsvector)
    tsv_results = search_tsv(
        query=keyword,
        fact_type=FACT_TYPE_STATIC,
        limit=limit,
    )

    # Merge via RRF
    channels = {
        "vector": vec_results,
        "trigram": trgm_results,
        "tsvector": tsv_results,
    }
    merged = _hybrid_rrf_merge(channels, k=60)

    if not merged:
        return []

    # Deduplicate: keep first occurrence by id
    seen, parsed = set(), []
    for r in merged:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        parsed.append(_parse_fact_content(r))

    parsed = parsed[:limit]

    if parsed:
        update_last_accessed([m["id"] for m in parsed])

    return parsed


def retrieve_dynamic_memories(session_id: int, query=None, limit=10):
    """
    Retrieve dynamic (per-session) episodic memories.
    3-channel hybrid: vector + trigram + tsvector, merged via RRF.
    """
    if not query:
        all_dynamic = get_facts_by_session(session_id=session_id, fact_type=FACT_TYPE_DYNAMIC, limit=limit * 3)
        results = [
            r for r in all_dynamic
            if r.get("metadata", {}).get("source_table") == "episodic_memories"
        ][:limit]
        parsed = [_parse_fact_content(r) for r in results]
        parsed = sorted(parsed, key=lambda x: x["score"], reverse=True)[:limit]
        if parsed:
            update_last_accessed([m["id"] for m in parsed])
        return parsed

    query_vec = _embed_query(query)
    keyword = query.strip()

    # Channel 1: vector (pgvector)
    vec_results = search_similar(
        embedding=query_vec,
        session_id=session_id,
        fact_type=FACT_TYPE_DYNAMIC,
        metadata_filter={"source_table": "episodic_memories"},
        limit=limit,
    ) if query_vec else []

    # Channel 2: trigram fuzzy (pg_trgm)
    trgm_results = search_trgm(
        query=keyword,
        session_id=session_id,
        fact_type=FACT_TYPE_DYNAMIC,
        limit=limit,
    )

    # Channel 3: tsvector full-text (pg_trgm tsvector)
    tsv_results = search_tsv(
        query=keyword,
        session_id=session_id,
        fact_type=FACT_TYPE_DYNAMIC,
        limit=limit,
    )

    # Merge via RRF
    channels = {
        "vector": vec_results,
        "trigram": trgm_results,
        "tsvector": tsv_results,
    }
    merged = _hybrid_rrf_merge(channels, k=60)

    if not merged:
        return []

    # Deduplicate: keep first occurrence by id
    seen, parsed = set(), []
    for r in merged:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        parsed.append(_parse_fact_content(r))

    parsed = parsed[:limit]

    if parsed:
        update_last_accessed([m["id"] for m in parsed])

    return parsed


# Legacy aliases for backward compat
retrieve_semantic_memories = retrieve_static_memories
retrieve_episodic_memories = retrieve_dynamic_memories



def retrieve_segments(session_id: int, query=None, limit: int = 10):
    """
    Retrieve conversation segments for a session.
    
    Segments are stored as fact_type=dynamic with source_table='conversation_segments'.
    They represent raw message windows, not semantic facts.
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
    else:
        # Fall back: fetch segments without vector search
        all_dynamic = get_facts_by_session(
            session_id=session_id,
            fact_type=FACT_TYPE_DYNAMIC,
            limit=limit * 3,  # over-fetch, filter below
        )
        # Filter: must be real segments (not old garbage with "No summary" content)
        _NO_SUMMARY_PATTERNS = ("no summary found", "no summary", "tidak ada ringkasan")
        results = [
            r for r in all_dynamic
            if r.get("metadata", {}).get("source_table") == "conversation_segments"
            and r.get("content")
            and len(r.get("content", "")) > 15
            and r.get("content", "").lower()[:20] not in _NO_SUMMARY_PATTERNS
        ][:limit]

    if not results:
        return []

    parsed = [_parse_fact_content(r) for r in results]
    parsed = sorted(parsed, key=lambda x: x["score"], reverse=True)[:limit]

    if parsed:
        update_last_accessed([m["id"] for m in parsed])

    return parsed


def retrieve_memory(session_id: int, query=None):
    """
    Main retrieval entry point.

    Returns:
        dict with static, dynamic, temporal_messages
    """
    try:
        static = retrieve_static_memories(query=query, limit=15)
    except Exception as e:
        logger.warning(f"Static memory retrieval failed: {e}")
        static = []

    try:
        dynamic = retrieve_dynamic_memories(session_id, query=query, limit=10)
    except Exception as e:
        logger.warning(f"Dynamic memory retrieval failed: {e}")
        dynamic = []

    # NOTE: pending_review is NO LONGER recorded here.
    # Tool-call path (retrieve_memory) does NOT mark pending review.
    # retrieve_memory() is now the tool path (hybrid 3-channel, FSRS re-rank).
    # Use retrieve_for_context() for system-prompt injection (semantic-only, no pending_review).
    # Pending review is handled by memory_review.review_memory() called explicitly.

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



def _format_static_context(static: list[dict]) -> str:
    """
    Format static (semantic) memories for system prompt injection.
    Clean output — includes category for clarity.
    Returns empty string if no facts.
    """
    if not static:
        return ""
    parts = []
    for mem in static[:10]:
        entity = mem.get("entity", "User")
        relation = mem.get("relation", "unknown")
        target = mem.get("target", mem.get("content", ""))
        category = mem.get("category", "unknown")
        # Format: "- [category] entity relation target"
        parts.append(f"- [{category}] {entity} {relation} {target}")
    return "\n".join(parts)


def retrieve_for_context(session_id: int, query: str | None = None, limit: int = 10) -> tuple[list[int], str]:
    """
    Retrieve ONLY static semantic memories for pre-LLM system prompt injection.
    Does NOT mark facts as pending_review — this is the "clean" path
    for context building, not tool-use retrieval.
    plast-mem equivalent: POST /api/v0/context_pre_retrieve

    Returns:
        (static_ids, context_text) — IDs for caller to mark as pending_review if desired
    """
    try:
        static = retrieve_static_memories(query=query, limit=limit)
    except Exception as e:
        logger.warning(f"retrieve_for_context failed: {e}")
        return [], ""
    ids = [m["id"] for m in static]
    return ids, _format_static_context(static)


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


# ═════════════════════════════════════════════════════════════════════════════
# ASYNC FUNCTIONS (for FastAPI routes)
# ═════════════════════════════════════════════════════════════════════════════


async def retrieve_static_memories_async(query=None, limit=15):
    """
    Async version of retrieve_static_memories.
    3-channel hybrid: vector + trigram + tsvector, merged via RRF.
    """
    if not query:
        results = await get_facts_by_session_async(session_id=None, fact_type=FACT_TYPE_STATIC, limit=limit)
        parsed = [_parse_fact_content(r) for r in results]
        parsed = sorted(parsed, key=lambda x: x["score"], reverse=True)[:limit]
        if parsed:
            await update_last_accessed_async([m["id"] for m in parsed])
        return parsed

    query_vec = _embed_query(query)
    keyword = query.strip()

    # Channel 1: vector (pgvector)
    vec_results = await search_similar_async(
        embedding=query_vec,
        fact_type=FACT_TYPE_STATIC,
        limit=limit,
    ) if query_vec else []

    # Channel 2: trigram fuzzy (pg_trgm) - still sync, runs in thread
    trgm_results = search_trgm(
        query=keyword,
        fact_type=FACT_TYPE_STATIC,
        limit=limit,
    )

    # Channel 3: tsvector full-text - still sync
    tsv_results = search_tsv(
        query=keyword,
        fact_type=FACT_TYPE_STATIC,
        limit=limit,
    )

    # Merge via RRF
    channels = {
        "vector": vec_results,
        "trigram": trgm_results,
        "tsvector": tsv_results,
    }
    merged = _hybrid_rrf_merge(channels, k=60)

    if not merged:
        return []

    seen, parsed = set(), []
    for r in merged:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        parsed.append(_parse_fact_content(r))

    parsed = parsed[:limit]

    if parsed:
        await update_last_accessed_async([m["id"] for m in parsed])

    return parsed


async def retrieve_dynamic_memories_async(session_id: int, query=None, limit=10):
    """
    Async version of retrieve_dynamic_memories.
    3-channel hybrid: vector + trigram + tsvector, merged via RRF.
    """
    if not query:
        all_dynamic = await get_facts_by_session_async(session_id=session_id, fact_type=FACT_TYPE_DYNAMIC, limit=limit * 3)
        results = [
            r for r in all_dynamic
            if r.get("metadata", {}).get("source_table") == "episodic_memories"
        ][:limit]
        parsed = [_parse_fact_content(r) for r in results]
        parsed = sorted(parsed, key=lambda x: x["score"], reverse=True)[:limit]
        if parsed:
            await update_last_accessed_async([m["id"] for m in parsed])
        return parsed

    query_vec = _embed_query(query)
    keyword = query.strip()

    # Channel 1: vector (pgvector)
    vec_results = await search_similar_async(
        embedding=query_vec,
        session_id=session_id,
        fact_type=FACT_TYPE_DYNAMIC,
        metadata_filter={"source_table": "episodic_memories"},
        limit=limit,
    ) if query_vec else []

    # Channel 2: trigram fuzzy - still sync
    trgm_results = search_trgm(
        query=keyword,
        session_id=session_id,
        fact_type=FACT_TYPE_DYNAMIC,
        limit=limit,
    )

    # Channel 3: tsvector full-text - still sync
    tsv_results = search_tsv(
        query=keyword,
        session_id=session_id,
        fact_type=FACT_TYPE_DYNAMIC,
        limit=limit,
    )

    # Merge via RRF
    channels = {
        "vector": vec_results,
        "trigram": trgm_results,
        "tsvector": tsv_results,
    }
    merged = _hybrid_rrf_merge(channels, k=60)

    if not merged:
        return []

    seen, parsed = set(), []
    for r in merged:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        parsed.append(_parse_fact_content(r))

    parsed = parsed[:limit]

    if parsed:
        await update_last_accessed_async([m["id"] for m in parsed])

    return parsed


async def retrieve_memory_async(session_id: int, query=None):
    """
    Async version of retrieve_memory.
    Main retrieval entry point.
    """
    try:
        static = await retrieve_static_memories_async(query=query, limit=15)
    except Exception as e:
        logger.warning(f"Static memory retrieval async failed: {e}")
        static = []

    try:
        dynamic = await retrieve_dynamic_memories_async(session_id, query=query, limit=10)
    except Exception as e:
        logger.warning(f"Dynamic memory retrieval async failed: {e}")
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


async def retrieve_for_context_async(session_id: int, query: str | None = None, limit: int = 10) -> tuple[list[int], str]:
    """
    Async version of retrieve_for_context.
    Retrieve ONLY static semantic memories for pre-LLM system prompt injection.
    """
    try:
        static = await retrieve_static_memories_async(query=query, limit=limit)
    except Exception as e:
        logger.warning(f"retrieve_for_context_async failed: {e}")
        return [], ""
    ids = [m["id"] for m in static]
    return ids, _format_static_context(static)
