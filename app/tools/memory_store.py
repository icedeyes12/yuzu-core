# FILE: app/tools/memory_store.py
# DESCRIPTION: Tool for storing memories to PostgreSQL vector database

from app.tools.schemas import ToolDefinition, ToolParam, ok_result, error_result
from app.memory.db_memory import save_fact, search_similar, FACT_TYPE_STATIC


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
            enum=["Identity", "Preference", "Interest", "Personality",
                  "Relationship", "Experience", "Goal", "Guideline"],
        ),
    ],
    needs_session=True,
    is_terminal=True,
)


def _classify_category_llm(fact: str) -> str:
    """Classify a fact into a memory category using LLM.

    Returns one of: Identity, Preference, Interest, Personality,
    Relationship, Experience, Goal, Guideline.
    """
    try:
        from app import get_ai_manager
        ai_manager = get_ai_manager()
    except Exception as e:
        print(f"[memory_store] AI manager unavailable: {e}")
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
        response = ai_manager._internal_llm_call(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Fact: {fact}"},
            ],
            timeout=15,
            max_tokens=30,
        )
        if response:
            category = response.strip().title()
            valid = {"Identity", "Preference", "Interest", "Personality",
                     "Relationship", "Experience", "Goal", "Guideline"}
            if category in valid:
                return category
    except Exception as e:
        print(f"[memory_store] LLM classification failed: {e}")

    return "Identity"


def execute(arguments, **kwargs):
    session_id = kwargs.get("session_id")
    from app.db_pg_models import get_profile
    from app.memory.embedder import embed_texts

    profile = get_profile() or {}
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
        category = _classify_category_llm(fact)
    full_command = f'/memory_store fact="{fact[:60]}" category={category}'

    # Embed the fact text
    fact_embed_text = f"[{category}] {fact}"
    try:
        vecs = embed_texts([fact_embed_text])
        if not vecs:
            return error_result(
                "Embedding service unavailable",
                TOOL_DEFINITION,
                full_command,
                partner_name,
            )
        vector = vecs[0]
    except Exception as e:
        print(f"[memory_store] Embed failed: {e}")
        return error_result(
            "Embedding service unavailable",
            TOOL_DEFINITION,
            full_command,
            partner_name,
        )

    # Check for duplicate using vector distance
    existing = search_similar(
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
            from app.memory.db_memory import increment_importance
            increment_importance(e["id"], delta=0.1, cap=1.0)
            new_confidence = e.get("metadata", {}).get("confidence", 0.7)
            return ok_result(
                {"status": "duplicate", "confidence": new_confidence},
                TOOL_DEFINITION,
                full_command,
                partner_name,
            )

    # Insert new fact into semantic_facts
    fact_id = save_fact(
        session_id=session_id,
        content=f"{category} {fact}",  # Store as "category fact" for searchability
        embedding=vector,
        fact_type=FACT_TYPE_STATIC,
        metadata={
            "category": category,
            "entity": "User",
            "relation": category,
            "target": fact,
            "confidence": 0.7,
            "importance": 0.6,
            "source_table": "semantic_memories",
            "session_id": session_id,
        },
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