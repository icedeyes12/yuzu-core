from __future__ import annotations
# FILE: app/memory/embedder.py
# DESCRIPTION: Chutes API embedding client for memory vectors
#              PostgreSQL handles list[float] natively - no blob conversion needed


import os
import threading
from app.database import get_api_key


CHUTES_EMBED_ENDPOINT = "https://chutes-qwen-qwen3-embedding-8b-tee.chutes.ai/v1/embeddings"
DEFAULT_MODEL = None  # Endpoint is model-specific, no model param needed
EMBEDDING_DIM = 4096  # Qwen3-Embedding-8B output dimension

_thread_local = threading.local()


def _get_session():
    """Get or create a thread-local requests session."""
    if not hasattr(_thread_local, "session") or _thread_local.session is None:
        # Try Zo secret env var first (more reliable), fallback to DB
        api_key = os.environ.get("CHUTES_API_KEY") or get_api_key("chutes")
        if not api_key:
            return None
        _thread_local.session = __import__("requests").Session()
        _thread_local.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })
    return _thread_local.session


def embed_texts(texts, model=None, dimensions=None, encoding_format="float", timeout=30):
    """Embed a list of strings via Chutes API. Returns list of embedding lists.
    
    Args:
        texts: String or list of strings to embed
        model: Ignored (endpoint is model-specific)
        dimensions: Optional output dimensions (not supported by this endpoint)
        encoding_format: Output format (default: "float")
        timeout: Request timeout in seconds (default: 30, was 60)
    
    Returns:
        List of embedding vectors, or raises exception on failure.
    """
    session = _get_session()
    if session is None:
        raise RuntimeError("Chutes API key not configured")
    if isinstance(texts, str):
        texts = [texts]
    if not texts:
        return []

    payload = {
        "input": texts,
        "model": None,  # Required by endpoint, but ignored
    }
    # Note: dimensions param not supported by this endpoint
    payload["encoding_format"] = encoding_format

    # Hard timeout with exception propagation
    result_container = {"result": None, "error": None}
    
    def _do_post():
        try:
            resp = session.post(CHUTES_EMBED_ENDPOINT, json=payload, timeout=timeout)
            resp.raise_for_status()
            results = [item["embedding"] for item in resp.json()["data"]]
            if results and len(results[0]) != EMBEDDING_DIM:
                raise ValueError(f"Embedding dim mismatch: got {len(results[0])}, expected {EMBEDDING_DIM}")
            result_container["result"] = results
        except Exception as e:
            result_container["error"] = e
    
    thread = threading.Thread(target=_do_post, daemon=True)
    thread.start()
    thread.join(timeout=timeout + 5)  # Thread timeout slightly longer than HTTP timeout
    
    if thread.is_alive():
        # Thread hung - return empty instead of blocking forever
        raise TimeoutError(f"Embedding request timed out after {timeout}s")
    
    if result_container["error"]:
        raise result_container["error"]
    
    return result_container["result"]


def embed_text(text, timeout=30, **kwargs):
    """Embed a single string. Returns None if embedding fails.
    
    Args:
        text: String to embed
        timeout: Request timeout in seconds (default: 30)
        **kwargs: Additional args passed to embed_texts
    
    Returns:
        Embedding vector or None on failure.
    """
    try:
        results = embed_texts([text], timeout=timeout, **kwargs)
        return results[0] if results and len(results) > 0 else None
    except Exception:
        return None


# ── Vector normalization (for pgvector) ────────────────────────────────────────
