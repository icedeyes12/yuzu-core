# established by app.db.facade.Database.
#
# Two patterns live here:
#   1. Pure passthroughs (generated via _proxy/_proxy_async) for methods
#      whose signatures don't need normalization.
#   2. Constants re-exported from db_memory_queries for caller convenience.
#
# This file is ONLY an interface layer. It does NOT modify execution logic,
# SQL queries, database schema, or threading.local caches.

from __future__ import annotations

from typing import Any, Callable

from app.memory.db_memory import (
    # ── Sync functions ────────────────────────────────────────────────────
    save_fact as _save_fact,
    search_similar as _search_similar,
    search_trgm as _search_trgm,
    search_tsv as _search_tsv,
    get_fact_by_id as _get_fact_by_id,
    get_facts_by_ids as _get_facts_by_ids,
    get_facts_by_session as _get_facts_by_session,
    count_facts as _count_facts,
    update_last_accessed as _update_last_accessed,
    increment_importance as _increment_importance,
    decay_facts as _decay_facts,
    invalidate_fact as _invalidate_fact,
    # ── Async functions ───────────────────────────────────────────────────
    save_fact_async as _save_fact_async,
    search_similar_async as _search_similar_async,
    search_trgm_async as _search_trgm_async,
    search_tsv_async as _search_tsv_async,
    get_fact_by_id_async as _get_fact_by_id_async,
    get_facts_by_ids_async as _get_facts_by_ids_async,
    get_facts_by_session_async as _get_facts_by_session_async,
    update_last_accessed_async as _update_last_accessed_async,
    invalidate_fact_async as _invalidate_fact_async,
)
from app.memory.db_memory_queries import (
    FACT_TYPE_STATIC,
    FACT_TYPE_DYNAMIC,
    EMBEDDING_DIM,
)


# ---------------------------------------------------------------------------
# Proxy helpers (identical pattern to app.db.facade)
# ---------------------------------------------------------------------------


def _proxy(target: Callable[..., Any]) -> staticmethod:
    """Wrap a sync function in a staticmethod that forwards *args/**kwargs."""

    def _call(*args: Any, **kwargs: Any) -> Any:
        return target(*args, **kwargs)

    _call.__name__ = target.__name__
    _call.__doc__ = target.__doc__
    return staticmethod(_call)


def _proxy_async(target: Callable[..., Any]) -> staticmethod:
    """Wrap an async function in a staticmethod that forwards *args/**kwargs."""

    async def _call(*args: Any, **kwargs: Any) -> Any:
        return await target(*args, **kwargs)

    _call.__name__ = target.__name__
    _call.__doc__ = target.__doc__
    return staticmethod(_call)


# ---------------------------------------------------------------------------
# MemoryDB facade
# ---------------------------------------------------------------------------


class MemoryDB:
    """Static helper class delegating to app.memory.db_memory.

    Mirrors the app.db.facade.Database pattern:
      - Every public function in db_memory gets a corresponding staticmethod.
      - Sync and async variants share the same method name convention
        (``foo`` / ``foo_async``).
      - Callers import ``MemoryDB`` instead of cherry-picking individual
        functions from db_memory.
    """

    # ── Write ─────────────────────────────────────────────────────────────
    save_fact = _proxy(_save_fact)
    save_fact_async = _proxy_async(_save_fact_async)

    # ── Vector search ─────────────────────────────────────────────────────
    search_similar = _proxy(_search_similar)
    search_similar_async = _proxy_async(_search_similar_async)

    # ── Keyword / trigram search ──────────────────────────────────────────
    search_trgm = _proxy(_search_trgm)
    search_trgm_async = _proxy_async(_search_trgm_async)

    # ── Full-text search ──────────────────────────────────────────────────
    search_tsv = _proxy(_search_tsv)
    search_tsv_async = _proxy_async(_search_tsv_async)

    # ── Single-row retrieval ──────────────────────────────────────────────
    get_fact_by_id = _proxy(_get_fact_by_id)
    get_fact_by_id_async = _proxy_async(_get_fact_by_id_async)

    # ── Batch retrieval ───────────────────────────────────────────────────
    get_facts_by_ids = _proxy(_get_facts_by_ids)
    get_facts_by_ids_async = _proxy_async(_get_facts_by_ids_async)

    # ── Session-scoped retrieval ──────────────────────────────────────────
    get_facts_by_session = _proxy(_get_facts_by_session)
    get_facts_by_session_async = _proxy_async(_get_facts_by_session_async)

    # ── Count (sync-only — no async callers currently) ────────────────────
    count_facts = _proxy(_count_facts)

    # ── Access tracking ───────────────────────────────────────────────────
    update_last_accessed = _proxy(_update_last_accessed)
    update_last_accessed_async = _proxy_async(_update_last_accessed_async)

    # ── Importance (sync-only — no async callers currently) ───────────────
    increment_importance = _proxy(_increment_importance)

    # ── FSRS decay (sync-only — no async callers currently) ───────────────
    decay_facts = _proxy(_decay_facts)

    # ── Soft delete ───────────────────────────────────────────────────────
    invalidate_fact = _proxy(_invalidate_fact)
    invalidate_fact_async = _proxy_async(_invalidate_fact_async)


__all__ = [
    "MemoryDB",
    "FACT_TYPE_STATIC",
    "FACT_TYPE_DYNAMIC",
    "EMBEDDING_DIM",
]
