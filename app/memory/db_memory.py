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
#     embedding      VECTOR(1024), -- pgvector, NULL allowed
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

import math
from datetime import datetime

from psycopg.types.json import Json

from app.db_pg import (
    PgSession, pg_fetchone, pg_fetchall, pg_execute,
    # Async versions
    AsyncPgSession, pg_fetchone_async, pg_fetchall_async, pg_execute_async,
)


# ── Enums ─────────────────────────────────────────────────────────────────────
FACT_TYPE_STATIC  = "static"
FACT_TYPE_DYNAMIC = "dynamic"

# ── Embedding helpers ─────────────────────────────────────────────────────────
def _normalize(vec) -> list[float]:
    """Normalize vector to unit length for cosine similarity."""
    if not vec:
        return []
    try:
        norm = sum(x * x for x in vec) ** 0.5
        if norm == 0:
            return []
        return [x / norm for x in vec]
    except (TypeError, ValueError):
        return []


def _embed_text(text: str) -> list[float] | None:
    """Embed text via Chutes API. Returns None on failure."""
    try:
        from app.memory.embedder import embed_text as _embed
        return _embed(text)
    except Exception as e:
        print(f"[db_memory] Embed failed: {e}")
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

    norm_vec = _normalize(embedding) if embedding else None

    if norm_vec is not None and len(norm_vec) != 1024:
        raise ValueError(f"Embedding dimension must be 1024, got {len(norm_vec)}")

    # Build pgvector literal directly — safe: norm_vec is list[float] with no user input
    vec_literal = ("[" + ",".join(str(x) for x in norm_vec) + "]") if norm_vec is not None else None

    # Reject exact content duplicates (same fact_type + content + not invalidated)
    try:
        dup_check = pg_fetchone(
            "SELECT id FROM semantic_facts WHERE fact_type=%s AND content=%s AND invalid_at IS NULL LIMIT 1",
            (fact_type, content),
        )
        if dup_check:
            print(f"[db_memory] save_fact: duplicate content found, rejecting id={dup_check['id']}")
            return dup_check["id"]
    except Exception as e:
        print(f"[db_memory] save_fact: dup check failed: {e}")

    query = """
        INSERT INTO semantic_facts
            (fact_type, content, embedding, metadata, valid_at, created_at, last_accessed)
        VALUES (%s, %s, %s::vector, %s, %s, %s, %s)
        RETURNING id
    """

    try:
        with PgSession() as s:
            row = s.execute_returning(query, (
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
        print(f"[db_memory] save_fact failed: {e}")
        return None


def upsert_fact(
    session_id: int | None,
    content: str,
    embedding: list[float] | None,
    fact_type: str = FACT_TYPE_STATIC,
    metadata: dict | None = None,
) -> int | None:
    """
    Insert a fact, but first check for near-duplicate using vector distance.
    If a row with cosine distance < 0.05 exists, reinforce it instead of inserting.
    Returns: (existing_id, reinforced=True) or (new_id, reinforced=False)
    """
    if embedding:
        try:
            existing = search_similar(
                embedding=embedding,
                session_id=session_id,
                fact_type=fact_type,
                limit=1,
                max_distance=0.05,  # cosine similarity threshold
            )
        except Exception as e:
            print(f"[db_memory] upsert_fact search_similar error: {e}")
            existing = []
        if not existing or len(existing) == 0:
            return None, False
        e = existing[0]
        # Reinforce existing
        meta = e.get("metadata") or {}
        new_confidence = min((meta.get("confidence") or 0.5) + 0.1, 1.0)
        new_access_count = (meta.get("access_count") or 0) + 1
        meta["confidence"] = new_confidence
        meta["access_count"] = new_access_count
        pg_execute(
            "UPDATE semantic_facts SET last_accessed=%s, metadata=%s WHERE id=%s",
            (datetime.now(), Json(meta), e["id"]),
        )
        return e["id"], True

    new_id = save_fact(session_id, content, embedding, fact_type, metadata)
    return new_id, False


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
        norm_vec = _normalize(embedding)
        if not norm_vec:
            print("[db_memory] search_similar: normalized vector is empty")
            return []

        vec_literal = "[" + ",".join(str(x) for x in norm_vec) + "]"

        # Build conditions and params
        conditions = ["embedding IS NOT NULL"]
        params: list = []

        if session_id is not None:
            conditions.append("(metadata->>'session_id')::int = %s")
            params.append(session_id)

        if fact_type:
            conditions.append("fact_type = %s")
            params.append(fact_type)

        if category:
            conditions.append("(metadata->>'category') = %s")
            params.append(category)

        if metadata_filter:
            for key, val in metadata_filter.items():
                conditions.append("metadata->>%s = %s")
                params.append(key)
                params.append(val)

        cond_sql = " AND ".join(conditions)

        # NOTE: vec_literal is interpolated directly as a string literal.
        # It is a pure float list — no SQL injection risk.
        query = f"""
            WITH searched AS (
                SELECT id, fact_type, content, metadata,
                       last_accessed, created_at,
                       (embedding <=> '{vec_literal}'::vector) AS distance
                FROM semantic_facts
                WHERE {cond_sql}
                  AND (embedding <=> '{vec_literal}'::vector) < %s
            )
            SELECT id, fact_type, content, metadata,
                   last_accessed, created_at, distance
            FROM searched
            ORDER BY distance
            LIMIT %s
        """
        params.extend([max_distance, limit])

        results = pg_fetchall(query, params)
        return results if results else []

    except Exception as e:
        import traceback
        print(f"[db_memory] search_similar EXCEPTION: {type(e).__name__}: {e}")
        traceback.print_exc()
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

    conditions = ["invalid_at IS NULL"]
    params: list = []

    if session_id is not None:
        conditions.append("(metadata->>'session_id')::int = %s")
        params.append(session_id)

    if fact_type:
        conditions.append("fact_type = %s")
        params.append(fact_type)

    if category:
        conditions.append("(metadata->>'category') = %s")
        params.append(category)

    if metadata_filter:
        for key, val in metadata_filter.items():
            conditions.append("metadata->>%s = %s")
            params.append(key)
            params.append(val)

    cond_sql = " AND ".join(conditions)
    params.append(min_similarity)
    params.append(limit)
    params.insert(1, query)

    sql = f"""
        SELECT id, fact_type, content, metadata,
               last_accessed, created_at,
               similarity(content, %s) AS similarity
        FROM semantic_facts
        WHERE {cond_sql}
          AND similarity(content, %s) >= %s::real
        ORDER BY similarity DESC
        LIMIT %s
    """

    try:
        results = pg_fetchall(sql, [query] + params)
        return results if results else []
    except Exception as e:
        import traceback
        print(f"[db_memory] search_trgm EXCEPTION: {type(e).__name__}: {e}")
        traceback.print_exc()
        return []


# DEPRECATED: Not used. Retrieval now uses search_similar + search_trgm + search_tsv (RRF merge).
def search_trgm_keywords(
    keyword: str,
    session_id: int | None = None,
    fact_type: str | None = None,
    limit: int = 15,
    metadata_filter: dict | None = None,
    category: str | None = None,
) -> list[dict]:
    """
    Substring/keyword search via ILIKE — fallback when trigram similarity
    is too loose (e.g. short keywords like "python" score low on similarity).

    Uses the GIN index for fast ILIKE scans.

    Returns list of dicts: {id, content, fact_type, metadata,
                            last_accessed, created_at}
    """
    if not keyword or not keyword.strip():
        return []

    conditions = ["invalid_at IS NULL", "content ILIKE %s"]
    params: list = [f"%{keyword}%"]

    if session_id is not None:
        conditions.append("(metadata->>'session_id')::int = %s")
        params.append(session_id)

    if fact_type:
        conditions.append("fact_type = %s")
        params.append(fact_type)

    if category:
        conditions.append("(metadata->>'category') = %s")
        params.append(category)

    if metadata_filter:
        for key, val in metadata_filter.items():
            conditions.append("metadata->>%s = %s")
            params.append(key)
            params.append(val)

    cond_sql = " AND ".join(conditions)
    params.append(limit)

    sql = f"""
        SELECT id, fact_type, content, metadata,
               last_accessed, created_at
        FROM semantic_facts
        WHERE {cond_sql}
        ORDER BY created_at DESC
        LIMIT %s
    """

    try:
        results = pg_fetchall(sql, params)
        return results if results else []
    except Exception as e:
        print(f"[db_memory] search_trgm_keywords EXCEPTION: {type(e).__name__}: {e}")
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

    conditions = ["invalid_at IS NULL", "tsv @@ plainto_tsquery('english', %s)"]
    params: list = [query]

    if session_id is not None:
        conditions.append("(metadata->>'session_id')::int = %s")
        params.append(session_id)

    if fact_type:
        conditions.append("fact_type = %s")
        params.append(fact_type)

    if category:
        conditions.append("(metadata->>'category') = %s")
        params.append(category)

    if metadata_filter:
        for key, val in metadata_filter.items():
            conditions.append("metadata->>%s = %s")
            params.append(key)
            params.append(val)

    cond_sql = " AND ".join(conditions)
    params.append(limit)

    sql = f"""
        SELECT id, fact_type, content, metadata,
               last_accessed, created_at,
               ts_rank(tsv, plainto_tsquery('english', %s)) AS ts_rank
        FROM semantic_facts
        WHERE {cond_sql}
        ORDER BY ts_rank DESC, created_at DESC
        LIMIT %s
    """

    try:
        results = pg_fetchall(sql, [query] + params)
        return results if results else []
    except Exception as e:
        print(f"[db_memory] search_tsv EXCEPTION: {type(e).__name__}: {e}")
        return []


# ── Retrieval ─────────────────────────────────────────────────────────────────
def get_fact_by_id(id: int) -> dict | None:
    return pg_fetchone(
        "SELECT * FROM semantic_facts WHERE id=%s", (id,)
    )


def get_facts_by_session(
    session_id: int | None,
    fact_type: str | None = None,
    limit: int = 100,
) -> list[dict]:
    # Static facts are GLOBAL - no session_id filter
    if fact_type == "static":
        return pg_fetchall(
            "SELECT * FROM semantic_facts WHERE fact_type=%s LIMIT %s",
            (fact_type, limit),
        )
    # Dynamic facts: only filter by session_id when it is not None
    conditions, params = [], []
    if session_id is not None:
        conditions.append("(metadata->>'session_id')::int = %s")
        params.append(session_id)
    if fact_type:
        conditions.append("fact_type = %s")
        params.append(fact_type)
    params.append(limit)
    where = "WHERE " + " AND ".join(conditions) if conditions else "WHERE fact_type = 'dynamic'"
    return pg_fetchall(
        f"SELECT * FROM semantic_facts {where} LIMIT %s",
        params,
    )


def count_facts(fact_type: str | None = None, session_id: int | None = None) -> int:
    conditions = []
    params = []
    if fact_type:
        conditions.append("fact_type = %s")
        params.append(fact_type)
    if session_id is not None:
        conditions.append("(metadata->>'session_id')::int = %s")
        params.append(session_id)
    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    row = pg_fetchone(f"SELECT COUNT(*) AS cnt FROM semantic_facts {where}", params)
    return row["cnt"] if row else 0


# ── Update / Access Tracking ───────────────────────────────────────────────────
def update_last_accessed(ids: list[int]) -> int:
    """Batch update last_accessed timestamp. Returns rows updated."""
    if not ids:
        return 0
    now = datetime.now()
    ph = ",".join(["%s"] * len(ids))
    try:
        with PgSession() as s:
            s.execute(
                f"UPDATE semantic_facts SET last_accessed=%s WHERE id IN ({ph})",
                (now,) + tuple(ids),
            )
        return len(ids)
    except Exception as e:
        print(f"[db_memory] update_last_accessed failed: {e}")
        return 0


def update_fact_importance(id: int, importance: float) -> bool:
# DEPRECATED: Not used. All callers use increment_importance instead.
    """Update importance in metadata JSONB."""
    try:
        meta_row = pg_fetchone("SELECT metadata FROM semantic_facts WHERE id=%s", (id,))
        if not meta_row:
            return False
        meta = meta_row["metadata"] or {}
        meta["importance"] = importance
        pg_execute(
            "UPDATE semantic_facts SET metadata=%s WHERE id=%s",
            (Json(meta), id),
        )
        return True
    except Exception as e:
        print(f"[db_memory] update_fact_importance failed: {e}")
        return False


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
            "UPDATE semantic_facts SET last_accessed=%s, metadata=%s WHERE id=%s",
            (datetime.now(), Json(meta), id),
        )
        return True
    except Exception as e:
        print(f"[db_memory] increment_importance failed: {e}")
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
            rows = pg_fetchall(
                """
                SELECT id, metadata, last_accessed
                FROM semantic_facts
                WHERE fact_type = %s
                  AND (metadata->>'session_id')::int = %s
                  AND invalid_at IS NULL
                """,
                (fact_type, session_id),
            )
        else:
            rows = pg_fetchall(
                """
                SELECT id, metadata, last_accessed
                FROM semantic_facts
                WHERE fact_type = %s
                  AND invalid_at IS NULL
                """,
                (fact_type,),
            )

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
                "UPDATE semantic_facts SET metadata=%s, last_accessed=%s WHERE id=%s",
                (Json(meta), now, row["id"]),
            )
            count += 1

        return count

    except Exception as e:
        print(f"[db_memory] decay_facts failed: {e}")
        return 0


# ── Soft Delete ───────────────────────────────────────────────────────────────
def invalidate_fact(id: int) -> bool:
    """
    Soft-delete a fact by setting invalid_at = NOW().
    Does NOT hard-delete — preserves history for audit.
    """
    try:
        pg_execute(
            "UPDATE semantic_facts SET invalid_at=%s, last_accessed=%s WHERE id=%s",
            (datetime.now(), datetime.now(), id),
        )
        return True
    except Exception as e:
        print(f"[db_memory] invalidate_fact failed: {e}")
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

    norm_vec = _normalize(embedding) if embedding else None

    if norm_vec is not None and len(norm_vec) != 1024:
        raise ValueError(f"Embedding dimension must be 1024, got {len(norm_vec)}")

    vec_literal = ("[" + ",".join(str(x) for x in norm_vec) + "]") if norm_vec is not None else None

    try:
        dup_check = await pg_fetchone_async(
            "SELECT id FROM semantic_facts WHERE fact_type=%s AND content=%s AND invalid_at IS NULL LIMIT 1",
            (fact_type, content),
        )
        if dup_check:
            print(f"[db_memory] save_fact_async: duplicate content found, rejecting id={dup_check['id']}")
            return dup_check["id"]
    except Exception as e:
        print(f"[db_memory] save_fact_async: dup check failed: {e}")

    query = """
        INSERT INTO semantic_facts
            (fact_type, content, embedding, metadata, valid_at, created_at, last_accessed)
        VALUES (%s, %s, %s::vector, %s, %s, %s, %s)
        RETURNING id
    """

    try:
        async with AsyncPgSession() as s:
            row = await s.execute_returning(query, (
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
        print(f"[db_memory] save_fact_async failed: {e}")
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
        norm_vec = _normalize(embedding)
        if not norm_vec:
            return []

        vec_literal = "[" + ",".join(str(x) for x in norm_vec) + "]"

        conditions = ["embedding IS NOT NULL"]
        params: list = []

        if session_id is not None:
            conditions.append("(metadata->>'session_id')::int = %s")
            params.append(session_id)

        if fact_type:
            conditions.append("fact_type = %s")
            params.append(fact_type)

        if category:
            conditions.append("(metadata->>'category') = %s")
            params.append(category)

        if metadata_filter:
            for key, val in metadata_filter.items():
                conditions.append("metadata->>%s = %s")
                params.append(key)
                params.append(val)

        cond_sql = " AND ".join(conditions)

        query = f"""
            WITH searched AS (
                SELECT id, fact_type, content, metadata,
                       last_accessed, created_at,
                       (embedding <=> '{vec_literal}'::vector) AS distance
                FROM semantic_facts
                WHERE {cond_sql}
                  AND (embedding <=> '{vec_literal}'::vector) < %s
            )
            SELECT id, fact_type, content, metadata,
                   last_accessed, created_at, distance
            FROM searched
            ORDER BY distance
            LIMIT %s
        """
        params.extend([max_distance, limit])

        results = await pg_fetchall_async(query, params)
        return results if results else []

    except Exception as e:
        print(f"[db_memory] search_similar_async EXCEPTION: {e}")
        return []


async def get_facts_by_session_async(
    session_id: int | None,
    fact_type: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Async version of get_facts_by_session."""
    if fact_type == "static":
        return await pg_fetchall_async(
            "SELECT * FROM semantic_facts WHERE fact_type=%s LIMIT %s",
            (fact_type, limit),
        )
    conditions, params = [], []
    if session_id is not None:
        conditions.append("(metadata->>'session_id')::int = %s")
        params.append(session_id)
    if fact_type:
        conditions.append("fact_type = %s")
        params.append(fact_type)
    params.append(limit)
    where = "WHERE " + " AND ".join(conditions) if conditions else "WHERE fact_type = 'dynamic'"
    return await pg_fetchall_async(
        f"SELECT * FROM semantic_facts {where} LIMIT %s",
        params,
    )


async def update_last_accessed_async(ids: list[int]) -> int:
    """Async version of update_last_accessed."""
    if not ids:
        return 0
    now = datetime.now()
    ph = ",".join(["%s"] * len(ids))
    try:
        async with AsyncPgSession() as s:
            await s.execute(
                f"UPDATE semantic_facts SET last_accessed=%s WHERE id IN ({ph})",
                (now,) + tuple(ids),
            )
        return len(ids)
    except Exception as e:
        print(f"[db_memory] update_last_accessed_async failed: {e}")
        return 0


async def invalidate_fact_async(id: int) -> bool:
    """Async version of invalidate_fact."""
    try:
        await pg_execute_async(
            "UPDATE semantic_facts SET invalid_at=%s, last_accessed=%s WHERE id=%s",
            (datetime.now(), datetime.now(), id),
        )
        return True
    except Exception as e:
        print(f"[db_memory] invalidate_fact_async failed: {e}")
        return False
