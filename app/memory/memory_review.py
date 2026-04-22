# FILE: app/memory/memory_review.py
# DESCRIPTION: LLM-based memory review system — ratings drive FSRS parameter updates.
#              Aligns with plast-mem's MemoryReviewJob.
#
# Flow:
#   1. retrieve_memory() marks retrieved facts as pending_review in metadata
#   2. review_memory() is called with conversation context
#   3. LLM rates each fact: Again/Hard/Good/Easy
#   4. FSRS parameters (stability, difficulty) updated based on rating

from __future__ import annotations

import logging

__all__ = [
    "review_memory",
    "mark_retrieved_as_pending_review",
]

from datetime import datetime
from psycopg.types.json import Json
from app.memory.db_memory import (
    get_fact_by_id,
    pg_execute,
)

logger = logging.getLogger(__name__)


# ── Rating → FSRS parameter mappings ─────────────────────────────────────────
# Based on FSRS (Free Spaced Repetition Scheduler) principles.
# Maps Again/Hard/Good/Easy ratings to multiplicative stability changes.
#
# Roadmap specifies:
#   Again → stability × 0.5
#   Hard  → stability × 0.9
#   Good  → stability × 1.2
#   Easy  → stability × 1.5
#
# Difficulty moves inversely (harder memories = more difficult to retain).

_RATING_MULTIPLIERS = {
    "again": {"stability_mult": 0.5,  "difficulty_delta": +0.15},  # very unstable, harder to relearn
    "hard":  {"stability_mult": 0.9,  "difficulty_delta": +0.05},  # slightly unstable
    "good":  {"stability_mult": 1.2,  "difficulty_delta": -0.05},  # stable
    "easy":  {"stability_mult": 1.5,  "difficulty_delta": -0.10},  # very stable
}

# Minimum values to prevent instability
_MIN_STABILITY   = 0.1
_MIN_DIFFICULTY  = 0.1
_MAX_DIFFICULTY  = 4.0

# Batch processing
_REVIEW_BATCH_SIZE = 20  # facts per LLM call


def _get_ai_manager():
    """Lazy-import to avoid circular imports."""
    from app import get_ai_manager
    return get_ai_manager()


def mark_retrieved_as_pending_review(fact_ids: list[int], session_id: int | None = None) -> int:
    """Mark retrieved facts as pending review.

    Uses native `pending_review` BOOLEAN column (not JSONB metadata).
    Also updates `last_reviewed_at` in metadata.
    Returns number of facts marked.
    """
    if not fact_ids:
        return 0

    now = datetime.now()
    if len(fact_ids) == 1:
        fid = fact_ids[0]
        try:
            row = get_fact_by_id(fid)
            if not row:
                return 0
            meta = row.get("metadata") or {}
            meta["last_reviewed_at"] = now.isoformat()
            pg_execute(
                "UPDATE semantic_facts SET pending_review=TRUE, metadata=%s, last_accessed=%s WHERE id=%s",
                (Json(meta), now, fid),
            )
            return 1
        except Exception as e:
            logger.warning(f"mark_pending failed for id={fid}: {e}")
            return 0

    # Batch update for multiple ids
    ph = ",".join(["%s"] * len(fact_ids))
    try:
        # meta_batch kept for future batch metadata update
        pass  # meta_batch = {fid: {"last_reviewed_at": now.isoformat()} for fid in fact_ids}
        # Use batch update: set pending_review=TRUE, last_accessed=now
        pg_execute(
            f"UPDATE semantic_facts SET pending_review=TRUE, last_accessed=%s WHERE id IN ({ph})",
            (now,) + tuple(fact_ids),
        )
        return len(fact_ids)
    except Exception as e:
        logger.warning(f"batch mark_pending failed: {e}")
        return 0


def _rate_facts_batch(
    facts: list[dict],
    conversation_context: str,
) -> dict[int, str]:
    """Rate multiple facts in a single LLM call.

    Args:
        facts: list of {id, content, category} dicts
        conversation_context: recent conversation text

    Returns:
        dict mapping fact_id -> rating ("again"/"hard"/"good"/"easy")
    """
    if not facts:
        return {}

    # Build facts list for prompt
    facts_text = "\n".join(
        f"[{i+1}] ID={f['id']}: {f['content'][:200]} (category: {f.get('category', 'unknown')})"
        for i, f in enumerate(facts)
    )

    system_prompt = """You are a memory relevance reviewer. Rate each memory's relevance to the conversation.

Ratings:
- **again**: NOT used — noise, irrelevant, incorrect
- **hard**: Tangentially related — weak connection
- **good**: Directly relevant — influenced conversation helpfully
- **easy**: CORE PILLAR — essential to conversation

Respond with ONLY a JSON array of objects:
[{"id": 123, "rating": "good"}, {"id": 124, "rating": "again"}, ...]

Rate ALL facts. Use exactly: "again", "hard", "good", or "easy"."""

    user_prompt = f"""Conversation context:
{conversation_context[:1000]}

Facts to rate:
{facts_text}

Rate each fact (respond with JSON array only):"""

    try:
        import json
        ai = _get_ai_manager()
        response = ai._internal_llm_call(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=30,
            max_tokens=500,
        )
        if not response:
            return {}

        # Parse JSON response
        try:
            ratings = json.loads(response.strip())
        except json.JSONDecodeError:
            # Try to extract JSON from response
            import re
            match = re.search(r'\[.*\]', response, re.DOTALL)
            if match:
                ratings = json.loads(match.group(0))
            else:
                logger.warning(f"Could not parse batch ratings: {response[:100]}")
                return {}

        # Build result dict
        result = {}
        for item in ratings:
            if isinstance(item, dict) and "id" in item and "rating" in item:
                rating = item["rating"].lower().strip()
                if rating in _RATING_MULTIPLIERS:
                    result[item["id"]] = rating

        return result

    except Exception as e:
        logger.warning(f"Batch rating failed: {e}")
        return {}


def _rate_fact(fact_content: str, fact_category: str | None, conversation_context: str) -> str | None:
    """Ask LLM to rate a retrieved memory in context.

    Returns: "again" | "hard" | "good" | "easy" | None
    """
    system_prompt = """You are a memory relevance reviewer.

Given a retrieved memory and the current conversation, rate how relevant this memory was to the ongoing discussion.

Categories: identity, preference, interest, personality, relationship, experience, goal, guideline

Rate the memory's relevance to THIS conversation:

- **again**: The memory was NOT used at all — it was noise, irrelevant, or incorrect. The assistant should NOT have relied on it.
- **hard**: The memory was tangentially related — required significant inference to connect, and the connection was weak.
- **good**: The memory was directly relevant and visibly influenced the conversation in a helpful way.
- **easy**: The memory was a CORE PILLAR — essential to the conversation's flow, topic, or emotional tone. It directly shaped the response.

Respond with ONLY the rating word: again, hard, good, or easy. Nothing else."""

    user_prompt = f"""Memory: {fact_content}
Category: {fact_category or 'unknown'}
Conversation context:
{conversation_context}

Rate: again, hard, good, or easy (respond with ONLY the word)."""

    try:
        ai = _get_ai_manager()
        response = ai._internal_llm_call(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=15,
            max_tokens=20,
        )
        if not response:
            return None
        rating = response.strip().lower()
        if rating in _RATING_MULTIPLIERS:
            return rating
        # Handle common mistakes
        if "again" in rating or "fail" in rating:
            return "again"
        if "hard" in rating:
            return "hard"
        if "good" in rating or "relevant" in rating:
            return "good"
        if "easy" in rating or "core" in rating or "pillar" in rating:
            return "easy"
        logger.warning(f"Unrecognized rating: {rating!r}")
        return None
    except Exception as e:
        logger.warning(f"LLM rating failed: {e}")
        return None


def _update_fsrs_params(fact_id: int, rating: str) -> bool:
    """Apply FSRS parameter update based on rating.

    Updates metadata with new stability and difficulty values.
    
    NOTE: FSRS only applies to episodic facts (source_table='episodic_memories').
    Semantic facts use temporal validity instead and should NOT have FSRS updates.
    """
    effects = _RATING_MULTIPLIERS.get(rating)
    if not effects:
        return False

    try:
        row = get_fact_by_id(fact_id)
        if not row:
            return False

        meta = row.get("metadata") or {}
        
        # FSRS scope check: only episodic facts get FSRS updates
        source_table = meta.get("source_table", "")
        fact_type = row.get("fact_type", "")
        if source_table != "episodic_memories" and fact_type != "dynamic":
            # Semantic/static facts don't use FSRS — skip update
            logger.debug(f"Skipping FSRS update for non-episodic fact id={fact_id} (source={source_table})")
            return False
        
        now = datetime.now()

        # Current values or defaults
        current_stability = meta.get("stability", 1.0)
        current_difficulty = meta.get("difficulty", 1.0)

        # Apply deltas
        new_stability = max(current_stability * effects["stability_mult"], _MIN_STABILITY)
        new_difficulty = max(
            min(current_difficulty + effects["difficulty_delta"], _MAX_DIFFICULTY),
            _MIN_DIFFICULTY,
        )

        meta["stability"] = new_stability
        meta["difficulty"] = new_difficulty
        meta["last_reviewed_at"] = now.isoformat()
        meta["last_rating"] = rating
        meta["pending_review"] = False  # clear pending flag

        pg_execute(
            "UPDATE semantic_facts SET metadata=%s, last_accessed=%s WHERE id=%s",
            (Json(meta), now, fact_id),
        )
        return True
    except Exception as e:
        logger.error(f"FSRS update failed for id={fact_id}: {e}")
        return False


def review_memory(fact_ids: list[int], conversation_context: str, session_id: int | None = None) -> dict:
    """Review a list of retrieved memories against the conversation context.

    Uses batch processing for efficiency: processes up to 20 facts per LLM call.

    Args:
        fact_ids: list of fact IDs returned from retrieve_memory
        conversation_context: recent conversation text for LLM to judge against
        session_id: optional session for logging

    Returns:
        dict: {again: int, hard: int, good: int, easy: int, failed: int}
    """
    counts = {"again": 0, "hard": 0, "good": 0, "easy": 0, "failed": 0}

    if not fact_ids:
        return counts

    # Fetch all facts first
    facts_to_rate = []
    for fid in fact_ids:
        try:
            row = get_fact_by_id(fid)
            if row:
                # FSRS review only applies to episodic facts (dynamic)
                # Skip semantic facts - they use temporal validity instead
                fact_type = row.get("fact_type", "")
                if fact_type == "static":
                    # Clear pending_review for semantic facts, they don't need FSRS review
                    meta = row.get("metadata", {}) or {}
                    meta["pending_review"] = False
                    pg_execute(
                        "UPDATE semantic_facts SET pending_review=FALSE, metadata=%s WHERE id=%s",
                        (Json(meta), fid),
                    )
                    continue
                
                facts_to_rate.append({
                    "id": fid,
                    "content": row.get("content", ""),
                    "category": row.get("metadata", {}).get("category"),
                })
        except Exception as e:
            logger.warning(f"Could not fetch fact {fid}: {e}")
            counts["failed"] += 1

    # Process in batches
    for i in range(0, len(facts_to_rate), _REVIEW_BATCH_SIZE):
        batch = facts_to_rate[i:i + _REVIEW_BATCH_SIZE]
        
        # Rate batch
        ratings = _rate_facts_batch(batch, conversation_context)
        
        # Update FSRS params for each fact
        for fact in batch:
            fid = fact["id"]
            rating = ratings.get(fid)
            
            if rating is None:
                # Fallback to single-fact rating if batch didn't return this one
                rating = _rate_fact(fact["content"], fact.get("category"), conversation_context)
            
            if rating is None:
                counts["failed"] += 1
                continue
            
            if _update_fsrs_params(fid, rating):
                counts[rating] = counts.get(rating, 0) + 1
            else:
                counts["failed"] += 1

    logger.info(f"session={session_id} reviewed {len(facts_to_rate)} facts in {(len(facts_to_rate) + _REVIEW_BATCH_SIZE - 1) // _REVIEW_BATCH_SIZE} batches: {counts}")
    return counts
