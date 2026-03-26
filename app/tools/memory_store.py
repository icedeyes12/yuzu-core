# FILE: app/tools/memory_store.py
# DESCRIPTION: Tool for storing memories to vector database

from datetime import datetime
from app.database import Database, get_db_session, SemanticMemory
from app.memory.embedder import embed_texts
from app.memory.embedder import cosine_similarity, blob_to_vec, vec_to_blob
from app.memory.vector_store import mark_dirty
from app.tools.registry import build_markdown_contract


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
        response = ai_manager.auto_send_message(
            provider=None,
            model=None,
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
    profile = Database.get_profile() or {}
    partner_name = profile.get("partner_name", "Yuzu")

    fact = arguments.get("fact", "").strip()
    if not fact:
        return build_markdown_contract(
            "memory_store_tools",
            "/memory_store",
            ["Error: 'fact' is required"],
            partner_name,
        )

    if len(fact) < 5:
        return build_markdown_contract(
            "memory_store_tools",
            "/memory_store",
            ["Error: Fact too short (min 5 chars)"],
            partner_name,
        )

    if len(fact) > 500:
        return build_markdown_contract(
            "memory_store_tools",
            "/memory_store",
            ["Error: Fact too long (max 500 chars)"],
            partner_name,
        )

    category = arguments.get("category")
    if not category:
        category = _classify_category_llm(fact)
    full_command = f"/memory_store fact=\"{fact[:60]}\" category={category}"

    # Embed the fact text
    fact_embed_text = f"[{category}] {fact}"
    try:
        vecs = embed_texts([fact_embed_text])
        vector = vecs[0]  # extract single vector from list
    except Exception as e:
        print(f"[memory_store] Embed failed: {e}")
        return build_markdown_contract(
            "memory_store_tools",
            full_command,
            ["Error: Embedding service unavailable"],
            partner_name,
        )

    # Check for duplicate using cosine similarity
    with get_db_session() as session:
        existing = session.query(SemanticMemory).filter(
            SemanticMemory.session_id == session_id,
        ).all()

        duplicate_id = None
        for rec in existing:
            if rec.embedding_vector:
                try:
                    rec_vec = blob_to_vec(rec.embedding_vector)
                    sim = cosine_similarity(vector, rec_vec)
                    if sim > 0.95:
                        duplicate_id = rec.id
                        break
                except Exception:
                    pass

        if duplicate_id:
            rec = session.query(SemanticMemory).filter_by(id=duplicate_id).first()
            if rec:
                rec.confidence = min((rec.confidence or 0.5) + 0.1, 1.0)
                rec.access_count = (rec.access_count or 0) + 1
                rec.last_accessed = datetime.now()
                session.commit()
            return build_markdown_contract(
                "memory_store_tools",
                full_command,
                [f"Already remembered (confidence {rec.confidence:.2f})"],
                partner_name,
            )

        # Insert new fact — store as blob bytes, not raw list
        new_mem = SemanticMemory(
            session_id=session_id,
            entity="User",
            relation=category,
            target=fact,
            confidence=0.7,
            importance=0.6,
            embedding_vector=vec_to_blob(vector),
            last_accessed=datetime.now(),
            access_count=1,
        )
        session.add(new_mem)
        session.commit()
        mark_dirty(session_id, "semantic")

    return build_markdown_contract(
        "memory_store_tools",
        full_command,
        [f"Stored: [{category}] {fact}"],
        partner_name,
    )
