from __future__ import annotations
# FILE: app/memory/embedder.py
# DESCRIPTION: Chutes API embedding client for memory vectors
#              PostgreSQL handles list[float] natively - no blob conversion needed


import httpx
import asyncio
from app.providers import get_ai_manager
from app.providers.base import _rate_limit_provider


CHUTES_EMBED_ENDPOINT = (
    "https://chutes-qwen-qwen3-embedding-8b-tee.chutes.ai/v1/embeddings"
)
DEFAULT_MODEL = None  # Endpoint is model-specific, no model param needed
EMBEDDING_DIM = 4096  # Qwen3-Embedding-8B output dimension


async def _get_client():
    """Get an async client with API key."""
    manager = await get_ai_manager()
    chutes = manager.providers.get("chutes")
    api_key = chutes.api_key if chutes else None

    if not api_key:
        return None

    return httpx.AsyncClient(
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
    )


async def embed_texts_async(
    texts, model=None, dimensions=None, encoding_format="float", timeout=30
):
    """Embed a list of strings via Chutes API (async). Returns list of embedding lists.

    Rate-limited to prevent 429 errors from concurrent embedding + LLM requests.
    """
    client = await _get_client()
    if client is None:
        raise RuntimeError("Chutes API key not configured")

    if isinstance(texts, str):
        texts = [texts]
    if not texts:
        return []

    payload = {
        "input": texts,
        "model": None,  # Required by endpoint, but ignored
    }
    payload["encoding_format"] = encoding_format

    # Use rate limiter - embedding shares global Chutes rate limit
    async with client:
        try:
            async with _rate_limit_provider("chutes", "embedding"):
                resp = await client.post(
                    CHUTES_EMBED_ENDPOINT, json=payload, timeout=timeout
                )
            resp.raise_for_status()
            data = resp.json()["data"]
            results = [item["embedding"] for item in data]

            if results and len(results[0]) != EMBEDDING_DIM:
                raise ValueError(
                    f"Embedding dim mismatch: got {len(results[0])}, expected {EMBEDDING_DIM}"
                )
            return results
        except httpx.TimeoutException:
            raise TimeoutError(f"Embedding request timed out after {timeout}s")
        except Exception as e:
            raise e


def embed_texts(
    texts, model=None, dimensions=None, encoding_format="float", timeout=30
):
    """Legacy sync wrapper (not recommended in async loop)."""
    return asyncio.run(
        embed_texts_async(texts, model, dimensions, encoding_format, timeout)
    )


async def embed_text_async(text, timeout=30, **kwargs):
    """Embed a single string (async). Returns None if embedding fails."""
    try:
        results = await embed_texts_async([text], timeout=timeout, **kwargs)
        return results[0] if results and len(results) > 0 else None
    except Exception:
        return None


def embed_text(text, timeout=30, **kwargs):
    """Legacy sync wrapper."""
    return asyncio.run(embed_text_async(text, timeout, **kwargs))


# ── Vector normalization (for pgvector) ────────────────────────────────────────
