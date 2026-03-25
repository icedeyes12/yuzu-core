# [FILE: memory/vector_store.py]
# [DESCRIPTION: FAISS ANN index for memory retrieval — replaces brute-force O(n)]

from __future__ import annotations

import json
import os
import threading

import numpy as np
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

def _create_index(dimension: int) -> "faiss.IndexFlatIP":  # noqa: F821
    """Create a normalized inner-product index (cosine sim equivalent)."""
    faiss = _init_faiss()
    index = faiss.IndexFlatIP(dimension)
    return index


def _normalize(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec
    return vec / norm


def _get_embedding_dim() -> int:
    """Detect embedding dimension from a sample semantic memory row."""
    with get_db_session() as session:
        mem = session.query(SemanticMemory).filter(
            SemanticMemory.embedding_vector.isnot(None)
        ).first()
        if mem:
            vec = blob_to_vec(mem.embedding_vector)
            return len(vec)
    return EMBEDDING_DIM  # fallback — chutes default is often 1024 or 1280


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
        return  # already built

    # Load vectors from DB
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
            # Empty index — remove stale files if any
            for p in (index_path, ids_path):
                if os.path.exists(p):
                    os.remove(p)
            _update_manifest(session_id, memory_type, dimension=0, count=0)
            return

        # Build vector matrix
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
                continue  # skip mismatched dimensions
            vecs.append(_normalize(vec))
            ids.append(row.id)

        if not vecs:
            return

        if dim is None:
            return

        mat = np.stack(vecs).astype(np.float32)
        index = _create_index(dim)
        index.add(mat)

        # Serialize
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


def _load_index(session_id: int, memory_type: str) -> tuple["faiss.IndexFlatIP", list[int], int] | None:  # noqa: F821
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

    # Check dirty flag — rebuild if needed
    manifest = _load_manifest()
    key = f"{session_id}_{memory_type}"
    if manifest.get(key, {}).get("dirty", False):
        build_index(session_id, memory_type, force=True)
        index_data = _load_index(session_id, memory_type)
        if index_data is None:
            return []
        index, ids, dim = index_data

    # Handle query vector dimension mismatch
    q = np.array(query_vec, dtype=np.float32)
    if len(q) != dim:
        # Rebuild with correct dimension
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
    """Remove a memory from the index by rebuilding without it."""
    index_data = _load_index(session_id, memory_type)
    if index_data is None:
        return
    index, ids, dim = index_data
    if db_id not in ids:
        return
    pos = ids.index(db_id)
    # Rebuild without that position
    ids_new = ids[:pos] + ids[pos + 1 :]
    # Reload vectors from DB and rebuild
    if memory_type == "semantic":
        Model = SemanticMemory
        attr = "embedding_vector"
    elif memory_type == "episodic":
        Model = EpisodicMemory
        attr = "embedding"
    else:
        Model = ConversationSegment
        attr = "embedding"

    with get_db_session() as session:
        rows = session.query(Model).filter(
            Model.session_id == session_id,
            Model.id.in_(ids_new),
            getattr(Model, attr).isnot(None),
        ).all()
        id_to_vec = {r.id: blob_to_vec(getattr(r, attr)) for r in rows if r.id in ids_new}

    vecs = []
    final_ids = []
    for rid in ids_new:
        if rid in id_to_vec:
            v = id_to_vec[rid]
            if len(v) == dim:
                vecs.append(_normalize(np.array(v, dtype=np.float32)))
                final_ids.append(rid)

    if not vecs:
        for p in [_manifest_path(session_id, memory_type), _ids_path(session_id, memory_type)]:
            if os.path.exists(p):
                os.remove(p)
        _update_manifest(session_id, memory_type, dimension=0, count=0)
        return

    faiss = _init_faiss()
    index = _create_index(dim)
    index.add(np.stack(vecs).astype(np.float32))
    faiss.write_index(index, _manifest_path(session_id, memory_type))
    with open(_ids_path(session_id, memory_type), "w") as f:
        json.dump(final_ids, f)
    _update_manifest(session_id, memory_type, dimension=dim, count=len(final_ids))


# ── Init on import ────────────────────────────────────────────────────────────

_build_manifest = {}


def _bootstrap_indexes():
    """Rebuild all dirty/missing indexes on startup. Runs once."""
    _init_faiss()

    manifest = _load_manifest()
    sessions_seen = set()

    for key, meta in manifest.items():
        parts = key.rsplit("_", 1)
        if len(parts) != 2:
            continue
        session_id_str, memory_type = parts
        try:
            session_id = int(session_id_str)
        except ValueError:
            continue
        sessions_seen.add(session_id)

    with get_db_session() as session:
        sem_sessions = set(
            r[0] for r in session.query(SemanticMemory.session_id).distinct().all()
        )
        epi_sessions = set(
            r[0] for r in session.query(EpisodicMemory.session_id).distinct().all()
        )
        seg_sessions = set(
            r[0] for r in session.query(ConversationSegment.session_id).distinct().all()
        )

    all_sessions = sem_sessions | epi_sessions | seg_sessions

    for session_id in all_sessions:
        for memory_type in ("semantic", "episodic", "segment"):
            key = f"{session_id}_{memory_type}"
            meta = manifest.get(key, {})
            if meta.get("dirty", False) or not os.path.exists(_manifest_path(session_id, memory_type)):
                build_index(session_id, memory_type, force=True)


# Run bootstrap in background thread so it doesn't block startup
_thread = threading.Thread(target=_bootstrap_indexes, daemon=True)
_thread.start()
