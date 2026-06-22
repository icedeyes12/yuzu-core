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
    "review_memory_async",
    "mark_retrieved_as_pending_review_async",
]

from app.memory.db_memory_facade import MemoryDB
from app.db import pg_execute, pg_execute_async
from app.memory.memory import _memory_llm_call

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
    "hard": {"stability_mult": 0.9, "difficulty_delta": +0.05},
    "good": {"stability_mult": 1.2, "difficulty_delta": -0.05},
    "easy": {"stability_mult": 1.5, "difficulty_delta": -0.10},
}

_MIN_STABILITY = 0.1
_MIN_DIFFICULTY = 0.1
_MAX_DIFFICULTY = 4.0
_REVIEW_BATCH_SIZE = 20


async def _get_ai_manager_async():
    """Lazy-import to avoid circular imports. Async version only.

    NOTE: All callers must be async and await this function.
    """
    # WORKAROUND: Lazy import to prevent circular dependency with app.providers
    from app.providers import get_ai_manager

    return await get_ai_manager()


async def mark_retrieved_as_pending_review_async(
    fact_ids: list[int], session_id: str | None = None, user_id: str | None = None
) -> int:
    """Mark retrieved facts as pending review (async)."""
    if not fact_ids:
        return 0

    now = datetime.now()
    if len(fact_ids) == 1:
        fid = fact_ids[0]
        try:
            row = await MemoryDB.get_fact_by_id_async(fid, user_id=user_id)
            if not row:
                return 0
            meta = row.get("metadata") or {}
            meta["last_reviewed_at"] = now.isoformat()
            await pg_execute_async(
                "UPDATE semantic_facts SET pending_review=TRUE, metadata=%s, last_accessed=%s WHERE id=%s",
                (Json(meta), now, fid),
            )
            return 1
        except Exception as e:
            logger.warning(f"mark_pending async failed for id={fid}: {e}")
            return 0

    # Batch update
    ph = ",".join(["%s"] * len(fact_ids))
    try:
        await pg_execute_async(
            f"UPDATE semantic_facts SET pending_review=TRUE, last_accessed=%s WHERE id IN ({ph})",
            (now,) + tuple(fact_ids),
        )
        return len(fact_ids)
    except Exception as e:
        logger.warning(f"batch mark_pending async failed: {e}")
        return 0


async def _rate_facts_batch_async(
    facts: list[dict],
    conversation_context: str,
) -> dict[int, str]:
    """Rate multiple facts (async)."""
    if not facts:
        return {}

    import json
    import re

    # Build facts list for prompt
    facts_text = "\n".join(
        f"[{i + 1}] ID={f['id']}: {f['content'][:200]} (category: {f.get('category', 'unknown')})"
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
        # WORKAROUND: Lazy import to prevent circular dependency with app.providers
        from app.providers import get_ai_manager

        ai = await get_ai_manager()
        response = await _memory_llm_call(
            ai,
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
            match = re.search(r"\[.*\]", response, re.DOTALL)
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
        state_enum = (
            State(current_state) if current_state in (1, 2, 3) else State.Review
        )
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
        meta["last_review"] = (
            new_card.last_review.isoformat() if new_card.last_review else None
        )
        meta["last_rating"] = rating
        meta["pending_review"] = False

        pg_execute(
            "UPDATE semantic_facts SET metadata=%s, last_accessed=%s WHERE id=%s",
            (Json(meta), now, fact_id),
        )

        logger.info(
            f"FSRS review: fact={fact_id}, rating={rating}, S={current_stability:.1f}→{new_card.stability:.1f}, D={current_difficulty:.1f}→{new_card.difficulty:.1f}"
        )
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


def _update_fsrs_params(fact_id: int, rating: str, user_id: str | None = None) -> bool:
    """Apply FSRS parameter update based on rating.

    Uses fsrs library if available, falls back to multipliers otherwise.

    NOTE: FSRS only applies to episodic facts (source_table='episodic_memories').
    Semantic facts use temporal validity instead and should NOT have FSRS updates.
    """
    try:
        row = MemoryDB.get_fact_by_id(fact_id, user_id=user_id)
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


async def _update_fsrs_params_async(fact_id: int, rating: str, user_id: str | None = None) -> bool:
    """Apply FSRS parameter update (async)."""
    try:
        row = await MemoryDB.get_fact_by_id_async(fact_id, user_id=user_id)
        if not row:
            return False

        meta = row.get("metadata") or {}
        now = datetime.now(timezone.utc)

        # FSRS scope check
        source_table = meta.get("source_table", "")
        fact_type = row.get("fact_type", "")
        if source_table != "episodic_memories" and fact_type != "dynamic":
            meta["pending_review"] = False
            await pg_execute_async(
                "UPDATE semantic_facts SET pending_review=FALSE, metadata=%s WHERE id=%s",
                (Json(meta), fact_id),
            )
            return True

        # For library call, still uses existing sync helpers for now but wrapped in to_thread if needed
        # Actually _update_fsrs_params_fsrs and _update_fsrs_params_fallback are fast math + 1 SQL update.
        # I'll just rewrite the update part.

        if FSRS_AVAILABLE:
            # Re-implementing logic with await pg_execute_async
            scheduler = _get_scheduler()
            if not scheduler:
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
            last_dt = None
            if last_reviewed:
                try:
                    last_dt = datetime.fromisoformat(
                        last_reviewed.replace("Z", "+00:00")
                    )
                except Exception:
                    pass

            # Map state int to State enum (handle invalid values)
            try:
                state_enum = (
                    State(current_state) if current_state in (1, 2, 3) else State.Review
                )
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
                meta["last_review"] = (
                    new_card.last_review.isoformat() if new_card.last_review else None
                )
                meta["last_rating"] = rating
                meta["pending_review"] = False

                await pg_execute_async(
                    "UPDATE semantic_facts SET metadata=%s, last_accessed=%s WHERE id=%s",
                    (Json(meta), now, fact_id),
                )
                return True
            except Exception as e:
                logger.warning(f"Scheduler.review_card() failed: {e}")
                return False
        else:
            # Fallback
            effects = _RATING_MULTIPLIERS.get(rating)
            if not effects:
                return False

            meta = row.get("metadata") or {}
            new_stability = max(
                meta.get("stability", 1.0) * effects["stability_mult"], _MIN_STABILITY
            )
            new_difficulty = max(
                min(
                    meta.get("difficulty", 1.0) + effects["difficulty_delta"],
                    _MAX_DIFFICULTY,
                ),
                _MIN_DIFFICULTY,
            )

            meta["stability"] = new_stability
            meta["difficulty"] = new_difficulty
            meta["last_reviewed_at"] = now.isoformat()
            meta["last_rating"] = rating
            meta["pending_review"] = False

            await pg_execute_async(
                "UPDATE semantic_facts SET metadata=%s, last_accessed=%s WHERE id=%s",
                (Json(meta), now, fact_id),
            )
            return True

    except Exception as e:
        logger.error(f"FSRS update failed for id={fact_id}: {e}")
        return False


def review_memory(
    fact_ids: list[int], conversation_context: str, session_id: str | None = None, user_id: str | None = None
) -> dict:
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

    # BATCH FETCH: Get all facts in a single query (N+1 fix)
    rows = MemoryDB.get_facts_by_ids(fact_ids, user_id=user_id)
    rows_by_id = {r["id"]: r for r in rows} if rows else {}

    facts_to_rate = []
    for fid in fact_ids:
        row = rows_by_id.get(fid)
        if not row:
            counts["failed"] += 1
            continue

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

        facts_to_rate.append(
            {
                "id": fid,
                "content": row.get("content", ""),
                "category": row.get("metadata", {}).get("category"),
            }
        )

    # Process in batches
    for i in range(0, len(facts_to_rate), _REVIEW_BATCH_SIZE):
        batch = facts_to_rate[i : i + _REVIEW_BATCH_SIZE]

        # Rate batch - use async version since review_memory is already sync
        # and we're in a sync context (this function is for sync compatibility)
        import asyncio

        try:
            ratings = asyncio.run(_rate_facts_batch_async(batch, conversation_context))
        except RuntimeError:
            # Already in async context - this shouldn't happen in sync path
            # but handle gracefully
            logger.error("sync review_memory called from async context")
            ratings = {}

        # Update FSRS params for each fact
        for fact in batch:
            fid = fact["id"]
            rating = ratings.get(fid)

            if rating is None:
                counts["failed"] += 1
                continue

            if _update_fsrs_params(fid, rating, user_id=user_id):
                counts[rating] = counts.get(rating, 0) + 1
            else:
                counts["failed"] += 1

    logger.info(
        f"session={session_id} reviewed {len(facts_to_rate)} facts in {(len(facts_to_rate) + _REVIEW_BATCH_SIZE - 1) // _REVIEW_BATCH_SIZE} batches: {counts}"
    )
    return counts


async def review_memory_async(
    fact_ids: list[int], conversation_context: str, session_id: str | None = None, user_id: str | None = None
) -> dict:
    """Review memories (async)."""
    counts = {"again": 0, "hard": 0, "good": 0, "easy": 0, "failed": 0}

    if not fact_ids:
        return {"again": 0, "hard": 0, "good": 0, "easy": 0, "failed": 0}

    # BATCH FETCH: Get all facts in a single query (N+1 fix)
    rows = await MemoryDB.get_facts_by_ids_async(fact_ids, user_id=user_id)
    rows_by_id = {r["id"]: r for r in rows} if rows else {}

    facts_to_rate = []
    for fid in fact_ids:
        row = rows_by_id.get(fid)
        if not row:
            counts["failed"] += 1
            continue

        fact_type = row.get("fact_type", "")
        if fact_type == "static":
            meta = row.get("metadata", {}) or {}
            meta["pending_review"] = False
            await pg_execute_async(
                "UPDATE semantic_facts SET pending_review=FALSE, metadata=%s WHERE id=%s",
                (Json(meta), fid),
            )
            continue

        facts_to_rate.append(
            {
                "id": fid,
                "content": row.get("content", ""),
                "category": row.get("metadata", {}).get("category"),
            }
        )

    # Process in batches
    for i in range(0, len(facts_to_rate), _REVIEW_BATCH_SIZE):
        batch = facts_to_rate[i : i + _REVIEW_BATCH_SIZE]
        ratings = await _rate_facts_batch_async(batch, conversation_context)

        for fact in batch:
            fid = fact["id"]
            rating = ratings.get(fid)
            if rating is None:
                counts["failed"] += 1
                continue

            if await _update_fsrs_params_async(fid, rating, user_id=user_id):
                counts[rating] = counts.get(rating, 0) + 1
            else:
                counts["failed"] += 1

    return counts
