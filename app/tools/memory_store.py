from __future__ import annotations
# FILE: app/tools/memory_store.py
# DESCRIPTION: Tool for storing memories to PostgreSQL vector database


import logging
from app.tools.schemas import ToolDefinition, ToolParam, ok_result, error_result
from app.memory.db_memory_facade import MemoryDB, FACT_TYPE_STATIC
from app.db import Database

logger = logging.getLogger(__name__)


TOOL_DEFINITION = ToolDefinition(
    name="memory_store",
    description="Store a new fact or piece of information about the user into long-term memory. "
    "The system auto-classifies into categories: Identity, Preference, Interest, "
    "Personality, Relationship, Experience, Goal, or Guideline.",
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
            description="Optional memory category. If omitted, auto-detected by LLM.",
            type="string",
            required=False,
            enum=[
                "Identity",
                "Preference",
                "Interest",
                "Personality",
                "Relationship",
                "Experience",
                "Goal",
                "Guideline",
            ],
        ),
    ],
    needs_session=True,
    is_terminal=True,
)


async def _classify_category_llm_async(fact: str) -> str:
    """Classify a fact into a memory category using LLM (async)."""
    try:
        # WORKAROUND: Lazy import to prevent circular dependency with app.providers
        from app.providers import get_ai_manager

        ai_manager = await get_ai_manager()
    except Exception as e:
        logger.warning(f"[memory_store] AI manager unavailable: {e}")
        return "Identity"

    system_prompt = """You are a memory categorizer. Classify the following fact into exactly ONE category.

Categories:
- Identity: name, profession, location, company, education, demographics
- Preference: likes, dislikes, favorites, stylistic choices, habits
- Interest: topics, hobbies, domains they engage with
- Personality: communication style, emotional tendencies, character traits
- Relationship: how they treat you, shared routines, inside jokes, social bonds
- Experience: skills, past events, professional background, completed projects
- Goal: plans, aspirations, things they're working toward
- Guideline: how you (assistant) should behave around them

Respond with ONLY the category name, nothing else."""

    try:
        response = await ai_manager._internal_llm_call(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Fact: {fact}"},
            ],
            timeout=15,
            max_tokens=30,
        )
        if response:
            category = response.strip().title()
            valid = {
                "Identity",
                "Preference",
                "Interest",
                "Personality",
                "Relationship",
                "Experience",
                "Goal",
                "Guideline",
            }
            if category in valid:
                return category
    except Exception as e:
        logger.warning(f"[memory_store] LLM classification failed: {e}")

    return "Identity"


async def execute(arguments, **kwargs):
    session_id = kwargs.get("session_id")
    user_id = kwargs.get("user_id")
    from app.memory.embedder import embed_texts_async

    profile = await Database.get_profile_async(user_id) or {}
    partner_name = profile.get("partner_name", "Yuzu")

    fact = arguments.get("fact", "").strip()
    if not fact:
        return error_result(
            "'fact' is required",
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

    category = arguments.get("category")
    if not category:
        category = await _classify_category_llm_async(fact)
    full_command = f'/memory_store fact="{fact[:60]}" category={category}'

    # Embed the fact text
    fact_embed_text = f"[{category}] {fact}"
    try:
        vecs = await embed_texts_async([fact_embed_text])
        if not vecs:
            return error_result(
                "Embedding service unavailable",
                TOOL_DEFINITION,
                full_command,
                partner_name,
            )
        vector = vecs[0]
    except Exception as e:
        logger.warning(f"[memory_store] Embed failed: {e}")
        return error_result(
            "Embedding service unavailable",
            TOOL_DEFINITION,
            full_command,
            partner_name,
        )

    # Check for duplicate using vector distance
    existing = await MemoryDB.search_similar_async(
        embedding=vector,
        session_id=session_id,
        fact_type=FACT_TYPE_STATIC,
        limit=1,
        max_distance=0.05,
    )

    if existing:
        e = existing[0]
        if e:
            # Duplicate found — reinforce existing fact
            from app.db import pg_execute_async
            from app.memory.db_memory_queries import SQL_FACT_UPDATE_METADATA
            from datetime import datetime
            from psycopg.types.json import Json

            meta = e.get("metadata") or {}
            current = meta.get("importance") or 0.5
            meta["importance"] = min(current + 0.1, 1.0)
            meta["access_count"] = (meta.get("access_count") or 0) + 1

            await pg_execute_async(
                SQL_FACT_UPDATE_METADATA,
                (datetime.now(), Json(meta), e["id"], user_id),
            )

            new_confidence = e.get("metadata", {}).get("confidence", 0.7)
            return ok_result(
                {"status": "duplicate", "confidence": new_confidence},
                TOOL_DEFINITION,
                full_command,
                partner_name,
            )

    # Insert new fact into semantic_facts
    fact_id = await MemoryDB.save_fact_async(
        session_id=session_id,
        content=fact,
        embedding=vector,
        fact_type=FACT_TYPE_STATIC,
        metadata={
            "category": category,
            "entity": "User",
            "relation": category,
            "target": fact,
            "confidence": 0.7,
            "importance": 0.6,
            "source_table": "semantic_facts",
            "session_id": session_id,
            "access_count": 0,
        },
        user_id=user_id,
    )

    if fact_id:
        return ok_result(
            {"status": "stored", "category": category, "fact": fact, "id": fact_id},
            TOOL_DEFINITION,
            full_command,
            partner_name,
        )
    else:
        return error_result(
            "Failed to store memory",
            TOOL_DEFINITION,
            full_command,
            partner_name,
        )
