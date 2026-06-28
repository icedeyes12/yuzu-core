# Schema reference:
#   semantic_facts (
#     id, session_id, fact_type, content, embedding (VECTOR(4096)),
#     metadata (JSONB), valid_at, invalid_at, created_at, last_accessed
#   )
# Active facts: invalid_at IS NULL
# Semantic facts use temporal validity; episodic facts use FSRS decay in metadata.

from __future__ import annotations

import logging
import math
from datetime import datetime

from psycopg.types.json import Json

from app.db import (
    PgSession,
    pg_fetchone,
    pg_fetchall,
    pg_execute,
    AsyncPgSession,
    pg_fetchone_async,
    pg_fetchall_async,
    pg_execute_async,
)
from app.memory.db_memory_queries import (
    FACT_TYPE_STATIC,
    FACT_TYPE_DYNAMIC,
    EMBEDDING_DIM,
    normalize_vector,
    vector_literal,
    SQL_FACT_DUP_CHECK_BY_CONTENT,
    SQL_FACT_INSERT,
    SQL_FACT_SELECT_BY_ID,
    SQL_FACT_SELECT_BY_IDS,
    SQL_FACT_SELECT_STATIC_LIMIT,
    SQL_FACT_UPDATE_METADATA,
    SQL_FACT_INVALIDATE,
    SQL_FACT_UPDATE_DECAY,
    SQL_FACT_DECAY_FETCH_FOR_SESSION,
    SQL_FACT_DECAY_FETCH_GLOBAL,
    build_metadata_conditions,
    build_search_similar_query,
    build_search_trgm_query,
    build_search_tsv_query,
    build_facts_by_session_query,
    build_count_query,
    build_update_last_accessed_query,
)

logger = logging.getLogger(__name__)


def _embed_text(text: str) -> list[float] | None:
    """Embed text via Chutes API. Returns None on failure."""
    try:
        from app.memory.embedder import embed_text as _embed

        return _embed(text)
    except Exception as e:
        logger.warning(f"Embed failed: {e}")
        return None


def save_fact(
    session_id: str | None,
    content: str,
    embedding: list[float] | None,
    fact_type: str,
    metadata: dict | None = None,
    category: str | None = None,
    user_id: str | None = None,
) -> int | None:
    if not user_id:
        raise ValueError("save_fact: user_id is required")
    meta = dict(metadata) if metadata else {}
    if "session_id" not in meta:
        meta["session_id"] = session_id
    if category:
        meta["category"] = category

    norm_vec = normalize_vector(embedding) if embedding else None

    if norm_vec is not None and len(norm_vec) != EMBEDDING_DIM:
        raise ValueError(
            f"Embedding dimension must be {EMBEDDING_DIM}, got {len(norm_vec)}"
        )

    vec_literal = vector_literal(norm_vec)


    try:
        dup_check = pg_fetchone(
            SQL_FACT_DUP_CHECK_BY_CONTENT, (fact_type, content, user_id)
        )
        if dup_check:
            logger.debug(
                f"save_fact: duplicate content found, rejecting id={dup_check['id']}"
            )
            return dup_check["id"]
    except Exception as e:
        logger.warning(f"save_fact: dup check failed: {e}")

    try:
        with PgSession() as s:
            row = s.execute_returning(
                SQL_FACT_INSERT,
                (
                    user_id,
                    fact_type,
                    content,
                    vec_literal,
                    Json(meta),
                    datetime.now(),
                    datetime.now(),
                ),
            )
            return row["id"] if row else None
    except Exception as e:
        logger.error(f"save_fact failed: {e}")
        return None


def search_similar(
    embedding: list[float],
    session_id: str | None = None,
    fact_type: str | None = None,
    limit: int = 15,
    max_distance: float = 1.5,
    metadata_filter: dict | None = None,
    category: str | None = None,
    user_id: str | None = None,
) -> list[dict]:
    if not user_id:
        raise ValueError("search_similar: user_id is required")
    try:
        norm_vec = normalize_vector(embedding)
        if not norm_vec:
            logger.warning("search_similar: normalized vector is empty")
            return []

        vec_literal = vector_literal(norm_vec)
        if not vec_literal:
            return []


        conditions, params = build_metadata_conditions(
            session_id=session_id,
            fact_type=fact_type,
            category=category,
            metadata_filter=metadata_filter,
            user_id=user_id,
        )

        query = build_search_similar_query(vec_literal, conditions)
        params.extend([max_distance, limit])

        results = pg_fetchall(query, params)
        return results if results else []

    except Exception as e:
        logger.exception(f"search_similar EXCEPTION: {type(e).__name__}: {e}")
        return []


def search_trgm(
    query: str,
    session_id: str | None = None,
    fact_type: str | None = None,
    limit: int = 15,
    min_similarity: float = 0.3,
    metadata_filter: dict | None = None,
    category: str | None = None,
    user_id: str | None = None,
) -> list[dict]:
    if not user_id:
        raise ValueError("search_trgm: user_id is required")
    if not query or not query.strip():
        return []

    conditions, params = build_metadata_conditions(
        session_id=session_id,
        fact_type=fact_type,
        category=category,
        metadata_filter=metadata_filter,
        user_id=user_id,
    )

    sql = build_search_trgm_query(conditions)
    params_with_query = [query] + params + [query, min_similarity, limit]

    try:
        results = pg_fetchall(sql, params_with_query)
        return results if results else []
    except Exception as e:
        logger.exception(f"search_trgm EXCEPTION: {type(e).__name__}: {e}")
        return []


def search_tsv(
    query: str,
    session_id: str | None = None,
    fact_type: str | None = None,
    limit: int = 15,
    metadata_filter: dict | None = None,
    category: str | None = None,
    rank_weight: float = 0.3,
    user_id: str | None = None,
) -> list[dict]:
    if not user_id:
        raise ValueError("search_tsv: user_id is required")
    if not query or not query.strip():
        return []

    conditions, params = build_metadata_conditions(
        session_id=session_id,
        fact_type=fact_type,
        category=category,
        metadata_filter=metadata_filter,
        user_id=user_id,
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


def get_fact_by_id(id: int, user_id: str | None = None) -> dict | None:
    if not user_id:
        raise ValueError("get_fact_by_id: user_id is required")
    return pg_fetchone(SQL_FACT_SELECT_BY_ID, (id, user_id))


async def get_fact_by_id_async(id: int, user_id: str) -> dict | None:
    if not user_id:
        raise ValueError("get_fact_by_id_async: user_id is required")
    return await pg_fetchone_async(SQL_FACT_SELECT_BY_ID, (id, user_id))


def get_facts_by_ids(ids: list[int], user_id: str | None = None) -> list[dict]:
    if not user_id:
        raise ValueError("get_facts_by_ids: user_id is required")
    if not ids:
        return []
    return pg_fetchall(SQL_FACT_SELECT_BY_IDS, (ids, user_id))


async def get_facts_by_ids_async(
    ids: list[int], user_id: str | None = None
) -> list[dict]:
    if not user_id:
        raise ValueError("get_facts_by_ids_async: user_id is required")
    if not ids:
        return []
    return await pg_fetchall_async(SQL_FACT_SELECT_BY_IDS, (ids, user_id))


def get_facts_by_session(
    session_id: str | None,
    fact_type: str | None = None,
    limit: int = 100,
    user_id: str | None = None,
) -> list[dict]:
    if not user_id:
        raise ValueError("get_facts_by_session: user_id is required")
    # Static facts are now per-user (was GLOBAL — multi-tenant leak fix)
    if fact_type == FACT_TYPE_STATIC:
        return pg_fetchall(SQL_FACT_SELECT_STATIC_LIMIT, (fact_type, user_id, limit))
    # Dynamic facts: build conditions
    conditions, params = build_metadata_conditions(
        session_id=session_id, fact_type=fact_type, user_id=user_id
    )
    params.append(limit)
    query = build_facts_by_session_query(conditions, default_dynamic=True)
    return pg_fetchall(query, params)


def count_facts(
    fact_type: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> int:
    if not user_id:
        raise ValueError("count_facts: user_id is required")
    conditions, params = build_metadata_conditions(
        fact_type=fact_type, session_id=session_id, user_id=user_id
    )
    query = build_count_query(conditions)
    row = pg_fetchone(query, params)
    return row["cnt"] if row else 0


def update_last_accessed(ids: list[int], user_id: str | None = None) -> int:
    if not user_id:
        raise ValueError("update_last_accessed: user_id is required")
    if not ids:
        return 0
    now = datetime.now()
    query = build_update_last_accessed_query(len(ids))
    try:
        pg_execute(query, (now,) + tuple(ids) + (user_id,))
        return len(ids)
    except Exception as e:
        logger.error(f"update_last_accessed failed: {e}")
        return 0


def increment_importance(
    id: int, delta: float = 0.05, cap: float = 1.0, user_id: str | None = None
) -> bool:
    if not user_id:
        raise ValueError("increment_importance: user_id is required")
    try:
        meta_row = pg_fetchone(SQL_FACT_SELECT_BY_ID, (id, user_id))
        if not meta_row:
            return False
        meta = meta_row["metadata"] or {}
        current = meta.get("importance") or 0.5
        meta["importance"] = min(current + delta, cap)
        meta["access_count"] = (meta.get("access_count") or 0) + 1
        pg_execute(
            SQL_FACT_UPDATE_METADATA,
            (datetime.now(), Json(meta), id, user_id),
        )
        return True
    except Exception as e:
        logger.error(f"increment_importance failed: {e}")
        return False


def decay_facts(
    session_id: str | None = None,
    fact_type: str = FACT_TYPE_DYNAMIC,
    user_id: str | None = None,
) -> int:
    try:
        now = datetime.now()

        if session_id is not None:
            rows = pg_fetchall(
                SQL_FACT_DECAY_FETCH_FOR_SESSION, (fact_type, session_id, user_id)
            )
        else:
            rows = pg_fetchall(SQL_FACT_DECAY_FETCH_GLOBAL, (fact_type, user_id))

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
                (Json(meta), now, row["id"], user_id),
            )
            count += 1

        return count

    except Exception as e:
        logger.error(f"decay_facts failed: {e}")
        return 0


def invalidate_fact(id: int, user_id: str | None = None) -> bool:
    if not user_id:
        raise ValueError("invalidate_fact: user_id is required")
    try:
        pg_execute(
            SQL_FACT_INVALIDATE,
            (datetime.now(), datetime.now(), id, user_id),
        )
        return True
    except Exception as e:
        logger.error(f"invalidate_fact failed: {e}")
        return False


async def save_fact_async(
    session_id: str | None,
    content: str,
    embedding: list[float] | None,
    fact_type: str = FACT_TYPE_STATIC,
    metadata: dict | None = None,
    category: str | None = None,
    user_id: str | None = None,
) -> int | None:
    """Async version of save_fact."""
    if not user_id:
        raise ValueError("save_fact_async: user_id is required")
    meta = dict(metadata) if metadata else {}
    if "session_id" not in meta:
        meta["session_id"] = session_id
    if category:
        meta["category"] = category

    norm_vec = normalize_vector(embedding) if embedding else None

    if norm_vec is not None and len(norm_vec) != EMBEDDING_DIM:
        raise ValueError(
            f"Embedding dimension must be {EMBEDDING_DIM}, got {len(norm_vec)}"
        )

    vec_literal = vector_literal(norm_vec)

    try:
        dup_check = await pg_fetchone_async(
            SQL_FACT_DUP_CHECK_BY_CONTENT, (fact_type, content, user_id)
        )
        if dup_check:
            logger.debug(
                f"save_fact_async: duplicate content found, rejecting id={dup_check['id']}"
            )
            return dup_check["id"]
    except Exception as e:
        logger.warning(f"save_fact_async: dup check failed: {e}")

    try:
        async with AsyncPgSession() as s:
            row = await s.execute_returning(
                SQL_FACT_INSERT,
                (
                    user_id,
                    fact_type,
                    content,
                    vec_literal,
                    Json(meta),
                    datetime.now(),
                    datetime.now(),
                ),
            )
            return row["id"] if row else None
    except Exception as e:
        logger.error(f"save_fact_async failed: {e}")
        return None


async def search_similar_async(
    embedding: list[float],
    session_id: str | None = None,
    fact_type: str | None = None,
    limit: int = 15,
    max_distance: float = 1.5,
    metadata_filter: dict | None = None,
    category: str | None = None,
    user_id: str | None = None,
) -> list[dict]:

    if not user_id:
        raise ValueError("search_similar_async: user_id is required")
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
            user_id=user_id,
        )

        query = build_search_similar_query(vec_literal, conditions)
        params.extend([max_distance, limit])

        results = await pg_fetchall_async(query, params)
        return results if results else []

    except Exception as e:
        logger.error(f"search_similar_async EXCEPTION: {e}")
        return []


async def get_facts_by_session_async(
    session_id: str | None,
    fact_type: str | None = None,
    limit: int = 100,
    user_id: str | None = None,
) -> list[dict]:

    if not user_id:
        raise ValueError("get_facts_by_session_async: user_id is required")
    if fact_type == FACT_TYPE_STATIC:
        return await pg_fetchall_async(
            SQL_FACT_SELECT_STATIC_LIMIT, (fact_type, user_id, limit)
        )
    conditions, params = build_metadata_conditions(
        session_id=session_id, fact_type=fact_type, user_id=user_id
    )
    params.append(limit)
    query = build_facts_by_session_query(conditions, default_dynamic=True)
    return await pg_fetchall_async(query, params)


async def update_last_accessed_async(ids: list[int]) -> int:

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


async def invalidate_fact_async(id: int, user_id: str) -> bool:

    if not user_id:
        raise ValueError("invalidate_fact_async: user_id is required")
    try:
        await pg_execute_async(
            SQL_FACT_INVALIDATE,
            (datetime.now(), datetime.now(), id, user_id),
        )
        return True
    except Exception as e:
        logger.error(f"invalidate_fact_async failed: {e}")
        return False


async def search_trgm_async(
    query: str,
    session_id: str | None = None,
    fact_type: str | None = None,
    limit: int = 15,
    min_similarity: float = 0.3,
    metadata_filter: dict | None = None,
    category: str | None = None,
    user_id: str | None = None,
) -> list[dict]:

    if not user_id:
        raise ValueError("search_trgm_async: user_id is required")
    try:
        conditions, params = build_metadata_conditions(
            session_id=session_id,
            fact_type=fact_type,
            category=category,
            metadata_filter=metadata_filter,
            user_id=user_id,
        )

        sql = build_search_trgm_query(conditions)
        params_with_query = [query] + params + [query, min_similarity, limit]

        results = await pg_fetchall_async(sql, params_with_query)
        return results if results else []
    except Exception as e:
        logger.exception(f"search_trgm_async EXCEPTION: {type(e).__name__}: {e}")
        return []


async def search_tsv_async(
    query: str,
    session_id: str | None = None,
    fact_type: str | None = None,
    limit: int = 15,
    metadata_filter: dict | None = None,
    category: str | None = None,
    rank_weight: float = 0.3,
    user_id: str | None = None,
) -> list[dict]:

    if not user_id:
        raise ValueError("search_tsv_async: user_id is required")
    if not query or not query.strip():
        return []

    conditions, params = build_metadata_conditions(
        session_id=session_id,
        fact_type=fact_type,
        category=category,
        metadata_filter=metadata_filter,
        user_id=user_id,
    )

    sql = build_search_tsv_query(conditions)
    params_with_query = [query, query] + params + [limit]

    try:
        results = await pg_fetchall_async(sql, params_with_query)
        return results if results else []
    except Exception as e:
        logger.error(f"search_tsv_async EXCEPTION: {type(e).__name__}: {e}")
        return []
