# [FILE: memory/embedder.py]
# [DESCRIPTION: Chutes API embedding client for memory vectors]

import math
import struct
import threading
from app.database import Database


CHUTES_EMBED_ENDPOINT = "https://chutes-qwen-qwen3-embedding-8b.chutes.ai/v1/embeddings"
DEFAULT_MODEL = "Qwen/Qwen3-Embedding-8B"
EMBEDDING_DIM = 4096  # Qwen3-Embedding-8B default output dimension

_thread_local = threading.local()


def _get_session():
    """Get or create a thread-local requests session."""
    if not hasattr(_thread_local, "session") or _thread_local.session is None:
        api_key = Database.get_api_key("chutes")
        if not api_key:
            return None
        _thread_local.session = __import__("requests").Session()
        _thread_local.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })
    return _thread_local.session


def embed_texts(texts, model=None, dimensions=None, encoding_format="float"):
    """Embed a list of strings via Chutes API. Returns list of embedding lists."""
    session = _get_session()
    if session is None:
        raise RuntimeError("Chutes API key not configured")
    if isinstance(texts, str):
        texts = [texts]
    if not texts:
        return []

    payload = {
        "input": texts,
        "model": model or DEFAULT_MODEL,
    }
    if dimensions:
        payload["dimensions"] = dimensions
    payload["encoding_format"] = encoding_format

    resp = session.post(CHUTES_EMBED_ENDPOINT, json=payload, timeout=60)
    resp.raise_for_status()
    return [item["embedding"] for item in resp.json()["data"]]


def embed_text(text, **kwargs):
    """Embed a single string. Returns None if embedding fails."""
    try:
        return embed_texts([text], **kwargs)[0]
    except Exception:
        return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def vec_to_blob(vec: list[float]) -> bytes:
    """Serialize a float list to bytes for SQLite BLOB storage."""
    if vec is None:
        return b""
    return struct.pack(f"{len(vec)}f", *vec)


def blob_to_vec(blob: bytes) -> list[float]:
    """Deserialize bytes back to float list."""
    if not blob:
        return []
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))
