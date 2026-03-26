# FILE: app/memory/vector_store.py
# DESCRIPTION: FAISS ANN index for memory retrieval

from __future__ import annotations

import json
import os
import threading

# ── Module-level FAISS/numpy availability flags ──────────────────────────────────
#
# TERMUX COMPATIBLE: no native extension required at import time.
# FAISS is optional; pure-Python fallback used automatically when unavailable.
#
# ── Module-level FAISS/numpy availability flags ──────────────────────────────────

_FAISS_AVAILABLE = False
_NUMPY_AVAILABLE = False

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    np = None  # type: ignore

try:
    import faiss
    _FAISS_AVAILABLE = True
except ImportError:
    faiss = None  # type: ignore

from app.database import get_db_session, SemanticMemory, EpisodicMemory, ConversationSegment
from app.memory.embedder import blob_to_vec, EMBEDDING_DIM
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import faiss


_INDEX_DIR = os.path.join(os.path.dirname(__file__), "indexes")
_MANIFEST_FILE = os.path.join(_INDEX_DIR, "manifest.json")


def _ensure_index_dir():
    os.makedirs(_INDEX_DIR, exist_ok=True)


def _manifest_path(session_id: int, memory_type: str) -> str:
    _ensure_index_dir()
    return os.path.join(_INDEX_DIR, f"session_{session_id}_{memory_type}.index")


def _ids_path(session_id: int, memory_type: str) -> str:
    _ensure_index_dir()
    return os.path.join(_INDEX_DIR, f"session_{session_id}_{memory_type}_ids.json")


def _load_manifest() -> dict:
    if not os.path.exists(_MANIFEST_FILE):
        return {}
    try:
        with open(_MANIFEST_FILE) as f:
            return json.load(f)
    except (ValueError, IOError):
        return {}


def _save_manifest(manifest: dict):
    _ensure_index_dir()
    try:
        with open(_MANIFEST_FILE, "w") as f:
            json.dump(manifest, f)
    except IOError as e:
        print(f"[vector_store] Failed to save manifest: {e}")


def _init_faiss():
    import faiss
    return faiss


# ── Core index operations ───────────────────────────────────────────────────────

def _create_index(dimension: int) -> "faiss.IndexFlatIP":
    """Create a normalized inner-product index (cosine sim equivalent)."""
    faiss = _init_faiss()
    index = faiss.IndexFlatIP(dimension)
    return index


def _normalize(vec) -> list[float]:
    """L2-normalize a vector. Works with both numpy arrays and plain lists."""
    if _NUMPY_AVAILABLE and hasattr(vec, '__len__') and not isinstance(vec, list):
        import numpy as np
        norm = float(np.linalg.norm(vec))
        if norm == 0:
            return vec.tolist()
        return (vec / norm).tolist()
    norm = __import__("math").sqrt(sum(x * x for x in vec))
    if norm == 0:
        return list(vec)
    return [x / norm for x in vec]


def _get_embedding_dim() -> int:
    """Detect embedding dimension from a sample semantic memory row."""
    with get_db_session() as session:
        mem = session.query(SemanticMemory).filter(
            SemanticMemory.embedding_vector.isnot(None)
        ).first()
        if mem:
            vec = blob_to_vec(mem.embedding_vector)
            return len(vec)
    return EMBEDDING_DIM


# ── Public API ────────────────────────────────────────────────────────────────

def build_index(session_id: int, memory_type: str, force: bool = False):
    """Build or rebuild FAISS index for a session+type from SQLite vectors.

    Args:
        session_id: session to index
        memory_type: 'semantic', 'episodic', or 'segment'
        force: rebuild even if index file exists
    """
    faiss = _init_faiss()
    index_path = _manifest_path(session_id, memory_type)
    ids_path = _ids_path(session_id, memory_type)

    if os.path.exists(index_path) and os.path.exists(ids_path) and not force:
        return

    if memory_type == "semantic":
        Model = SemanticMemory
    elif memory_type == "episodic":
        Model = EpisodicMemory
    else:
        Model = ConversationSegment

    with get_db_session() as session:
        rows = session.query(Model).filter(
            Model.session_id == session_id,
            Model.embedding.isnot(None) if memory_type != "semantic"
            else Model.embedding_vector.isnot(None)
        ).all()

        if not rows:
            for p in (index_path, ids_path):
                if os.path.exists(p):
                    os.remove(p)
            _update_manifest(session_id, memory_type, dimension=0, count=0)
            return

        vecs = []
        ids = []
        dim = None

        attr = "embedding_vector" if memory_type == "semantic" else "embedding"
        for row in rows:
            blob = getattr(row, attr, None)
            if blob is None:
                continue
            vec = np.array(blob_to_vec(blob), dtype=np.float32)
            if dim is None:
                dim = len(vec)
            if len(vec) != dim:
                continue
            vecs.append(_normalize(vec))
            ids.append(row.id)

        if not vecs:
            return

        if dim is None:
            return

        mat = np.stack(vecs).astype(np.float32)
        index = _create_index(dim)
        index.add(mat)

        faiss.write_index(index, index_path)
        with open(ids_path, "w") as f:
            json.dump(ids, f)

        _update_manifest(session_id, memory_type, dimension=dim, count=len(ids))
        print(f"[vector_store] Built index for session={session_id} type={memory_type} dim={dim} count={len(ids)}")


def _update_manifest(session_id: int, memory_type: str, dimension: int, count: int):
    manifest = _load_manifest()
    key = f"{session_id}_{memory_type}"
    manifest[key] = {"dimension": dimension, "count": count, "dirty": False}
    _save_manifest(manifest)


def mark_dirty(session_id: int, memory_type: str):
    """Mark index as stale so next retrieval rebuilds it."""
    manifest = _load_manifest()
    key = f"{session_id}_{memory_type}"
    if key in manifest:
        manifest[key]["dirty"] = True
    else:
        manifest[key] = {"dimension": 0, "count": 0, "dirty": True}
    _save_manifest(manifest)


def _load_index(session_id: int, memory_type: str) -> tuple["faiss.IndexFlatIP", list[int], int] | None:
    """Load index + id list from disk. Returns (index, ids, dimension) or None."""
    faiss = _init_faiss()
    index_path = _manifest_path(session_id, memory_type)
    ids_path = _ids_path(session_id, memory_type)

    if not os.path.exists(index_path) or not os.path.exists(ids_path):
        return None

    try:
        index = faiss.read_index(index_path)
        with open(ids_path) as f:
            ids = json.load(f)
        manifest = _load_manifest()
        key = f"{session_id}_{memory_type}"
        dim = manifest.get(key, {}).get("dimension", 0)
        return index, ids, dim
    except Exception as e:
        print(f"[vector_store] Failed to load index: {e}")
        return None


def search(session_id: int, memory_type: str, query_vec: list[float], k: int = 15) -> list[tuple[int, float]]:
    """Search FAISS index. Returns list of (db_id, score), sorted descending."""
    _init_faiss()
    index_data = _load_index(session_id, memory_type)

    if index_data is None:
        build_index(session_id, memory_type)
        index_data = _load_index(session_id, memory_type)

    if index_data is None:
        return []

    index, ids, dim = index_data

    if index.ntotal == 0 or len(ids) == 0:
        return []

    manifest = _load_manifest()
    key = f"{session_id}_{memory_type}"
    if manifest.get(key, {}).get("dirty", False):
        build_index(session_id, memory_type, force=True)
        index_data = _load_index(session_id, memory_type)
        if index_data is None:
            return []
        index, ids, dim = index_data

    q = np.array(query_vec, dtype=np.float32)
    if len(q) != dim:
        build_index(session_id, memory_type, force=True)
        index_data = _load_index(session_id, memory_type)
        if index_data is None:
            return []
        index, ids, dim = index_data
        if len(q) != dim:
            return []

    q_norm = _normalize(q).reshape(1, -1)
    scores, indices = index.search(q_norm, min(k, index.ntotal))

    results = []
    for idx, score in zip(indices[0], scores[0]):
        if idx >= 0 and idx < len(ids):
            results.append((ids[int(idx)], float(score)))
    return results


def remove_from_index(session_id: int, memory_type: str, db_id: int):
    """Remove a memory from the index in-place without full rebuild.

    Loads the on-disk index, removes the single vector by position,
    writes back — O(1) disk I/O instead of O(n) DB queries.
    """
    faiss = _init_faiss()
    index_path = _manifest_path(session_id, memory_type)
    ids_path = _ids_path(session_id, memory_type)

    index_data = _load_index(session_id, memory_type)
    if index_data is None:
        return
    index, ids, dim = index_data

    if db_id not in ids:
        return

    pos = ids.index(db_id)

    # In-place remove: rebuild ID list, rewrite index with one less vector
    ids_new = ids[:pos] + ids[pos + 1:]

    # Rewrite index by reconstructing without the removed vector
    # IDs are 0-indexed positions in the index, so we remove the vector at `pos`
    if index.ntotal == 1:
        # Last vector — delete index files entirely
        for p in (index_path, ids_path):
            if os.path.exists(p):
                os.remove(p)
        _update_manifest(session_id, memory_type, dimension=0, count=0)
        return

    # Extract all vectors, exclude the one at `pos`
    # Read index vectors directly via `index.reconstruct`
    all_vecs = []
    for i in range(index.ntotal):
        all_vecs.append(index.reconstruct(i))
    all_vecs.pop(pos)
    mat = np.stack(all_vecs).astype(np.float32)

    new_index = _create_index(dim)
    new_index.add(mat)
    faiss.write_index(new_index, index_path)

    with open(ids_path, "w") as f:
        json.dump(ids_new, f)

    _update_manifest(session_id, memory_type, dimension=dim, count=len(ids_new))


# ── Init on import ────────────────────────────────────────────────────────────

_BOOTSTRAP_ERRORS = []


def _bootstrap_indexes():
    """Rebuild all dirty/missing indexes on startup. Runs once in background."""
    global _BOOTSTRAP_ERRORS
    try:
        _init_faiss()
    except Exception as e:
        _BOOTSTRAP_ERRORS.append(str(e))
        print(f"[vector_store] CRITICAL: FAISS unavailable — vector search disabled: {e}")
        return  # Don't try to build indexes without FAISS

    manifest = _load_manifest()
    sessions_seen = set()

    for key in manifest:
        parts = key.rsplit("_", 1)
        if len(parts) != 2:
            continue
        session_id_str, _ = parts
        try:
            sessions_seen.add(int(session_id_str))
        except ValueError:
            continue

    with get_db_session() as session:
        sem_sessions = set(r[0] for r in session.query(SemanticMemory.session_id).distinct().all())
        epi_sessions = set(r[0] for r in session.query(EpisodicMemory.session_id).distinct().all())
        seg_sessions = set(r[0] for r in session.query(ConversationSegment.session_id).distinct().all())

    all_sessions = sem_sessions | epi_sessions | seg_sessions

    for session_id in all_sessions:
        for memory_type in ("semantic", "episodic", "segment"):
            key = f"{session_id}_{memory_type}"
            meta = manifest.get(key, {})
            if meta.get("dirty", False) or not os.path.exists(_manifest_path(session_id, memory_type)):
                try:
                    build_index(session_id, memory_type, force=True)
                except Exception as e:
                    err = f"session={session_id} type={memory_type}: {e}"
                    _BOOTSTRAP_ERRORS.append(err)
                    print(f"[vector_store] Bootstrap index build failed for {err}")


def get_bootstrap_errors():
    """Return list of errors encountered during bootstrap (for diagnostics)."""
    return list(_BOOTSTRAP_ERRORS)


