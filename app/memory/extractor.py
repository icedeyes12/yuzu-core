# FILE: app/memory/extractor.py
# DESCRIPTION: LLM-only semantic fact extraction - uses db_memory for storage

from __future__ import annotations

__all__ = [
    "process_messages_for_memory",
    "extract_semantic_facts",
    "upsert_semantic_memory",
    "create_episodic_memory",
    "generate_episodic_summary",
    "calculate_emotional_weight",
    "should_create_episodic",
]

from app.memory.db_memory import (
    save_fact,
    search_similar,
    FACT_TYPE_STATIC,
    FACT_TYPE_DYNAMIC,
)


def _get_ai_manager():
    """Lazy-import to avoid circular imports."""
    from app import get_ai_manager
    return get_ai_manager()


# ── Semantic extraction (LLM-only) ──────────────────────────────────────────────

def extract_semantic_facts(messages) -> list[dict]:
    """Extract semantic facts from messages using LLM only.

    Returns list of dicts: {entity, relation, target}
    """
    if not messages:
        return []

    try:
        ai_manager = _get_ai_manager()
    except Exception as e:
        print(f"[WARNING] AI manager unavailable: {e}")
        return []

    # Build conversation text
    conversation = "\n".join(
        f"{'User' if m.get('role') == 'user' else 'AI'}: {m.get('content', '')}"
        for m in messages
        if m.get("role") in ("user", "assistant")
    )

    if not conversation.strip():
        return []

    system_prompt = """You are a HIGH-QUALITY knowledge extraction specialist.

Extract ONLY persistent, high-value facts from the user's messages.

## CRITICAL: Extract ONLY facts that pass ALL FOUR tests:
1. Persistence Test — Will this still be true in 6 months?
2. Specificity Test — Does it contain concrete, searchable information?
3. Utility Test — Can this help predict future user needs or preferences?
4. Independence Test — Can this be understood WITHOUT the conversation context?

## CATEGORIES (use as relation):
- identity: name, profession, location, company, education
- preference: likes, dislikes, favorites, stylistic choices
- interest: topics, hobbies, domains they engage with
- personality: communication style, emotional tendencies
- relationship: how they treat you, shared routines, inside jokes
- experience: skills, past events, professional background
- goal: plans, aspirations, things they're working toward
- guideline: how you (assistant) should behave around them

## SKIP:
- single-emotion reactions (happy, sad, frustrated in one moment)
- acknowledgments or greetings
- vague statements without specifics
- context-dependent information

## OUTPUT: JSON array only, no markdown, no explanation.
[{"entity": "User", "relation": "preference", "target": "..."}]"""

    user_prompt = f"Extract facts from this conversation:\n\n{conversation}\n\nRespond with a JSON array of facts."

    try:
        response = ai_manager._internal_llm_call(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=30,
            max_tokens=800,
        )
        if not response:
            return []

        import json
        print(f"[DEBUG extract_semantic_facts] conv_len={len(conversation)} chars, raw_response (first 500): {response[:500]}")
        try:
            facts = json.loads(response)
        except json.JSONDecodeError:
            # Response may be truncated mid-JSON; find last valid close bracket
            facts = []
            for i in range(len(response), 0, -1):
                try:
                    facts = json.loads(response[:i])
                    if isinstance(facts, list):
                        break
                except json.JSONDecodeError:
                    continue
            if not isinstance(facts, list):
                print(f"[WARNING] LLM returned invalid JSON (len={len(response)}), skipping extraction")
                return []
        if not isinstance(facts, list):
            return []

        # Validate and clean
        cleaned = []
        for f in facts:
            if (
                isinstance(f, dict)
                and f.get("entity")
                and f.get("relation")
                and f.get("target")
            ):
                target = str(f["target"]).strip()
                if 3 < len(target) < 300:
                    cleaned.append({
                        "entity": "User",
                        "relation": f["relation"].title(),
                        "target": target,
                    })
        return cleaned

    except Exception as e:
        print(f"[WARNING] LLM fact extraction failed: {e}")
        return []


# ── Episodic helpers ───────────────────────────────────────────────────────────

_EMOTIONAL_KEYWORDS = [
    "angry", "frustrated", "sad", "happy", "excited", "love",
    "hate", "cry", "laugh", "upset", "worried", "scared",
    "marah", "kesal", "sedih", "senang", "sayang", "benci",
    "takut", "khawatir", "kecewa",
]


def calculate_emotional_weight(messages) -> float:
    """Calculate emotional intensity. Returns 0.0–1.0."""
    if not messages:
        return 0.0
    total_hits = sum(
        1
        for msg in messages
        for kw in _EMOTIONAL_KEYWORDS
        if kw in msg.get("content", "").lower()
    )
    return min(total_hits / max(len(messages), 1) * 0.3, 1.0)


def should_create_episodic(messages, affection_delta: float = 0) -> bool:
    """Trigger episodic memory on emotion, length, or affection change."""
    if not messages:
        return False
    if calculate_emotional_weight(messages) >= 0.3:
        return True
    if len(messages) >= 10:
        return True
    if abs(affection_delta) >= 20:
        return True
    return False


def generate_episodic_summary(messages) -> str | None:
    """Generate episodic summary via LLM. Returns None on failure."""
    if not messages:
        return None

    try:
        ai_manager = _get_ai_manager()
    except Exception:
        return None

    # Build conversation for summarization
    prompt_messages = [
        {
            "role": "system",
            "content": (
                "You are a memory summarizer. Produce a concise 1-3 sentence "
                "third-person summary of the conversation. Focus on: what topic "
                "was discussed, any decisions made, and the user's emotional state. "
                "Be specific and factual. Do not add information not present."
            ),
        }
    ]
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") for c in content if c.get("type") == "text"
            )
        if role in ("user", "assistant"):
            label = "User" if role == "user" else "AI"
            prompt_messages.append({"role": "user", "content": f"{label}: {content}"})

    try:
        response = ai_manager._internal_llm_call(
            messages=prompt_messages,
            timeout=30,
            max_tokens=800,
        )
        if response and isinstance(response, str) and response.strip():
            return response.strip()
    except Exception as e:
        print(f"[WARNING] Episodic LLM summarization failed: {e}")

    return None


def _build_semantic_text(entity, relation, target) -> str:
    """Build a searchable text from a semantic triple."""
    return f"{entity} {relation} {target}"


# ── Storage (using db_memory) ──────────────────────────────────────────────────

def upsert_semantic_memory(session_id, entity, relation, target):
    """Insert or update a semantic memory with embedding.

    Duplicate detection: vector search for top-5 similar records;
    if any distance < 0.05, reinforce the existing record.
    """
    text = _build_semantic_text(entity, relation, target)
    
    # Embed the text
    try:
        from app.memory.embedder import embed_text
        vector = embed_text(text)
    except Exception as e:
        print(f"[WARNING] Embedding failed: {e}")
        vector = None

    if vector is not None:
        # Check for duplicates
        existing = search_similar(
            embedding=vector,
            session_id=session_id,
            fact_type=FACT_TYPE_STATIC,
            limit=5,
            max_distance=0.05,
        )
        
        if existing and len(existing) > 0:
            # Duplicate found — reinforce existing
            from app.memory.db_memory import increment_importance
            increment_importance(existing[0].get("id"), delta=0.1, cap=1.0)
            return  # done — no insert needed

    # No duplicate — insert new fact
    save_fact(
        session_id=session_id,
        content=f"{entity} {relation} {target}",
        embedding=vector,
        fact_type=FACT_TYPE_STATIC,
        metadata={
            "entity": entity,
            "relation": relation,
            "target": target,
            "confidence": 0.7,
            "importance": 0.7,
            "source_table": "semantic_memories",
            "session_id": session_id,
        },
    )


def create_episodic_memory(session_id, summary, emotional_weight=0.0, importance=0.5, source_message_ids=None):
    """Create a new episodic memory record with embedding.

    Args:
        session_id: session this episodic memory belongs to
        summary: LLM-generated narrative summary
        emotional_weight: 0.0-1.0 emotional intensity score
        importance: 0.0-1.0 importance score
        source_message_ids: list of message IDs (for cross-layer tracing)
    """
    # Embed the summary
    try:
        from app.memory.embedder import embed_text
        vector = embed_text(summary)
    except Exception as e:
        print(f"[WARNING] Embedding failed: {e}")
        vector = None

    save_fact(
        session_id=session_id,
        content=summary,
        embedding=vector,
        fact_type=FACT_TYPE_DYNAMIC,
        metadata={
            "importance": importance,
            "emotional_weight": emotional_weight,
            "source_table": "episodic_memories",
            "source_message_ids": source_message_ids,
            "session_id": session_id,
        },
    )


# ── Main entry point ─────────────────────────────────────────────────────────

def process_messages_for_memory(session_id, messages, affection_delta: float = 0):
    """Analyze messages and extract memories (LLM-only semantic, LLM episodic).

    This is called from session init. Idempotent per session.
    """
    if not messages:
        return

    # 1. LLM semantic extraction
    try:
        facts = extract_semantic_facts(messages)
        for fact in facts:
            try:
                upsert_semantic_memory(
                    session_id,
                    fact["entity"],
                    fact["relation"],
                    fact["target"],
                )
            except Exception as e:
                print(f"[WARNING] Semantic memory upsert failed: {e}")
    except Exception as e:
        print(f"[WARNING] Semantic fact extraction failed: {e}")

    # 2. Episodic if emotionally significant
    if should_create_episodic(messages, affection_delta):
        emotional_weight = calculate_emotional_weight(messages)
        summary = generate_episodic_summary(messages)
        if summary:
            try:
                importance = 0.5 + emotional_weight * 0.3
                create_episodic_memory(
                    session_id, summary, emotional_weight, importance
                )
            except Exception as e:
                print(f"[WARNING] Episodic memory creation failed: {e}")