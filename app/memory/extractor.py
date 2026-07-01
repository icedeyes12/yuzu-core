from __future__ import annotations

import logging
from datetime import datetime
from psycopg.types.json import Json

__all__ = [
    "upsert_semantic_memory",
    "upsert_semantic_memory_async",
    "create_episodic_memory",
    "create_episodic_memory_async",
    "calculate_emotional_weight",
]

from app.memory.db_memory_facade import (
    MemoryDB,
    FACT_TYPE_STATIC,
    FACT_TYPE_DYNAMIC,
)
from app.db import pg_fetchone_async, pg_execute_async

logger = logging.getLogger(__name__)


# ── Emotional keywords for weight calculation ─────────────────────────────────
_EMOTIONAL_KEYWORDS = [
    "angry",
    "frustrated",
    "sad",
    "happy",
    "excited",
    "love",
    "hate",
    "cry",
    "laugh",
    "upset",
    "worried",
    "scared",
    "marah",
    "kesal",
    "sedih",
    "senang",
    "sayang",
    "benci",
    "takut",
    "khawatir",
    "kecewa",
]


# NOTE: No sync _get_ai_manager helper - use async functions throughout
# All semantic memory operations should use async versions


# ── Semantic extraction (LLM-only) ──────────────────────────────────────────────


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


def _build_semantic_text(entity, relation, target) -> str:
    """Build a searchable text from a semantic triple."""
    return f"{entity} {relation} {target}"


# ── Storage (using db_memory) ──────────────────────────────────────────────────

_RELATION_TO_CATEGORY = {
    # identity
    "identity": "Identity",
    "name": "Identity",
    "profession": "Identity",
    "location": "Identity",
    "company": "Identity",
    "education": "Identity",
    "demographics": "Identity",
    # preference
    "preference": "Preference",
    "likes": "Preference",
    "dislikes": "Preference",
    "favorites": "Preference",
    "habit": "Preference",
    # interest
    "interest": "Interest",
    "hobby": "Interest",
    "topic": "Interest",
    # personality
    "personality": "Personality",
    "communication_style": "Personality",
    "emotional_tendency": "Personality",
    "trait": "Personality",
    # relationship
    "relationship": "Relationship",
    "shared_routine": "Relationship",
    "inside_joke": "Relationship",
    # experience
    "experience": "Experience",
    "skill": "Experience",
    "past_event": "Experience",
    "background": "Experience",
    # goal
    "goal": "Goal",
    "aspiration": "Goal",
    "plan": "Goal",
    # guideline
    "guideline": "Guideline",
    "behavior": "Guideline",
    "tone": "Guideline",
}

# Stricter dedup: was 0.05, tightened to 0.03 to reduce noise
_EXTRACTOR_DEDUP_THRESHOLD = 0.03


def _map_relation_to_category(relation: str) -> str:
    """Map a relation keyword to one of the 8 categories."""
    key = relation.lower().strip()
    return _RELATION_TO_CATEGORY.get(key, "Experience")


def upsert_semantic_memory(
    session_id, entity, relation, target, episode_id=None, user_id=None
):
    """Insert or update a semantic memory with embedding and 8-category taxonomy.

    Duplicate detection: vector search for top-5 similar records;
    if any distance < 0.05, reinforce the existing record.
    On reinforce: append to source_episodic_ids.
    On new: initialize source_episodic_ids = [episode_id] if provided.
    """
    category = _map_relation_to_category(relation)
    text = _build_semantic_text(entity, relation, target)

    # Embed the text
    try:
        from app.memory.embedder import embed_text

        vector = embed_text(text)
    except Exception as e:
        logger.warning(f"Embedding failed: {e}")
        vector = None

    if vector is not None:
        # Check for duplicates using stricter threshold
        existing = MemoryDB.search_similar(
            embedding=vector,
            session_id=session_id,
            fact_type=FACT_TYPE_STATIC,
            limit=5,
            max_distance=_EXTRACTOR_DEDUP_THRESHOLD,
            user_id=user_id,
        )

        # FALLBACK: text-level dedupe (in case embedding failed)
        if existing and len(existing) > 0:
            e = existing[0]
            if e.get("content") == text:
                # Exact content match — reinforce existing
                from app.memory.db_memory_facade import MemoryDB

                from app.db import pg_execute
                from datetime import datetime

                MemoryDB.increment_importance(
                    e["id"], delta=0.1, cap=1.0, user_id=user_id
                )
                meta = e.get("metadata") or {}
                ids = meta.get("source_episodic_ids", [])
                if episode_id and episode_id not in ids:
                    ids.append(episode_id)
                elif not ids:
                    ids = [episode_id] if episode_id else []
                meta["source_episodic_ids"] = ids
                meta["category"] = category
                pg_execute(
                    "UPDATE semantic_facts SET last_accessed=%s, metadata=%s WHERE id=%s",
                    (datetime.now(), Json(meta), e["id"]),
                )
                return  # done — no insert needed

        # Also check by exact content match directly in DB
        from app.db import pg_fetchone

        existing_exact = pg_fetchone(
            "SELECT id, metadata FROM semantic_facts WHERE fact_type=%s AND content=%s AND invalid_at IS NULL AND user_id=%s LIMIT 1",
            (FACT_TYPE_STATIC, text, user_id),
        )
        if existing_exact:
            from app.memory.db_memory_facade import MemoryDB

            from app.db import pg_execute
            from datetime import datetime

            MemoryDB.increment_importance(
                existing_exact["id"], delta=0.1, cap=1.0, user_id=user_id
            )
            meta = existing_exact.get("metadata") or {}
            ids = meta.get("source_episodic_ids", [])
            if episode_id and episode_id not in ids:
                ids.append(episode_id)
            elif not ids:
                ids = [episode_id] if episode_id else []
            meta["source_episodic_ids"] = ids
            meta["category"] = category
            pg_execute(
                "UPDATE semantic_facts SET last_accessed=%s, metadata=%s WHERE id=%s",
                (datetime.now(), Json(meta), existing_exact["id"]),
            )
            return  # exact content dupe — reinforce, don't insert

    # No duplicate — insert new fact
    metadata = {
        "entity": entity,
        "relation": relation,
        "target": target,
        "confidence": 0.7,
        "importance": 0.7,
        "category": category,
        "source_table": "semantic_memories",
        "session_id": session_id,
    }
    if episode_id:
        metadata["source_episodic_ids"] = [episode_id]

    MemoryDB.save_fact(
        session_id=session_id,
        content=f"{entity} {relation} {target}",
        embedding=vector,
        fact_type=FACT_TYPE_STATIC,
        metadata=metadata,
        category=category,
        user_id=user_id,
    )


async def upsert_semantic_memory_async(
    session_id, entity, relation, target, episode_id=None, user_id=None
):
    """Async version of upsert_semantic_memory."""
    category = _map_relation_to_category(relation)
    text = _build_semantic_text(entity, relation, target)

    try:
        from app.memory.embedder import embed_text_async

        vector = await embed_text_async(text)
    except Exception as e:
        logger.warning(f"Embedding async failed: {e}")
        vector = None

    if vector is not None:
        existing = await MemoryDB.search_similar_async(
            embedding=vector,
            session_id=session_id,
            fact_type=FACT_TYPE_STATIC,
            limit=5,
            max_distance=_EXTRACTOR_DEDUP_THRESHOLD,
            user_id=user_id,
        )

        if existing and len(existing) > 0:
            e = existing[0]
            if e.get("content") == text:
                meta = e.get("metadata") or {}
                ids = meta.get("source_episodic_ids", [])
                if episode_id and episode_id not in ids:
                    ids.append(episode_id)
                elif not ids:
                    ids = [episode_id] if episode_id else []
                meta["source_episodic_ids"] = ids
                meta["category"] = category
                await pg_execute_async(
                    "UPDATE semantic_facts SET last_accessed=%s, metadata=%s WHERE id=%s",
                    (datetime.now(), Json(meta), e["id"]),
                )
                return  # done — no insert needed

        existing_exact = await pg_fetchone_async(
            "SELECT id, metadata FROM semantic_facts WHERE fact_type=%s AND content=%s AND invalid_at IS NULL AND user_id=%s LIMIT 1",
            (FACT_TYPE_STATIC, text, user_id),
        )
        if existing_exact:
            meta = existing_exact.get("metadata") or {}
            ids = meta.get("source_episodic_ids", [])
            if episode_id and episode_id not in ids:
                ids.append(episode_id)
            elif not ids:
                ids = [episode_id] if episode_id else []
            meta["source_episodic_ids"] = ids
            meta["category"] = category
            await pg_execute_async(
                "UPDATE semantic_facts SET last_accessed=%s, metadata=%s WHERE id=%s",
                (datetime.now(), Json(meta), existing_exact["id"]),
            )
            return  # exact content dupe — reinforce, don't insert

    # No duplicate — insert new fact
    metadata = {
        "entity": entity,
        "relation": relation,
        "target": target,
        "confidence": 0.7,
        "importance": 0.7,
        "category": category,
        "source_table": "semantic_memories",
        "session_id": session_id,
    }
    if episode_id:
        metadata["source_episodic_ids"] = [episode_id]

    await MemoryDB.save_fact_async(
        session_id=session_id,
        content=f"{entity} {relation} {target}",
        embedding=vector,
        fact_type=FACT_TYPE_STATIC,
        metadata=metadata,
        category=category,
        user_id=user_id,
    )


def create_episodic_memory(
    session_id,
    summary,
    emotional_weight=0.0,
    importance=0.5,
    source_message_ids=None,
    user_id=None,
):
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
        logger.warning(f"Embedding failed: {e}")
        vector = None

    fact_id = MemoryDB.save_fact(
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
        user_id=user_id,
    )
    return fact_id


async def create_episodic_memory_async(
    session_id,
    summary,
    emotional_weight=0.0,
    importance=0.5,
    source_message_ids=None,
    user_id=None,
):
    """Async version of create_episodic_memory."""
    try:
        from app.memory.embedder import embed_text_async

        vector = await embed_text_async(summary)
    except Exception as e:
        logger.warning(f"Embedding async failed: {e}")
        vector = None

    fact_id = await MemoryDB.save_fact_async(
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
        user_id=user_id,
    )
    return fact_id
