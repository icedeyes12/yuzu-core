from __future__ import annotations

import logging
from typing import Any

from app.db import Database
from app.tools.schemas import ToolDefinition, ToolParam, error_result, ok_result

logger = logging.getLogger(__name__)

_CATEGORIES = (
    "Identity",
    "Preference",
    "Interest",
    "Personality",
    "Relationship",
    "Experience",
    "Goal",
    "Guideline",
)

TOOL_DEFINITION = ToolDefinition(
    name="memory_store",
    description="Store an inferred, durable fact about the user in graph memory.",
    role="memory_store_tools",
    parameters=[
        ToolParam(
            name="fact",
            description="The fact or information to store (5-500 characters)",
            type="string",
            required=True,
        ),
        ToolParam(
            name="category",
            description="Memory category.",
            type="string",
            required=False,
            enum=list(_CATEGORIES),
        ),
    ],
    needs_session=True,
)


async def _classify_category_llm_async(fact: str, profile: dict[str, Any]) -> str:
    """Classify a fact into one graph node category."""
    try:
        from app.providers import get_ai_manager

        manager = await get_ai_manager()
        response = await manager._internal_llm_call(
            messages=[
                {
                    "role": "system",
                    "content": "Return exactly one category: " + ", ".join(_CATEGORIES),
                },
                {"role": "user", "content": fact},
            ],
            timeout=15,
            profile=profile,
        )
        category = str(response or "").strip().title()
        return category if category in _CATEGORIES else "Experience"
    except Exception as exc:
        logger.warning("memory category classification failed: %s", exc)
        return "Experience"


async def execute(arguments, **kwargs):
    session_id = kwargs.get("session_id")
    user_id = kwargs.get("user_id")
    profile = await Database.get_profile(user_id) or {}
    partner_name = profile.get("partner_name", "Yuzu")
    fact = str(arguments.get("fact", "")).strip()

    if not session_id or not user_id:
        return error_result(
            "session_id and user_id required",
            TOOL_DEFINITION,
            "/memory_store",
            partner_name,
        )
    if len(fact) < 5:
        return error_result(
            "Fact too short (min 5 chars)",
            TOOL_DEFINITION,
            "/memory_store",
            partner_name,
        )
    if len(fact) > 500:
        return error_result(
            "Fact too long (max 500 chars)",
            TOOL_DEFINITION,
            "/memory_store",
            partner_name,
        )

    category = str(arguments.get("category") or "").strip().title()
    if category not in _CATEGORIES:
        category = await _classify_category_llm_async(fact, profile)
    content = f"[{category}] {fact}"
    try:
        from app.memory.embedder import embed_text_async
        from app.memory.graph import GraphMemoryRepository

        embedding = await embed_text_async(content, timeout=30)
        node = await GraphMemoryRepository.get_or_create_node(
            user_id=user_id,
            node_type=category.lower(),
            content=fact,
            embedding=embedding,
            confidence=0.7,
            importance=0.6,
            embedding_model="qwen3-embedding-8b",
            embedding_dimensions=len(embedding) if embedding else None,
        )
    except Exception as exc:
        logger.warning("graph memory store failed: %s", exc)
        return error_result(
            "Failed to store memory", TOOL_DEFINITION, "/memory_store", partner_name
        )

    if not node:
        return error_result(
            "Failed to store memory", TOOL_DEFINITION, "/memory_store", partner_name
        )
    return ok_result(
        {"status": "stored", "category": category, "fact": fact, "id": str(node["id"])},
        TOOL_DEFINITION,
        f'/memory_store fact="{fact[:60]}" category={category}',
        partner_name,
    )
