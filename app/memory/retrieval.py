from __future__ import annotations

import logging
import threading
from typing import Any

from app.core.byok import YUZU_PORTAL, get_provider_key
from app.memory.embedder import embed_text, embed_text_async
from app.memory.graph import GraphMemoryRepository

logger = logging.getLogger(__name__)

_embedding_cache = threading.local()
_MIN_QUERY_LEN_FOR_EMBEDDING = 4


def _get_cached_embedding(query: str) -> list[float] | None:
    if len(query.strip()) < _MIN_QUERY_LEN_FOR_EMBEDDING:
        return None
    cache_key = f"embedding_{hash(query)}"
    if hasattr(_embedding_cache, cache_key):
        return getattr(_embedding_cache, cache_key)
    try:
        vector = embed_text(query, timeout=30)
    except Exception as exc:
        logger.warning("Query embedding failed: %s", exc)
        vector = None
    setattr(_embedding_cache, cache_key, vector)
    return vector


async def _get_cached_embedding_async(query: str) -> list[float] | None:
    if len(query.strip()) < _MIN_QUERY_LEN_FOR_EMBEDDING:
        return None
    cache_key = f"embedding_{hash(query)}"
    if hasattr(_embedding_cache, cache_key):
        return getattr(_embedding_cache, cache_key)
    try:
        vector = await embed_text_async(query, timeout=30)
    except Exception as exc:
        logger.warning("Query embedding failed: %s", exc)
        vector = None
    setattr(_embedding_cache, cache_key, vector)
    return vector


def _clear_embedding_cache() -> None:
    for attr in list(dir(_embedding_cache)):
        if attr.startswith("embedding_"):
            delattr(_embedding_cache, attr)


def _format_node(node: dict[str, Any], relation: str = "states") -> dict[str, Any]:
    content = str(node.get("content", ""))
    return {
        "id": str(node.get("id") or node.get("node_id")),
        "content": content,
        "entity": node.get("node_type", "fact"),
        "relation": relation,
        "target": content,
        "category": node.get("node_type", "fact"),
        "confidence": float(
            node.get("confidence", node.get("node_confidence", 0.5)) or 0.5
        ),
        "importance": float(node.get("importance", 0.5) or 0.5),
        "score": float(node.get("score", 0.0) or 0.0),
        "evidence": node.get("evidence", []),
        "valid_from": node.get("valid_from"),
        "valid_until": node.get("valid_until"),
    }


async def retrieve_memories_combined_async(
    session_id: str,
    query: str | None = None,
    static_limit: int = 10,
    dynamic_limit: int = 5,
    user_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not user_id:
        raise ValueError("retrieve_memories_combined_async: user_id is required")
    if not get_provider_key(YUZU_PORTAL):
        logger.info("memory retrieval disabled: missing Yuzu Portal API key")
        return [], []

    nodes: list[dict[str, Any]] = []
    if query:
        vector = await _get_cached_embedding_async(query)
        if vector:
            nodes = await GraphMemoryRepository.search_nodes_vector(
                user_id=user_id, embedding=vector, limit=static_limit
            )
        if not nodes:
            nodes = await GraphMemoryRepository.search_nodes(
                user_id=user_id, query=query, limit=static_limit
            )
    else:
        nodes = await GraphMemoryRepository.search_nodes(
            user_id=user_id, query="", limit=static_limit
        )

    static: list[dict[str, Any]] = []
    dynamic: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in nodes:
        node_id = str(raw.get("id"))
        if node_id in seen:
            continue
        seen.add(node_id)
        formatted = _format_node(raw)
        formatted["evidence"] = await GraphMemoryRepository.get_node_provenance(
            user_id=user_id, node_id=node_id
        )
        static.append(formatted)
        related = await GraphMemoryRepository.expand_nodes(
            user_id=user_id, node_id=node_id, limit=2
        )
        for related_raw in related:
            related_id = str(related_raw.get("node_id"))
            if related_id in seen:
                continue
            seen.add(related_id)
            related_formatted = _format_node(
                related_raw, related_raw.get("edge_type", "related_to")
            )
            related_formatted[
                "evidence"
            ] = await GraphMemoryRepository.get_node_provenance(
                user_id=user_id, node_id=related_id
            )
            dynamic.append(related_formatted)
            if len(dynamic) >= dynamic_limit:
                break
        if len(static) >= static_limit:
            break
    return static, dynamic[:dynamic_limit]


async def retrieve_memory_async(
    session_id: str, query: str | None = None, user_id: str | None = None
) -> dict[str, Any]:
    static, dynamic = await retrieve_memories_combined_async(
        session_id, query=query, static_limit=8, dynamic_limit=4, user_id=user_id
    )
    return {"static": static, "dynamic": dynamic, "temporal_messages": []}


def retrieve_memory(
    session_id: str, query: str | None = None, user_id: str | None = None
) -> dict[str, Any]:
    raise RuntimeError(
        "Synchronous memory retrieval is not supported; use async retrieval"
    )


def _format_static_context(static: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- [memory:{item['id']} score:{item['score']:.3f} category:{item['category']}] "
        f"{item['entity']} {item['relation']} {item['target']}"
        for item in static[:10]
    )


def _format_dynamic_context(dynamic: list[dict[str, Any]]) -> str:
    if not dynamic:
        return ""
    return "\n\nRecent related memories:\n" + "\n".join(
        f"- [memory:{item['id']} score:{item['score']:.3f}] {item['content'][:150]}"
        for item in dynamic[:5]
    )


def format_memory(memory_bundle: dict[str, Any]) -> str:
    parts: list[str] = []
    static = memory_bundle.get("static", [])
    if static:
        parts.append("Known inferred memory:\n" + _format_static_context(static))
    dynamic = memory_bundle.get("dynamic", [])
    if dynamic:
        parts.append(_format_dynamic_context(dynamic).strip())
    return "\n".join(part for part in parts if part)


def retrieve_for_context(*args: Any, **kwargs: Any) -> tuple[list[str], str]:
    raise RuntimeError(
        "Synchronous memory retrieval is not supported; use async retrieval"
    )


async def retrieve_for_context_async(
    session_id: str,
    query: str | None = None,
    limit: int = 10,
    user_id: str | None = None,
) -> tuple[list[str], str]:
    static, _ = await retrieve_memories_combined_async(
        session_id, query=query, static_limit=limit, dynamic_limit=0, user_id=user_id
    )
    return [item["id"] for item in static], _format_static_context(static)


__all__ = [
    "retrieve_memories_combined_async",
    "retrieve_memory_async",
    "retrieve_memory",
    "retrieve_for_context_async",
    "format_memory",
    "_clear_embedding_cache",
]
