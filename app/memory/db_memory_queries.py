# FILE: app/memory/db_memory_queries.py
# DESCRIPTION: Single source of truth for SQL strings and parsers used by
#              the sync (db_memory.py) and async (db_memory_async stubs)
#              memory repository layers.
#
#  Mirrors the pattern established in app/db_queries.py for the core DB
#  layer: SQL constants live here, repository functions become thin
#  wrappers around them. This eliminates the previously duplicated SQL
#  strings between sync and async paths.
#
# Design notes:
#   * pgvector literals are NOT parameterized because psycopg can't bind
#     a Python list directly to a vector column. We render them as a
#     bracketed CSV string via vector_literal() and interpolate. The
#     input is always list[float], so injection is impossible.
#   * search_similar() and search_trgm() / search_tsv() build dynamic
#     WHERE clauses from optional filters, so we expose builder helpers
#     rather than fixed SQL constants for those paths.

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Fact-type constants
# ---------------------------------------------------------------------------

FACT_TYPE_STATIC = "static"
FACT_TYPE_DYNAMIC = "dynamic"

# Embedding dimension expected by the schema (Qwen3-Embedding-8B).
EMBEDDING_DIM = 4096


# ---------------------------------------------------------------------------
# Vector helpers
# ---------------------------------------------------------------------------


def normalize_vector(vec: list[float] | None) -> list[float]:
    """Unit-normalize a vector for cosine similarity. Empty list on failure."""
    if not vec:
        return []
    try:
        norm = sum(x * x for x in vec) ** 0.5
        if norm == 0:
            return []
        return [x / norm for x in vec]
    except (TypeError, ValueError):
        return []


def vector_literal(vec: list[float] | None) -> str | None:
    """Render a list[float] as a pgvector bracketed CSV literal."""
    if vec is None:
        return None
    return "[" + ",".join(str(x) for x in vec) + "]"


# ---------------------------------------------------------------------------
# Static SQL constants — ALL scoped by user_id (multi-tenant isolation)
# ---------------------------------------------------------------------------

SQL_FACT_DUP_CHECK_BY_CONTENT = (
    "SELECT id FROM semantic_facts "
    "WHERE fact_type=%s AND content=%s AND user_id=%s AND invalid_at IS NULL LIMIT 1"
)

SQL_FACT_INSERT = """
INSERT INTO semantic_facts
    (user_id, fact_type, content, embedding, metadata, created_at, last_accessed)
VALUES (%s, %s, %s, %s::vector, %s, %s, %s)
RETURNING id
"""

SQL_FACT_SELECT_BY_ID = "SELECT * FROM semantic_facts WHERE id=%s AND user_id=%s"

# Batch query for multiple fact IDs (N+1 fix)
SQL_FACT_SELECT_BY_IDS = "SELECT * FROM semantic_facts WHERE id = ANY(%s) AND user_id=%s"

SQL_FACT_SELECT_STATIC_LIMIT = (
    "SELECT * FROM semantic_facts WHERE fact_type=%s AND user_id=%s LIMIT %s"
)

SQL_FACT_UPDATE_METADATA = (
    "UPDATE semantic_facts SET last_accessed=%s, metadata=%s WHERE id=%s AND user_id=%s"
)

SQL_FACT_INVALIDATE = (
    "UPDATE semantic_facts SET invalid_at=%s, last_accessed=%s WHERE id=%s AND user_id=%s"
)

SQL_FACT_UPDATE_DECAY = (
    "UPDATE semantic_facts SET metadata=%s, last_accessed=%s WHERE id=%s AND user_id=%s"
)

SQL_FACT_DECAY_FETCH_FOR_SESSION = """
SELECT id, metadata, last_accessed
FROM semantic_facts
WHERE fact_type = %s
  AND (metadata->>'session_id') = %s::text
  AND user_id = %s
  AND invalid_at IS NULL
"""

SQL_FACT_DECAY_FETCH_GLOBAL = """
SELECT id, metadata, last_accessed
FROM semantic_facts
WHERE fact_type = %s
  AND user_id = %s
  AND invalid_at IS NULL
"""


# ---------------------------------------------------------------------------
# Dynamic WHERE-clause builders
# ---------------------------------------------------------------------------


def build_metadata_conditions(
    *,
    session_id: str | None = None,
    fact_type: str | None = None,
    category: str | None = None,
    metadata_filter: dict[str, str] | None = None,
    user_id: str | None = None,
) -> tuple[list[str], list[Any]]:
    """Build a list of WHERE-clause fragments + their parameter list.

    Returns ([cond, ...], [param, ...]). Caller joins conditions with AND
    and passes params positionally.

    HARD-FAIL: user_id is REQUIRED. A falsy user_id raises ValueError to
    prevent cross-tenant data leaks. This is the central enforcement point
    for multi-tenant isolation on semantic_facts.

    Used by search_similar / search_trgm / search_tsv / get_facts_by_session.
    """
    if not user_id:
        raise ValueError(
            "user_id is required for semantic_facts queries — "
            "refusing to execute unscoped query (multi-tenant isolation)"
        )
    conditions: list[str] = []
    params: list[Any] = []

    conditions.append("user_id = %s")
    params.append(user_id)
    if session_id is not None:
        conditions.append("(metadata->>'session_id') = %s::text")
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

    return conditions, params


def build_search_similar_query(
    vec_literal: str,
    extra_conditions: list[str],
) -> str:
    """Render the vector-similarity SQL with the given extra WHERE clauses.

    Note: vec_literal is interpolated directly because psycopg cannot bind
    Python lists to vector columns. It is always produced by
    vector_literal() from list[float], so injection is impossible.
    """
    base_conditions = ["embedding IS NOT NULL"] + extra_conditions
    cond_sql = " AND ".join(base_conditions)
    return f"""
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


def build_search_trgm_query(extra_conditions: list[str]) -> str:
    """Trigram fuzzy search. extra_conditions are user-filter fragments."""
    base_conditions = ["invalid_at IS NULL"] + extra_conditions
    cond_sql = " AND ".join(base_conditions)
    return f"""
        SELECT id, fact_type, content, metadata,
               last_accessed, created_at,
               similarity(content, %s) AS similarity
        FROM semantic_facts
        WHERE {cond_sql}
          AND similarity(content, %s) >= %s::real
        ORDER BY similarity DESC
        LIMIT %s
    """


def build_search_tsv_query(extra_conditions: list[str]) -> str:
    """Full-text search via tsvector. extra_conditions are user filters."""
    base_conditions = [
        "invalid_at IS NULL",
        "tsv @@ plainto_tsquery('english', %s)",
    ] + extra_conditions
    cond_sql = " AND ".join(base_conditions)
    return f"""
        SELECT id, fact_type, content, metadata,
               last_accessed, created_at,
               ts_rank(tsv, plainto_tsquery('english', %s)) AS ts_rank
        FROM semantic_facts
        WHERE {cond_sql}
        ORDER BY ts_rank DESC, created_at DESC
        LIMIT %s
    """


def build_facts_by_session_query(
    extra_conditions: list[str],
    default_dynamic: bool = True,
) -> str:
    """List-facts query (no full-text/vector ranking).

    When extra_conditions is empty and default_dynamic is True, falls back
    to filtering by `fact_type = 'dynamic'` to preserve the previous
    behavior of get_facts_by_session().
    """
    if extra_conditions:
        where = "WHERE " + " AND ".join(extra_conditions)
    elif default_dynamic:
        where = "WHERE fact_type = 'dynamic'"
    else:
        where = ""
    return f"SELECT * FROM semantic_facts {where} LIMIT %s"


def build_count_query(extra_conditions: list[str]) -> str:
    where = "WHERE " + " AND ".join(extra_conditions) if extra_conditions else ""
    return f"SELECT COUNT(*) AS cnt FROM semantic_facts {where}"


def build_update_last_accessed_query(id_count: int) -> str:
    """Render the multi-id last_accessed UPDATE for the given count.

    Includes user_id scope to prevent cross-tenant updates.
    """
    placeholders = ",".join(["%s"] * id_count)
    return f"UPDATE semantic_facts SET last_accessed=%s WHERE id IN ({placeholders}) AND user_id=%s"


__all__ = [
    # Constants
    "FACT_TYPE_STATIC",
    "FACT_TYPE_DYNAMIC",
    "EMBEDDING_DIM",
    # Vector helpers
    "normalize_vector",
    "vector_literal",
    # Static SQL
    "SQL_FACT_DUP_CHECK_BY_CONTENT",
    "SQL_FACT_INSERT",
    "SQL_FACT_SELECT_BY_ID",
    "SQL_FACT_SELECT_STATIC_LIMIT",
    "SQL_FACT_UPDATE_METADATA",
    "SQL_FACT_INVALIDATE",
    "SQL_FACT_UPDATE_DECAY",
    "SQL_FACT_DECAY_FETCH_FOR_SESSION",
    "SQL_FACT_DECAY_FETCH_GLOBAL",
    # Builders
    "build_metadata_conditions",
    "build_search_similar_query",
    "build_search_trgm_query",
    "build_search_tsv_query",
    "build_facts_by_session_query",
    "build_count_query",
    "build_update_last_accessed_query",
]
