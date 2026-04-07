# FILE: app/memory/db_memory.py
# DESCRIPTION: Unified memory CRUD layer over PostgreSQL semantic_facts table.
#             All memory operations (semantic, episodic, segment) go through here.
#             No SQLAlchemy ORM — pure psycopg2 raw SQL for vector friendliness.
#
# Schema:
#   semantic_facts (
#     id             SERIAL PRIMARY KEY,
#     session_id     INTEGER,
#     fact_type      VARCHAR(20)  -- 'static' | 'dynamic'
#     content        TEXT,
#     embedding      VECTOR(1024), -- pgvector, NULL allowed
#     metadata       JSONB,        -- carries per-type fields
#     created_at     TIMESTAMP DEFAULT NOW(),
#     last_accessed  TIMESTAMP DEFAULT NOW()
#   )
#
# metadata carries per-type data:
#   - static (semantic): { confidence, importance, entity, relation, target,
#                          source_table, access_count }
#   - dynamic (episodic): { importance, emotional_weight, summary, source_table,
#                          access_count }
#   - dynamic (segment): { importance, start_message_id, end_message_id,
#                          source_table, access_count }

from __future__ import annotations

import math
from datetime import datetime

from app.db_pg import PgSession, pg_fetchone, pg_fetchall, pg_execute
from psycopg2.extras import Json


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
            (fact_type, content, embedding, metadata, created_at, last_accessed)
        VALUES (%s, %s, %s::vector, %s, %s, %s)
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


def get_active_facts(
    session_id: int | None = None,
    fact_type: str | None = None,
    category: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """
    Get active (non-deleted) facts only.
    Adds WHERE invalid_at IS NULL to all reads.
    """
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

    params.append(limit)
    where = " AND ".join(conditions)
    return pg_fetchall(
        f"SELECT * FROM semantic_facts WHERE {where} LIMIT %s",
        params,
    )


# ── Delete ────────────────────────────────────────────────────────────────────
def delete_fact(id: int) -> bool:
    """Hard-delete a single fact by id. Prefer invalidate_fact() for soft delete."""
    try:
        pg_execute("DELETE FROM semantic_facts WHERE id=%s", (id,))
        return True
    except Exception as e:
        print(f"[db_memory] delete_fact failed: {e}")
        return False


def delete_facts_by_session(session_id: int, fact_type: str | None = None) -> int:
    """Delete all facts for a session. Returns count deleted."""
    params = [session_id]
    extra = ""
    if fact_type:
        extra = " AND fact_type = %s"
        params.append(fact_type)
    try:
        with PgSession() as s:
            s.execute(f"DELETE FROM semantic_facts WHERE (metadata->>'session_id')::int=%s{extra}", params)
            return s.conn.affected_rows if hasattr(s.conn, "affected_rows") else 0
    except Exception:
        return 0


# ── Decay (FSRS-style) ─────────────────────────────────────────────────────────
def decay_facts(session_id: int | None = None, fact_type: str | None = None) -> int:
    """
    Apply importance decay to facts.
    importance *= exp(-hours_since_last_access / stability)
    stability = 24 * (1 + access_count * 0.5) for semantic
                48 * (1 + access_count * 0.3) for episodic
    """
    conditions = []
    params = []
    if session_id is not None:
        conditions.append("(metadata->>'session_id')::int = %s")
        params.append(session_id)
    if fact_type:
        conditions.append("fact_type = %s")
        params.append(fact_type)
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    where_metadata = "AND metadata->>'source_table' = 'episodic_memories'" if fact_type == FACT_TYPE_DYNAMIC else ""

    # Get all facts to decay
    facts = pg_fetchall(f"SELECT id, metadata FROM semantic_facts {where} {where_metadata}", params)
    updated = 0
    now = datetime.now()

    for fact in facts:
        meta = fact.get("metadata") or {}
        last_accessed_str = fact.get("last_accessed")
        access_count = meta.get("access_count") or 0

        if isinstance(last_accessed_str, str):
            try:
                last_dt = datetime.strptime(last_accessed_str, '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                try:
                    last_dt = datetime.strptime(last_accessed_str, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    last_dt = now
        elif last_accessed_str:
            last_dt = last_accessed_str
        else:
            last_dt = now

        hours = max((now - last_dt).total_seconds() / 3600.0, 0.0)
        stability = 24.0 * (1 + access_count * 0.5)
        decay = math.exp(-hours / stability)
        current_importance = meta.get("importance") or 0.5
        new_importance = max(current_importance * decay, 0.01)
        meta["importance"] = new_importance

        try:
            pg_execute(
                "UPDATE semantic_facts SET metadata=%s, last_accessed=%s WHERE id=%s",
                (Json(meta), now, fact["id"]),
            )
            updated += 1
        except Exception as e:
            print(f"[db_memory] decay id={fact['id']} failed: {e}")

    return updated


# ── Stats ─────────────────────────────────────────────────────────────────────
def get_memory_stats(session_id: int | None = None) -> dict:
    """Return memory statistics."""
    total = count_facts(session_id=session_id)
    # Static facts are GLOBAL - don't filter by session_id
    static_count = count_facts(fact_type=FACT_TYPE_STATIC)
    # Dynamic facts are session-scoped
    dynamic_count = count_facts(fact_type=FACT_TYPE_DYNAMIC, session_id=session_id)

    return {
        "total": total,
        "static": static_count,
        "dynamic": dynamic_count,
    }
