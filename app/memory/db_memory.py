# FILE: app/memory/db_memory.py
# DESCRIPTION: Unified memory CRUD layer over PostgreSQL semantic_facts table.
#             All memory operations (semantic, episodic, segment) go through here.
#             No SQLAlchemy ORM — pure psycopg v3 raw SQL for vector friendliness.
#
# Schema (aligned with plast-mem):
#   semantic_facts (
#     id             SERIAL PRIMARY KEY,
#     session_id     INTEGER,
#     fact_type      VARCHAR(20)  -- 'static' | 'dynamic'
#     content        TEXT,
#     embedding      VECTOR(4096), -- pgvector, NULL allowed
#     metadata       JSONB,        -- carries per-type fields
#     valid_at       TIMESTAMP,    -- when fact became true (plast-mem pattern)
#     invalid_at     TIMESTAMP,    -- when fact became false (soft delete)
#     created_at     TIMESTAMP DEFAULT NOW(),
#     last_accessed  TIMESTAMP DEFAULT NOW()
#   )
#
# Temporal Validity (plast-mem pattern):
#   - valid_at: set on creation (when fact becomes true)
#   - invalid_at: set when contradicted (soft delete)
#   - Active facts: invalid_at IS NULL
#   - Semantic facts use temporal validity (no FSRS decay)
#   - Episodic facts use FSRS decay (stored in metadata)
#
# metadata carries per-type data:
#   - static (semantic): { confidence, importance, entity, relation, target,
#                          category, source_table, access_count }
#   - dynamic (episodic): { importance, stability, difficulty, surprise_level,
#                          title, summary, source_table, access_count }
#   - dynamic (segment): { importance, start_message_id, end_message_id,
#                          source_table, access_count }

from __future__ import annotations

import logging
import math
from datetime import datetime

from psycopg.types.json import Json

from app.database import (
    PgSession, pg_fetchone, pg_fetchall, pg_execute,
    # Async versions
    AsyncPgSession, pg_fetchone_async, pg_fetchall_async, pg_execute_async,
)
from app.memory.db_memory_queries import (
    # Constants
    FACT_TYPE_STATIC, FACT_TYPE_DYNAMIC, EMBEDDING_DIM,
    # Vector helpers
    normalize_vector, vector_literal,
    # Static SQL
    SQL_FACT_DUP_CHECK_BY_CONTENT, SQL_FACT_INSERT,
    SQL_FACT_SELECT_BY_ID, SQL_FACT_SELECT_STATIC_LIMIT,
    SQL_FACT_UPDATE_METADATA, SQL_FACT_INVALIDATE,
    SQL_FACT_UPDATE_DECAY,
    SQL_FACT_DECAY_FETCH_FOR_SESSION, SQL_FACT_DECAY_FETCH_GLOBAL,
    # Builders
    build_metadata_conditions,
    build_search_similar_query, build_search_trgm_query,
    build_search_tsv_query, build_facts_by_session_query,
    build_count_query, build_update_last_accessed_query,
)

logger = logging.getLogger(__name__)


# ── Embedding helpers ─────────────────────────────────────────────────────────
def _embed_text(text: str) -> list[float] | None:
    """Embed text via Chutes API. Returns None on failure."""
    try:
        from app.memory.embedder import embed_text as _embed
        return _embed(text)
    except Exception as e:
        logger.warning(f"Embed failed: {e}")
        return None


# ═════════════════════════════════════════════════════════════════════════════
# SYNC FUNCTIONS (legacy compatibility)
# ═════════════════════════════════════════════════════════════════════════════

# ── Save / Insert ─────────────────────────────────────────────────────────────
def save_fact(
    session_id: int | None,
    content: str,
    embedding: list[float] | None,
    fact_type: str = FACT_TYPE_STATIC,
    metadata: dict | None = None,
    category: str | None = None,
) -> int | None:
    """
    Insert a new fact into semantic_facts.

    Returns the new row id, or None on failure.
    """
    meta = dict(metadata) if metadata else {}
    if "session_id" not in meta:
        meta["session_id"] = session_id
    if category:
        meta["category"] = category

    norm_vec = normalize_vector(embedding) if embedding else None

    if norm_vec is not None and len(norm_vec) != EMBEDDING_DIM:
        raise ValueError(f"Embedding dimension must be {EMBEDDING_DIM}, got {len(norm_vec)}")

    vec_literal = vector_literal(norm_vec)

    # Reject exact content duplicates (same fact_type + content + not invalidated)
    try:
        dup_check = pg_fetchone(SQL_FACT_DUP_CHECK_BY_CONTENT, (fact_type, content))
        if dup_check:
            logger.debug(f"save_fact: duplicate content found, rejecting id={dup_check['id']}")
            return dup_check["id"]
    except Exception as e:
        logger.warning(f"save_fact: dup check failed: {e}")

    try:
        with PgSession() as s:
            row = s.execute_returning(SQL_FACT_INSERT, (
                fact_type,
                content,
                vec_literal,
                Json(meta),
                datetime.now(),
                datetime.now(),
                datetime.now(),
            ))
            return row["id"] if row else None
    except Exception as e:
        logger.error(f"save_fact failed: {e}")
        return None


# ── Vector Search ─────────────────────────────────────────────────────────────
def search_similar(
    embedding: list[float],
    session_id: int | None = None,
    fact_type: str | None = None,
    limit: int = 15,
    max_distance: float = 1.5,
    metadata_filter: dict | None = None,
    category: str | None = None,
) -> list[dict]:
    """
    ANN search via PostgreSQL <=> (cosine) operator.
    Distance is computed once via CTE and used in WHERE and ORDER BY.

    Returns list of dicts: {id, content, fact_type, metadata,
                            last_accessed, created_at, distance}
    """
    try:
        norm_vec = normalize_vector(embedding)
        if not norm_vec:
            logger.warning("search_similar: normalized vector is empty")
            return []

        vec_literal = vector_literal(norm_vec)
        if not vec_literal:
            return []

        # Build conditions using the query builder
        conditions, params = build_metadata_conditions(
            session_id=session_id,
            fact_type=fact_type,
            category=category,
            metadata_filter=metadata_filter,
        )

        query = build_search_similar_query(vec_literal, conditions)
        params.extend([max_distance, limit])

        results = pg_fetchall(query, params)
        return results if results else []

    except Exception as e:
        logger.exception(f"search_similar EXCEPTION: {type(e).__name__}: {e}")
        return []


# ── Keyword / Trigram Search ──────────────────────────────────────────────────
def search_trgm(
    query: str,
    session_id: int | None = None,
    fact_type: str | None = None,
    limit: int = 15,
    min_similarity: float = 0.3,
    metadata_filter: dict | None = None,
    category: str | None = None,
) -> list[dict]:
    """
    Fuzzy keyword search via pg_trgm similarity operator.

    Uses the GIN index on content (gin_trgm_ops) for fast trigram matching.
    Ranks by similarity score descending.

    Returns list of dicts: {id, content, fact_type, metadata,
                            last_accessed, created_at, similarity}
    """
    if not query or not query.strip():
        return []

    conditions, params = build_metadata_conditions(
        session_id=session_id,
        fact_type=fact_type,
        category=category,
        metadata_filter=metadata_filter,
    )

    sql = build_search_trgm_query(conditions)
    # Params order: query, query, min_similarity, limit (query appears twice for similarity() calls)
    params_with_query = [query] + params + [query, min_similarity, limit]

    try:
        results = pg_fetchall(sql, params_with_query)
        return results if results else []
    except Exception as e:
        logger.exception(f"search_trgm EXCEPTION: {type(e).__name__}: {e}")
        return []


# ── Full-Text Search ─────────────────────────────────────────────────────────
def search_tsv(
    query: str,
    session_id: int | None = None,
    fact_type: str | None = None,
    limit: int = 15,
    metadata_filter: dict | None = None,
    category: str | None = None,
    rank_weight: float = 0.3,
) -> list[dict]:
    """
    PostgreSQL full-text search via tsvector column.

    Uses the GIN index on the auto-generated tsv column for fast
    ts_headline and ts_rank scoring.

    Args:
        query: plain-text search query (converted to tsquery internally)
        rank_weight: how much ts_rank contributes to final score vs recency

    Returns list of dicts: {id, content, fact_type, metadata,
                            last_accessed, created_at, ts_rank}
    """
    if not query or not query.strip():
        return []

    conditions, params = build_metadata_conditions(
        session_id=session_id,
        fact_type=fact_type,
        category=category,
        metadata_filter=metadata_filter,
    )

    sql = build_search_tsv_query(conditions)
    # Params order: query (ts_rank), query (WHERE), ...conditions..., limit
    params_with_query = [query, query] + params + [limit]

    try:
        results = pg_fetchall(sql, params_with_query)
        return results if results else []
    except Exception as e:
        logger.error(f"search_tsv EXCEPTION: {type(e).__name__}: {e}")
        return []


# ── Retrieval ─────────────────────────────────────────────────────────────────
def get_fact_by_id(id: int) -> dict | None:
    return pg_fetchone(SQL_FACT_SELECT_BY_ID, (id,))


def get_facts_by_session(
    session_id: int | None,
    fact_type: str | None = None,
    limit: int = 100,
) -> list[dict]:
    # Static facts are GLOBAL - no session_id filter
    if fact_type == FACT_TYPE_STATIC:
        return pg_fetchall(SQL_FACT_SELECT_STATIC_LIMIT, (fact_type, limit))
    # Dynamic facts: build conditions
    conditions, params = build_metadata_conditions(session_id=session_id, fact_type=fact_type)
    params.append(limit)
    query = build_facts_by_session_query(conditions, default_dynamic=True)
    return pg_fetchall(query, params)


def count_facts(fact_type: str | None = None, session_id: int | None = None) -> int:
    conditions, params = build_metadata_conditions(fact_type=fact_type, session_id=session_id)
    query = build_count_query(conditions)
    row = pg_fetchone(query, params)
    return row["cnt"] if row else 0


# ── Update / Access Tracking ───────────────────────────────────────────────────
def update_last_accessed(ids: list[int]) -> int:
    """Batch update last_accessed timestamp. Returns rows updated."""
    if not ids:
        return 0
    now = datetime.now()
    query = build_update_last_accessed_query(len(ids))
    try:
        with PgSession() as s:
            s.execute(query, (now,) + tuple(ids))
        return len(ids)
    except Exception as e:
        logger.error(f"update_last_accessed failed: {e}")
        return 0


def increment_importance(id: int, delta: float = 0.05, cap: float = 1.0) -> bool:
    """Increment importance, capped at `cap`."""
    try:
        meta_row = pg_fetchone("SELECT metadata FROM semantic_facts WHERE id=%s", (id,))
        if not meta_row:
            return False
        meta = meta_row["metadata"] or {}
        current = meta.get("importance") or 0.5
        meta["importance"] = min(current + delta, cap)
        meta["access_count"] = (meta.get("access_count") or 0) + 1
        pg_execute(
            SQL_FACT_UPDATE_METADATA,
            (datetime.now(), Json(meta), id),
        )
        return True
    except Exception as e:
        logger.error(f"increment_importance failed: {e}")
        return False


# ── FSRS Decay ────────────────────────────────────────────────────────────────
def decay_facts(
    session_id: int | None = None, fact_type: str = FACT_TYPE_DYNAMIC
) -> int:
    """
    Apply FSRS-style decay to episodic/dynamic facts.

    Decay formula:
        importance = importance * exp(-hours_since_last_access / stability)
        stability = 24 * (1 + access_count * 0.5)

    Does NOT affect static (semantic) facts — they use invalid_at temporal validity.

    Returns the number of facts decayed.
    """
    try:
        now = datetime.now()

        if session_id is not None:
            rows = pg_fetchall(SQL_FACT_DECAY_FETCH_FOR_SESSION, (fact_type, session_id))
        else:
            rows = pg_fetchall(SQL_FACT_DECAY_FETCH_GLOBAL, (fact_type,))

        count = 0
        for row in rows:
            meta = row["metadata"] or {}
            last_accessed = row["last_accessed"]

            importance = meta.get("importance") or 0.5
            access_count = meta.get("access_count") or 0

            if last_accessed:
                if isinstance(last_accessed, str):
                    try:
                        last_accessed = datetime.strptime(
                            last_accessed, "%Y-%m-%d %H:%M:%S.%f"
                        )
                    except ValueError:
                        last_accessed = datetime.strptime(
                            last_accessed, "%Y-%m-%d %H:%M:%S"
                        )
                hours = (now - last_accessed).total_seconds() / 3600.0
            else:
                hours = 0

            # FSRS decay
            stability_val = 24.0 * (1.0 + access_count * 0.5)
            new_importance = (
                importance * math.exp(-hours / stability_val)
                if stability_val > 0
                else importance
            )

            meta["importance"] = new_importance
            meta["stability"] = stability_val

            pg_execute(
                SQL_FACT_UPDATE_DECAY,
                (Json(meta), now, row["id"]),
            )
            count += 1

        return count

    except Exception as e:
        logger.error(f"decay_facts failed: {e}")
        return 0


# ── Soft Delete ───────────────────────────────────────────────────────────────
def invalidate_fact(id: int) -> bool:
    """
    Soft-delete a fact by setting invalid_at = NOW().
    Does NOT hard-delete — preserves history for audit.
    """
    try:
        pg_execute(
            SQL_FACT_INVALIDATE,
            (datetime.now(), datetime.now(), id),
        )
        return True
    except Exception as e:
        logger.error(f"invalidate_fact failed: {e}")
        return False


# ═════════════════════════════════════════════════════════════════════════════
# ASYNC FUNCTIONS (for FastAPI routes)
# ═════════════════════════════════════════════════════════════════════════════

async def save_fact_async(
    session_id: int | None,
    content: str,
    embedding: list[float] | None,
    fact_type: str = FACT_TYPE_STATIC,
    metadata: dict | None = None,
    category: str | None = None,
) -> int | None:
    """Async version of save_fact."""
    meta = dict(metadata) if metadata else {}
    if "session_id" not in meta:
        meta["session_id"] = session_id
    if category:
        meta["category"] = category

    norm_vec = normalize_vector(embedding) if embedding else None

    if norm_vec is not None and len(norm_vec) != EMBEDDING_DIM:
        raise ValueError(f"Embedding dimension must be {EMBEDDING_DIM}, got {len(norm_vec)}")

    vec_literal = vector_literal(norm_vec)

    try:
        dup_check = await pg_fetchone_async(SQL_FACT_DUP_CHECK_BY_CONTENT, (fact_type, content))
        if dup_check:
            logger.debug(f"save_fact_async: duplicate content found, rejecting id={dup_check['id']}")
            return dup_check["id"]
    except Exception as e:
        logger.warning(f"save_fact_async: dup check failed: {e}")

    try:
        async with AsyncPgSession() as s:
            row = await s.execute_returning(SQL_FACT_INSERT, (
                fact_type,
                content,
                vec_literal,
                Json(meta),
                datetime.now(),
                datetime.now(),
                datetime.now(),
            ))
            return row["id"] if row else None
    except Exception as e:
        logger.error(f"save_fact_async failed: {e}")
        return None


async def search_similar_async(
    embedding: list[float],
    session_id: int | None = None,
    fact_type: str | None = None,
    limit: int = 15,
    max_distance: float = 1.5,
    metadata_filter: dict | None = None,
    category: str | None = None,
) -> list[dict]:
    """Async version of search_similar."""
    try:
        norm_vec = normalize_vector(embedding)
        if not norm_vec:
            return []

        vec_literal = vector_literal(norm_vec)
        if not vec_literal:
            return []

        conditions, params = build_metadata_conditions(
            session_id=session_id,
            fact_type=fact_type,
            category=category,
            metadata_filter=metadata_filter,
        )

        query = build_search_similar_query(vec_literal, conditions)
        params.extend([max_distance, limit])

        results = await pg_fetchall_async(query, params)
        return results if results else []

    except Exception as e:
        logger.error(f"search_similar_async EXCEPTION: {e}")
        return []


async def get_facts_by_session_async(
    session_id: int | None,
    fact_type: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Async version of get_facts_by_session."""
    if fact_type == FACT_TYPE_STATIC:
        return await pg_fetchall_async(SQL_FACT_SELECT_STATIC_LIMIT, (fact_type, limit))
    conditions, params = build_metadata_conditions(session_id=session_id, fact_type=fact_type)
    params.append(limit)
    query = build_facts_by_session_query(conditions, default_dynamic=True)
    return await pg_fetchall_async(query, params)


async def update_last_accessed_async(ids: list[int]) -> int:
    """Async version of update_last_accessed."""
    if not ids:
        return 0
    now = datetime.now()
    query = build_update_last_accessed_query(len(ids))
    try:
        async with AsyncPgSession() as s:
            await s.execute(query, (now,) + tuple(ids))
        return len(ids)
    except Exception as e:
        logger.error(f"update_last_accessed_async failed: {e}")
        return 0


async def invalidate_fact_async(id: int) -> bool:
    """Async version of invalidate_fact."""
    try:
        await pg_execute_async(
            SQL_FACT_INVALIDATE,
            (datetime.now(), datetime.now(), id),
        )
        return True
    except Exception as e:
        logger.error(f"invalidate_fact_async failed: {e}")
        return False
