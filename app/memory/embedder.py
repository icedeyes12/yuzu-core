import asyncio
import os
import httpx
from app.providers.base import _rate_limit_provider

CHUTES_EMBED_ENDPOINT = "http://localhost:20128/v1/embeddings"
DEFAULT_MODEL = "gemini/gemini-embedding-2-preview"
EMBEDDING_DIM = 1536


async def _get_client():
    """Get an async client with API key from env (application-scoped)."""
    api_key = os.environ.get("EMBED_KEY")

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
    """Embed a list of strings via embedding API (async). Returns list of embedding lists.

    Rate-limited to prevent errors from concurrent embedding + LLM requests.
    """
    client = await _get_client()
    if client is None:
        raise RuntimeError("EMBED_KEY not configured")

    if isinstance(texts, str):
        texts = [texts]
    if not texts:
        return []

    payload = {
        "input": texts,
        "model": model or DEFAULT_MODEL,
        "dimensions": dimensions or EMBEDDING_DIM,
    }

    # Use rate limiter
    async with client:
        try:
            async with _rate_limit_provider("embedding", "embedding", "embedding"):
                resp = await client.post(
                    CHUTES_EMBED_ENDPOINT, json=payload, timeout=timeout
                )
            resp.raise_for_status()
            data = resp.json().get("data", [])
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
    """Legacy sync wrapper for embed_texts_async."""
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
    """Legacy sync wrapper for embed_text_async."""
    return asyncio.run(embed_text_async(text, timeout, **kwargs))


# ── Vector normalization (for pgvector) ────────────────────────────────────────
