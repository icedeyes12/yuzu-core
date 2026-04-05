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

__all__ = [
    "review_memory",
    "mark_retrieved_as_pending_review",
    "get_pending_review_count",
]

from datetime import datetime
from app.memory.db_memory import (
    get_fact_by_id,
    pg_execute,
    pg_fetchall,
)
from psycopg2.extras import Json


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


def _get_ai_manager():
    """Lazy-import to avoid circular imports."""
    from app import get_ai_manager
    return get_ai_manager()


def mark_retrieved_as_pending_review(fact_ids: list[int], session_id: int | None = None) -> int:
    """Mark retrieved facts as pending review.

    Adds `pending_review: True` and `last_reviewed_at` to metadata.
    Returns number of facts marked.
    """
    if not fact_ids:
        return 0

    marked = 0
    now = datetime.now()
    for fid in fact_ids:
        try:
            row = get_fact_by_id(fid)
            if not row:
                continue
            meta = row.get("metadata") or {}
            meta["pending_review"] = True
            meta["last_reviewed_at"] = now.isoformat()
            pg_execute(
                "UPDATE semantic_facts SET metadata=%s, last_accessed=%s WHERE id=%s",
                (Json(meta), now, fid),
            )
            marked += 1
        except Exception as e:
            print(f"[review] mark_pending failed for id={fid}: {e}")

    return marked


def get_pending_review_count(fact_type: str | None = None) -> int:
    """Return count of facts with pending_review=True."""
    conditions = ["(metadata->>'pending_review')::bool = true"]
    params: list = []
    if fact_type:
        conditions.append("fact_type = %s")
        params.append(fact_type)
    where = "WHERE " + " AND ".join(conditions)
    row = pg_fetchall(f"SELECT COUNT(*) AS cnt FROM semantic_facts {where}", params)
    return row[0]["cnt"] if row else 0


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
        print(f"[review] Unrecognized rating: {rating!r}")
        return None
    except Exception as e:
        print(f"[review] LLM rating failed: {e}")
        return None


def _update_fsrs_params(fact_id: int, rating: str) -> bool:
    """Apply FSRS parameter update based on rating.

    Updates metadata with new stability and difficulty values.
    """
    effects = _RATING_MULTIPLIERS.get(rating)
    if not effects:
        return False

    try:
        row = get_fact_by_id(fact_id)
        if not row:
            return False

        meta = row.get("metadata") or {}
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
        print(f"[review] FSRS update failed for id={fact_id}: {e}")
        return False


def review_memory(fact_ids: list[int], conversation_context: str, session_id: int | None = None) -> dict:
    """Review a list of retrieved memories against the conversation context.

    Each fact is rated by LLM (again/hard/good/easy) and FSRS parameters updated.

    Args:
        fact_ids: list of fact IDs returned from retrieve_memory
        conversation_context: recent conversation text for LLM to judge against
        session_id: optional session for logging

    Returns:
        dict: {again: int, hard: int, good: int, easy: int, failed: int}
    """
    counts = {"again": 0, "hard": 0, "good": 0, "easy": 0, "failed": 0}

    for fid in fact_ids:
        try:
            row = get_fact_by_id(fid)
            if not row:
                counts["failed"] += 1
                continue

            content = row.get("content", "")
            category = row.get("metadata", {}).get("category")
            rating = _rate_fact(content, category, conversation_context)

            if rating is None:
                counts["failed"] += 1
                continue

            _update_fsrs_params(fid, rating)
            counts[rating] += 1
            print(f"[review] id={fid} rated={rating}")
        except Exception as e:
            print(f"[review] review failed for id={fid}: {e}")
            counts["failed"] += 1

    print(f"[review] session={session_id} results: {counts}")
    return counts
