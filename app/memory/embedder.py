from __future__ import annotations

import asyncio
import logging

import httpx

from app.core.byok import DEFAULT_YUZU_PORTAL_BASE_URL, YUZU_PORTAL
from app.core.context import get_request_keyring
from app.providers.base import _rate_limit_provider

DEFAULT_MODEL = "gemini/gemini-embedding-2-preview"
EMBEDDING_DIM = 1536
logger = logging.getLogger(__name__)


def _parse_embedding_data(
    data: list[dict], expected_count: int, expected_dim: int = EMBEDDING_DIM
) -> list[list[float]]:
    if len(data) != expected_count:
        raise ValueError(
            f"Embedding count mismatch: got {len(data)}, expected {expected_count}"
        )
    try:
        ordered = sorted(data, key=lambda item: item["index"])
        if [item["index"] for item in ordered] != list(range(expected_count)):
            raise ValueError("Embedding indexes are incomplete or duplicated")
        results = [item["embedding"] for item in ordered]
    except (KeyError, TypeError) as exc:
        raise ValueError("Embedding response indexes are invalid") from exc
    if any(len(embedding) != expected_dim for embedding in results):
        raise ValueError("Embedding dimension mismatch")
    return results


async def _get_client(profile: dict | None = None) -> httpx.AsyncClient | None:
    del profile
    keyring = get_request_keyring(YUZU_PORTAL)
    api_key = keyring.key.strip() if keyring and keyring.key else None
    if not api_key:
        logger.info(
            "memory embeddings disabled provider=%s",
            YUZU_PORTAL,
        )
        return None
    base_url = (
        keyring.base_url.strip().rstrip("/")
        if keyring and keyring.base_url
        else DEFAULT_YUZU_PORTAL_BASE_URL
    )
    return httpx.AsyncClient(
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        base_url=base_url,
    )


async def embed_texts_async(
    texts,
    model=None,
    dimensions=None,
    encoding_format="float",
    timeout=30,
    profile=None,
):
    client = await _get_client(profile)
    if client is None:
        return []

    if isinstance(texts, str):
        texts = [texts]
    if not texts:
        await client.aclose()
        return []

    payload = {
        "input": texts,
        "model": model or DEFAULT_MODEL,
        "dimensions": dimensions or EMBEDDING_DIM,
        "encoding_format": encoding_format,
    }

    async with client:
        try:
            async with _rate_limit_provider(
                "yuzu_portal", payload["model"], "embedding"
            ):
                response = await client.post(
                    "/embeddings", json=payload, timeout=timeout
                )
            response.raise_for_status()
            data = response.json().get("data", [])
            return _parse_embedding_data(data, len(texts), payload["dimensions"])
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"Embedding request timed out after {timeout}s") from exc


def embed_texts(
    texts, model=None, dimensions=None, encoding_format="float", timeout=30
):
    return asyncio.run(
        embed_texts_async(texts, model, dimensions, encoding_format, timeout)
    )


async def embed_text_async(text, timeout=30, **kwargs):
    try:
        results = await embed_texts_async([text], timeout=timeout, **kwargs)
        return results[0] if results else None
    except Exception as exc:
        logger.warning("Embedding skipped: %s", type(exc).__name__)
        return None


def embed_text(text, timeout=30, **kwargs):
    return asyncio.run(embed_text_async(text, timeout, **kwargs))


# ── Vector normalization (for pgvector) ────────────────────────────────────────
