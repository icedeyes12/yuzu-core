from datetime import datetime
from database import Database, get_db_session, SemanticMemory
from memory.embedder import embed_text, vec_to_blob
from tools.registry import build_markdown_contract


def _infer_category(fact):
    s = fact.lower()
    if any(w in s for w in ["prefer", "like", "love", "hate", "dislike", "favorit"]):
        return "Preference"
    if any(w in s for w in ["name", "live", "work", "job", "career", "company", "city"]):
        return "Identity"
    if any(w in s for w in ["interest", "hobby", "learn", "study"]):
        return "Interest"
    if any(w in s for w in ["should", "avoid", "never", "always", "tone", "behave"]):
        return "Guideline"
    if any(w in s for w in ["goal", "plan", "want", "aspire"]):
        return "Goal"
    if any(w in s for w in ["family", "friend", "relationship", "partner"]):
        return "Relationship"
    if any(w in s for w in ["skill", "experience", "past"]):
        return "Experience"
    if any(w in s for w in ["personality", "style", "tend", "usually"]):
        return "Personality"
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
            ["Error: Fact too short"],
            partner_name,
        )
    if len(fact) > 500:
        return build_markdown_contract(
            "memory_store_tools",
            "/memory_store",
            ["Error: Fact too long (max 500 chars)"],
            partner_name,
        )

    entity = arguments.get("entity", "User")
    relation = arguments.get("relation", "Identity")
    category = arguments.get("category", _infer_category(fact))
    full_command = f"/memory_store fact={fact[:80]}..."

    try:
        vector = embed_text(f"{entity} {relation} {fact}")
    except Exception as e:
        print(f"[memory_store] Embed failed: {e}")
        return build_markdown_contract(
            "memory_store_tools",
            full_command,
            ["Error: Embedding service unavailable"],
            partner_name,
        )

    with get_db_session() as session:
        existing = session.query(SemanticMemory).filter(
            SemanticMemory.session_id == session_id,
            SemanticMemory.entity == entity,
            SemanticMemory.relation == relation,
            SemanticMemory.target == fact,
        ).first()

        if existing:
            existing.confidence = min((existing.confidence or 0.5) + 0.1, 1.0)
            existing.access_count = (existing.access_count or 0) + 1
            existing.last_accessed = datetime.now()
            session.commit()
            return build_markdown_contract(
                "memory_store_tools",
                full_command,
                [f"Already remembered (confidence {existing.confidence:.2f})"],
                partner_name,
            )

        new_mem = SemanticMemory(
            session_id=session_id,
            entity=entity,
            relation=relation,
            target=fact,
            confidence=0.7,
            importance=0.6,
            embedding_vector=vec_to_blob(vector),
            last_accessed=datetime.now(),
            access_count=1,
        )
        session.add(new_mem)
        session.commit()

    return build_markdown_contract(
        "memory_store_tools",
        full_command,
        [f"Stored: [{category}] {entity} {relation} {fact}"],
        partner_name,
    )
