# FILE: app/memory/vector_store.py
# DESCRIPTION: DEPRECATED - FAISS ANN index replaced by PostgreSQL pgvector.
#              This file is kept as a stub for backward compatibility.
#              All operations now delegate to db_memory.search_similar().
#
# DEPRECATION NOTICE:
#   - FAISS is no longer used
#   - Vector search is handled by PostgreSQL pgvector via db_memory.py
#   - mark_dirty() is a no-op (PostgreSQL handles indexing automatically)
#   - build_index() is a no-op (pgvector indexes are auto-maintained)
#
# Migration: Use db_memory.search_similar() directly in new code.

from __future__ import annotations

import warnings

# ── Deprecation Warning ───────────────────────────────────────────────────────

warnings.warn(
    "vector_store.py is deprecated. Use app.memory.db_memory instead.",
    DeprecationWarning,
    stacklevel=2
)

# ── Backward Compat Stubs ─────────────────────────────────────────────────────

_FAISS_AVAILABLE = False
_NUMPY_AVAILABLE = False
EMBEDDING_DIM = 4096


def build_index(session_id: int, memory_type: str, force: bool = False):
    """DEPRECATED - No-op stub. PostgreSQL pgvector handles indexing automatically."""
    pass  # No-op: pgvector maintains indexes


def mark_dirty(session_id: int, memory_type: str):
    """DEPRECATED - No-op stub. PostgreSQL handles index updates automatically."""
    pass  # No-op: pgvector auto-updates


def search(session_id: int, memory_type: str, query_vec: list[float], k: int = 15) -> list[tuple[int, float]]:
    """
    DEPRECATED - Delegate to db_memory.search_similar().
    
    Returns list of (db_id, similarity_score) for backward compatibility.
    
    Args:
        session_id: session to search
        memory_type: 'semantic', 'episodic', or 'segment' (mapped to fact_type)
        query_vec: embedding vector
        k: number of results
        
    Returns:
        list of (id, score) tuples, sorted by similarity descending
    """
    from app.memory.db_memory import search_similar
    
    # Map memory_type to fact_type
    if memory_type == "semantic":
        fact_type = "static"
        metadata_filter = {"source_table": "semantic_memories"}
    elif memory_type == "episodic":
        fact_type = "dynamic"
        metadata_filter = {"source_table": "episodic_memories"}
    elif memory_type == "segment":
        fact_type = "dynamic"
        metadata_filter = {"source_table": "conversation_segments"}
    else:
        fact_type = None
        metadata_filter = None
    
    results = search_similar(
        embedding=query_vec,
        session_id=session_id,
        fact_type=fact_type,
        limit=k,
        metadata_filter=metadata_filter,
    )
    
    # Convert distance to similarity score (1 - distance for cosine)
    # db_memory returns distance (lower = more similar)
    # FAISS returned similarity (higher = more similar)
    return [(r["id"], 1.0 - r.get("distance", 0.0)) for r in results]


def remove_from_index(session_id: int, memory_type: str, db_id: int):
    """DEPRECATED - No-op stub. PostgreSQL handles deletion automatically."""
    pass  # No-op: handled by db_memory.delete_fact()


def get_bootstrap_errors() -> list[str]:
    """DEPRECATED - Returns empty list (no bootstrap errors with pgvector)."""
    return []


# ── Internal Functions (kept for compat, but unused) ───────────────────────────

def _load_manifest() -> dict:
    return {}

def _save_manifest(manifest: dict):
    pass

def _create_index(dimension: int):
    return None

def _normalize(vec) -> list[float]:
    """L2-normalize a vector."""
    import math
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return list(vec)
    return [x / norm for x in vec]