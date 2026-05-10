# FILE: app/memory/memory_review.py
# DESCRIPTION: LLM-based memory review system using fsrs library.
#              Ratings drive FSRS parameter updates via proper state transitions.
#
# Flow:
#   1. retrieve_memory() marks retrieved facts as pending_review in metadata
#   2. review_memory() is called with conversation context
#   3. LLM rates each fact: Again/Hard/Good/Easy
#   4. FSRS parameters (stability, difficulty) updated using fsrs library

from __future__ import annotations

import logging
from datetime import datetime, timezone
from psycopg.types.json import Json

__all__ = [
    "review_memory",
    "mark_retrieved_as_pending_review",
]

from app.memory.db_memory import (
    get_fact_by_id,
    pg_execute,
)

logger = logging.getLogger(__name__)

# ── FSRS Library Integration ───────────────
# PyPI fsrs library: https://pypi.org/project/fsrs/
# API: Scheduler.review_card(card, rating) -> (new_card, review_log)
try:
    from fsrs import Scheduler, Card, Rating, State
    FSRS_AVAILABLE = True
except ImportError:
    FSRS_AVAILABLE = False
    Scheduler = None
    Card = None
    Rating = None
    State = None
    logger.warning("fsrs library not available, falling back to multipliers")

# Initialize Scheduler instance (singleton)
_scheduler_instance = None


def _get_scheduler() -> Scheduler | None:
    """Get or create FSRS Scheduler instance."""
    global _scheduler_instance
    if _scheduler_instance is None and FSRS_AVAILABLE:
        _scheduler_instance = Scheduler()
    return _scheduler_instance


# ── Fallback multipliers (when fsrs not available) ─────────────────────────────
_RATING_MULTIPLIERS = {
    "again": {"stability_mult": 0.5, "difficulty_delta": +0.15},
    "hard":  {"stability_mult": 0.9, "difficulty_delta": +0.05},
    "good":  {"stability_mult": 1.2, "difficulty_delta": -0.05},
    "easy":  {"stability_mult": 1.5, "difficulty_delta": -0.10},
}

_MIN_STABILITY = 0.1
_MIN_DIFFICULTY = 0.1
_MAX_DIFFICULTY = 4.0
_REVIEW_BATCH_SIZE = 20


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

    import json
    import re

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
            match = re.search(r'\[.*\]', response, re.DOTALL)
            if match:
                ratings = json.loads(match.group(0))
            else:
                logger.warning(f"Could not parse batch ratings: {response[:100]}")
                return {}

        # Build result dict
        result = {}
        valid_ratings = {"again", "hard", "good", "easy"}
        for item in ratings:
            if isinstance(item, dict) and "id" in item and "rating" in item:
                rating = item["rating"].lower().strip()
                if rating in valid_ratings:
                    result[item["id"]] = rating

        return result

    except Exception as e:
        logger.warning(f"Batch rating failed: {e}")
        return {}


def _update_fsrs_params_fsrs(fact_id: int, rating: str, row: dict) -> bool:
    """Apply FSRS parameter update using the fsrs library.

    Uses scheduler.review_card(card, rating) to get next state.
    """
    scheduler = _get_scheduler()
    if scheduler is None or Card is None or Rating is None or State is None:
        return False

    meta = row.get("metadata") or {}

    # Current FSRS state from metadata
    current_stability = meta.get("stability", 1.0)
    current_difficulty = meta.get("difficulty", 1.0)
    last_reviewed = meta.get("last_reviewed_at")
    current_state = meta.get("state", 2)  # 2 = review state

    # === EDGE CASE PROTECTION ===
    # Ensure stability and difficulty have valid values
    if not current_stability or current_stability <= 0:
        current_stability = 1.0  # Minimum stable stability (1 day)
    if not current_difficulty or current_difficulty < 0:
        current_difficulty = 3.0  # Default medium difficulty

    # Calculate days since last review for logging
    now = datetime.now(timezone.utc)
    last_dt = None
    if last_reviewed:
        try:
            last_dt = datetime.fromisoformat(last_reviewed.replace("Z", "+00:00"))
        except Exception:
            pass

    # Map state int to State enum (handle invalid values)
    try:
        state_enum = State(current_state) if current_state in (1, 2, 3) else State.Review
    except ValueError:
        state_enum = State.Review

    # Calculate due date from stability
    from datetime import timedelta
    due = now + timedelta(days=current_stability)

    # Create Card with correct fsrs v6.3.1 API
    # Card only accepts: card_id, state, step, stability, difficulty, due, last_review
    card = Card(
        stability=current_stability,
        difficulty=current_difficulty,
        state=state_enum,
        due=due,
        last_review=last_dt,
    )

    # Map rating string to Rating enum
    rating_map = {
        "again": Rating.Again,
        "hard": Rating.Hard,
        "good": Rating.Good,
        "easy": Rating.Easy,
    }

    try:
        rating_enum = rating_map[rating]
        # Use scheduler.review_card() to get next state
        new_card, review_log = scheduler.review_card(card, rating_enum)

        # Extract new state from returned card (correct attributes)
        meta["stability"] = new_card.stability
        meta["difficulty"] = new_card.difficulty
        meta["state"] = new_card.state.value  # Store as int for JSON
        meta["due"] = new_card.due.isoformat() if new_card.due else None
        meta["last_review"] = new_card.last_review.isoformat() if new_card.last_review else None
        meta["last_rating"] = rating
        meta["pending_review"] = False

        pg_execute(
            "UPDATE semantic_facts SET metadata=%s, last_accessed=%s WHERE id=%s",
            (Json(meta), now, fact_id),
        )
        
        logger.info(f"FSRS review: fact={fact_id}, rating={rating}, S={current_stability:.1f}→{new_card.stability:.1f}, D={current_difficulty:.1f}→{new_card.difficulty:.1f}")
        return True

    except Exception as e:
        logger.warning(f"Scheduler.review_card() failed: {e}")
        return False


def _update_fsrs_params_fallback(fact_id: int, rating: str, row: dict) -> bool:
    """Apply FSRS parameter update using multiplicative multipliers.

    This is the fallback when fsrs library is not available.
    """
    effects = _RATING_MULTIPLIERS.get(rating)
    if not effects:
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
    meta["pending_review"] = False

    pg_execute(
        "UPDATE semantic_facts SET metadata=%s, last_accessed=%s WHERE id=%s",
        (Json(meta), now, fact_id),
    )
    return True


def _update_fsrs_params(fact_id: int, rating: str) -> bool:
    """Apply FSRS parameter update based on rating.

    Uses fsrs library if available, falls back to multipliers otherwise.

    NOTE: FSRS only applies to episodic facts (source_table='episodic_memories').
    Semantic facts use temporal validity instead and should NOT have FSRS updates.
    """
    try:
        row = get_fact_by_id(fact_id)
        if not row:
            return False

        meta = row.get("metadata") or {}

        # FSRS scope check: only episodic facts get FSRS updates
        source_table = meta.get("source_table", "")
        fact_type = row.get("fact_type", "")
        if source_table != "episodic_memories" and fact_type != "dynamic":
            # Semantic/static facts don't use FSRS — just clear pending
            meta["pending_review"] = False
            pg_execute(
                "UPDATE semantic_facts SET pending_review=FALSE, metadata=%s WHERE id=%s",
                (Json(meta), fact_id),
            )
            logger.debug(f"Skipping FSRS update for non-episodic fact id={fact_id}")
            return True

        # Try fsrs library first, fallback to multipliers
        if FSRS_AVAILABLE:
            return _update_fsrs_params_fsrs(fact_id, rating, row)
        else:
            return _update_fsrs_params_fallback(fact_id, rating, row)

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
                    # Clear pending_review for semantic facts
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
                counts["failed"] += 1
                continue

            if _update_fsrs_params(fid, rating):
                counts[rating] = counts.get(rating, 0) + 1
            else:
                counts["failed"] += 1

    logger.info(f"session={session_id} reviewed {len(facts_to_rate)} facts in {(len(facts_to_rate) + _REVIEW_BATCH_SIZE - 1) // _REVIEW_BATCH_SIZE} batches: {counts}")
    return counts
