# Architecture: one asynchronous extraction pass per eligible message batch.
#
# Trigger gates: >=40 new messages, or >=20 after 3 hours idle.
# A completed chat turn is not itself a trigger; the backlog gates below are.
#
# Fence mechanism (aligned with plast-mem):
#   - in_progress_fence: prevents concurrent pipeline runs for same session
#   - fence_ttl_minutes: 120 minutes (stale job cleanup)

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta

from app.db import (
    get_message_count_async,
    get_pipeline_state_async,
    get_session_messages_after_id_async,
    get_session_messages_async,
    pg_execute_async,
    pg_fetchone_async,
    update_pipeline_state_async,
)
from app.db.queries import SQL_PIPELINE_STATE_LOCK, SQL_PIPELINE_STATE_UPDATE

__all__ = [
    "trigger_memory_pipeline_async",
    "enqueue_memory_pipeline_async",
    "run_memory_pipeline_async",
    "extract_memory_batch_async",
    "should_trigger_segmentation_async",
    "mark_segmentation_done_async",
    "_memory_llm_call",
]

logger = logging.getLogger(__name__)

# Batch trigger constants
WINDOW_BASE = 40
IDLE_WINDOW_BASE = 20
IDLE_GATE_HOURS = 3.0
BATCH_SIZE = 100
MAX_BATCHES_PER_WORKER = 5
MAX_WORKER_RUNTIME_SECONDS = 300.0

# Fence constants
FENCE_TTL_MINUTES = 120

# Historical backlog logging threshold
HISTORICAL_BACKLOG_THRESHOLD = 1000

# ── Rate limiting for memory pipeline ─────────────────────────────────────────
# Removed semaphore to avoid event-loop binding issues
# Rate limiting is handled by _last_memory_llm_call delay below
_MEMORY_LLM_DELAY = 3.0  # Seconds between memory LLM calls
_last_memory_llm_call = 0.0  # Timestamp of last call


async def _memory_llm_call(ai_manager, messages: list[dict], **kwargs) -> str | None:
    """Rate-limited LLM call for memory pipeline.

    Ensures memory calls don't overwhelm the API:
    - Min delay between calls
    - Explicit error logging for failures
    """
    global _last_memory_llm_call

    # Log context size before making the call
    total_chars = sum(
        len(m.get("content", "")) if isinstance(m.get("content"), str) else 0
        for m in messages
    )
    logger.debug(f"[MEMORY_LLM] Sending {total_chars} chars to LLM...")

    # Enforce minimum delay between calls
    now = time.time()
    elapsed = now - _last_memory_llm_call
    if elapsed < _MEMORY_LLM_DELAY:
        await asyncio.sleep(_MEMORY_LLM_DELAY - elapsed)

    try:
        result = await ai_manager._internal_llm_call(
            messages, source="memory_pipeline", **kwargs
        )
        _last_memory_llm_call = time.time()
        if result:
            logger.debug(f"[MEMORY_LLM] Response received: {len(result)} chars")
        else:
            # Explicit log when LLM returns None without throwing
            logger.warning(
                "[MEMORY_LLM] LLM returned None - possible context overflow, "
                "rate limit, or empty response"
            )
        return result
    except TimeoutError as e:
        logger.warning(f"[MEMORY_LLM] Timeout after {kwargs.get('timeout', 30)}s: {e}")
        return None
    except Exception as e:
        error_type = type(e).__name__
        logger.info("[MEMORY_LLM] skipped (%s)", error_type)
        return None


# ── Background state ─────────────────────────────────────────────────────────

_pending_sessions: asyncio.Queue[tuple[str, str | None]] = asyncio.Queue()
_queued_sessions: set[tuple[str, str]] = set()
_worker_task: asyncio.Task | None = None


async def _get_cached_pipeline_state_async(
    session_id: str, user_id: str | None
) -> dict:
    """(｡•̀ᴗ-)✧"""
    if not user_id:
        return {}
    return await get_pipeline_state_async(session_id, user_id)


async def _try_set_fence_async(
    session_id: str, fence_count: int, user_id: str | None = None
) -> bool:
    """Atomically set a fence for a user-owned session."""
    if not user_id:
        return False
    now = datetime.now()
    state = await pg_fetchone_async(SQL_PIPELINE_STATE_LOCK, (session_id, user_id))
    if not state:
        return False
    ms = state.get("memory_pipeline_state") or {}
    existing_count = ms.get("in_progress_fence_count")
    existing_since = ms.get("in_progress_fence_since")
    if existing_count is not None and existing_since is not None:
        try:
            existing_dt = datetime.fromisoformat(existing_since)
            age = now - existing_dt
            if age <= timedelta(minutes=FENCE_TTL_MINUTES):
                return False
        except (ValueError, TypeError):
            logger.warning("Invalid fence timestamp for session %s", session_id)
    ms["in_progress_fence_count"] = fence_count
    ms["in_progress_fence_since"] = now.isoformat()
    await pg_execute_async(
        SQL_PIPELINE_STATE_UPDATE,
        (json.dumps(ms), datetime.now(), session_id, user_id),
    )
    return True


async def _clear_fence_async(session_id: str, user_id: str | None = None) -> None:
    """Clear a fence only on the owning session."""
    if not user_id:
        return
    state = await pg_fetchone_async(SQL_PIPELINE_STATE_LOCK, (session_id, user_id))
    if not state:
        return
    ms = state.get("memory_pipeline_state") or {}
    ms["in_progress_fence_count"] = None
    ms["in_progress_fence_since"] = None
    await pg_execute_async(
        SQL_PIPELINE_STATE_UPDATE,
        (json.dumps(ms), datetime.now(), session_id, user_id),
    )


async def _is_fence_active_async(session_id: str, user_id: str | None = None) -> bool:
    """Check a fence only on the owning session."""
    state = await _get_cached_pipeline_state_async(session_id, user_id=user_id)
    existing_count = state.get("in_progress_fence_count")
    existing_since = state.get("in_progress_fence_since")
    if existing_count is None or existing_since is None:
        return False
    try:
        existing_dt = datetime.fromisoformat(existing_since)
        return datetime.now() - existing_dt <= timedelta(minutes=FENCE_TTL_MINUTES)
    except (ValueError, TypeError):
        return False


async def _get_session_idle_hours_async(
    session_id: str, user_id: str | None = None
) -> float | None:
    """Get idle hours (async)."""
    if not user_id:
        return None
    messages = await get_session_messages_async(
        session_id, limit=1, order="DESC", user_id=user_id
    )
    if not messages:
        return None
    last_ts = messages[0].get("timestamp")
    if not last_ts:
        return None
    try:
        last_dt = datetime.fromisoformat(
            last_ts.replace("Z", "+00:00").replace("+00:00", "")
        )
        return (datetime.now() - last_dt).total_seconds() / 3600.0
    except Exception:
        return None


async def _has_eligible_backlog_async(
    session_id: str, remaining_count: int, user_id: str
) -> bool:
    if remaining_count >= WINDOW_BASE:
        return True
    if remaining_count < IDLE_WINDOW_BASE:
        return False
    idle_hours = await _get_session_idle_hours_async(session_id, user_id=user_id)
    return idle_hours is not None and idle_hours >= IDLE_GATE_HOURS


async def should_trigger_segmentation_async(
    session_id: str, current_count: int, user_id: str | None = None
) -> tuple[bool, int]:
    """Check if segmentation should trigger (async).

    Uses message ID-based tracking to avoid count-vs-index dual-semantics.

    Args:
        session_id: Session ID to check
        current_count: Current message count (used for fallback and logging)

    Returns:
        (should_trigger: bool, delta: int) - whether to trigger pipeline
            and the delta (new messages since last_segmented_message_id)

    Safety checks:
        - Blocks if fence is active
        - Detects historical backlogs (>1000 messages) and logs warning
    """
    if await _is_fence_active_async(session_id, user_id=user_id):
        return False, 0

    state = await _get_cached_pipeline_state_async(session_id, user_id=user_id)

    last_message_id = state.get("last_segmented_message_id")
    try:
        messages_after = await get_session_messages_after_id_async(
            session_id,
            last_message_id or "00000000-00000000-0000-000000000000",
            limit=10000,
            user_id=user_id or "",
        )
        delta = sum(
            1
            for message in messages_after
            if message.get("role") in ("user", "assistant")
        )
    except Exception as exc:
        logger.warning("Cursor delta query failed; using count fallback: %s", exc)
        last_count = state.get("last_segmented_count", 0) or 0
        delta = max(0, current_count - last_count)

    # Historical backlog detection (safety net)
    if delta > HISTORICAL_BACKLOG_THRESHOLD:
        logger.warning(
            f"⚠️ HISTORICAL BACKLOG DETECTED: session={session_id} "
            f"delta={delta} > threshold={HISTORICAL_BACKLOG_THRESHOLD} "
            f"— worker will process bounded batches"
        )

    if delta >= WINDOW_BASE:
        return True, delta

    if delta < IDLE_WINDOW_BASE:
        return False, delta

    idle_hours = await _get_session_idle_hours_async(session_id, user_id=user_id)
    return idle_hours is not None and idle_hours >= IDLE_GATE_HOURS, delta


async def mark_segmentation_done_async(
    session_id: str,
    last_message_id: str | None = None,
    processed_count: int = 0,
    *,
    user_id: str,
) -> None:
    """Mark segmentation done (async).

    Stores both message ID (preferred) and count (fallback) for tracking.

    Args:
        session_id: Session ID to update
        last_message_id: ID of the last processed message (preferred)
        processed_count: Number of messages processed in this run
    """
    actual_total = await get_message_count_async(session_id, user_id=user_id)

    state_update = {
        "last_segmented_count": actual_total,  # Keep for compatibility
        "last_segmented_at": datetime.now().isoformat(),
    }

    # Store message ID if available
    if last_message_id:
        state_update["last_segmented_message_id"] = last_message_id

    await update_pipeline_state_async(session_id, state_update, user_id=user_id)


# ── Single-pass extraction ────────────────────────────────────────────────────


async def extract_memory_batch_async(
    messages: list[dict], profile: dict | None = None
) -> dict:
    """Extract episodes and claims with one structured LLM call."""
    from app.memory.extractor import extract_batch_async

    return await extract_batch_async(messages, profile=profile)


# ── Main pipeline runner ───────────────────────────────────────────────────────


async def run_memory_pipeline_async(
    session_id: str, message_count: int, user_id: str
) -> dict:
    """Run the full memory pipeline for a session.

    Steps:
      1. Get unsegmented messages after last_segmented_message_id
      2. Extract episodes and claims in one LLM call
      3. Persist episodes, claims, and provenance
      4. Clear fence and mark done with message ID

    Returns summary: {episodes: n, claims: n, llm_calls: n}
    """
    logger.info(f"Starting for session {session_id}, count={message_count}")
    from app.db import Database

    profile = await Database.get_profile(user_id)

    # Get current state for tracking
    state = await get_pipeline_state_async(session_id, user_id)
    last_message_id = state.get("last_segmented_message_id")
    last_count = state.get("last_segmented_count", 0) or 0

    try:
        # ID-based query: fetch messages AFTER the last processed message ID
        if last_message_id:
            try:
                from app.db import get_session_messages_after_id_async

                all_messages = await get_session_messages_after_id_async(
                    session_id, last_message_id, limit=10000, user_id=user_id
                )
                unsegmented = [
                    m for m in all_messages if m.get("role") in ("user", "assistant")
                ]
            except Exception as e:
                logger.warning(
                    f"ID-based query failed, falling back to count-based: {e}"
                )
                # Fallback
                all_messages = await get_session_messages_async(
                    session_id, limit=10000, user_id=user_id
                )
                conversation_messages = [
                    m for m in all_messages if m.get("role") in ("user", "assistant")
                ]
                unsegmented = conversation_messages[last_count:]
        else:
            # Initial state: use count-based
            all_messages = await get_session_messages_async(
                session_id, limit=10000, user_id=user_id
            )
            conversation_messages = [
                m for m in all_messages if m.get("role") in ("user", "assistant")
            ]
            unsegmented = conversation_messages[last_count:]

        # Filter to conversation messages only. The ID path is already scoped
        # to the cursor; never reapply the old global count as an offset.
        if not isinstance(unsegmented, list):
            unsegmented = [
                m for m in all_messages if m.get("role") in ("user", "assistant")
            ]

        if not unsegmented:
            return {"episodes": 0, "claims": 0, "llm_calls": 0}

        unsegmented_count = len(unsegmented)

        original_unsegmented_count = unsegmented_count
        if unsegmented_count > BATCH_SIZE:
            logger.info(
                "Session %s has %s messages; processing one worker batch of %s",
                session_id,
                unsegmented_count,
                BATCH_SIZE,
            )
            unsegmented = unsegmented[:BATCH_SIZE]
            unsegmented_count = BATCH_SIZE

        # Track how many we're actually processing
        processed_count = unsegmented_count
        # ───────────────────────────────────────────────────────────────────────

        if unsegmented_count < IDLE_WINDOW_BASE:
            logger.debug("Only %s unsegmented messages; skipping", unsegmented_count)
            return {
                "episodes": 0,
                "claims": 0,
                "llm_calls": 0,
                "processed_messages": 0,
            }

        extracted = await extract_memory_batch_async(unsegmented, profile=profile)
        if not extracted["episodes"] and not extracted["claims"]:
            logger.debug("No durable memory extracted")
            if unsegmented:
                last_msg = unsegmented[-1]
                await mark_segmentation_done_async(
                    session_id, last_msg.get("id", 0), processed_count, user_id=user_id
                )
            return {"episodes": 0, "claims": 0, "llm_calls": 1}

        episode_count = 0
        claim_count = 0
        from app.memory.embedder import embed_text_async
        from app.memory.graph import GraphMemoryRepository

        episode_ids: list[str] = []
        for episode in extracted["episodes"]:
            segment_messages = unsegmented[
                episode["start_index"] : episode["end_index"]
            ]
            source_ids = [str(message.get("id")) for message in segment_messages]
            embedding = await embed_text_async(episode["summary"])
            episode_row = await GraphMemoryRepository.create_episode(
                user_id=user_id,
                session_id=session_id,
                title=episode["title"],
                summary=episode["summary"],
                embedding=embedding,
                importance=episode["importance"],
                source_start_message_id=source_ids[0] if source_ids else None,
                source_end_message_id=source_ids[-1] if source_ids else None,
            )
            episode_id = str(episode_row["id"]) if episode_row else None
            if episode_id:
                episode_ids.append(episode_id)
                episode_count += 1

        for claim in extracted["claims"]:
            episode_id = next(
                (
                    episode_ids[index]
                    for index, episode in enumerate(extracted["episodes"])
                    if episode["start_index"]
                    <= claim["evidence_start_index"]
                    < episode["end_index"]
                    and index < len(episode_ids)
                ),
                None,
            )
            metadata = {
                "confidence": claim["confidence"],
                "evidence_message_ids": [
                    str(unsegmented[index].get("id"))
                    for index in range(
                        claim["evidence_start_index"],
                        min(claim["evidence_end_index"], len(unsegmented)),
                    )
                ],
            }
            if episode_id is not None:
                metadata["source_episodic_ids"] = [episode_id]
            node_content = f"{claim['entity']} {claim['relation']} {claim['target']}"
            node_row = await GraphMemoryRepository.get_or_create_node(
                user_id=user_id,
                node_type="fact",
                content=node_content,
                embedding=await embed_text_async(node_content),
                confidence=claim["confidence"],
                importance=0.7,
                embedding_model="gemini-embedding-2-preview",
                embedding_dimensions=1536,
            )
            if node_row:
                node_id = str(node_row["id"])
                if episode_id:
                    await GraphMemoryRepository.add_evidence(
                        user_id=user_id,
                        node_id=node_id,
                        episode_id=episode_id,
                        message_ids=metadata["evidence_message_ids"],
                    )
                claim_count += 1

                related_claims = [
                    other
                    for other in extracted["claims"]
                    if other is not claim
                    and other["evidence_start_index"] == claim["evidence_start_index"]
                ]
                for related_claim in related_claims:
                    related_content = (
                        f"{related_claim['entity']} {related_claim['relation']} "
                        f"{related_claim['target']}"
                    )
                    related_node = await GraphMemoryRepository.get_or_create_node(
                        user_id=user_id,
                        node_type="fact",
                        content=related_content,
                        embedding=None,
                        confidence=related_claim["confidence"],
                        importance=0.7,
                        embedding_model=None,
                        embedding_dimensions=None,
                    )
                    if related_node and str(related_node["id"]) != node_id:
                        await GraphMemoryRepository.add_edge(
                            user_id=user_id,
                            from_node_id=node_id,
                            to_node_id=str(related_node["id"]),
                            edge_type="related_to",
                            confidence=min(
                                claim["confidence"], related_claim["confidence"]
                            ),
                        )

        logger.info(
            "Single-pass memory extraction: episodes=%s claims=%s",
            episode_count,
            claim_count,
        )

        # Mark done with the last processed message ID
        last_processed_msg = unsegmented[-1] if unsegmented else None
        last_processed_id = (
            str(last_processed_msg.get("id")) if last_processed_msg else None
        )

        await mark_segmentation_done_async(
            session_id, last_processed_id, processed_count, user_id=user_id
        )

        # Log if there are remaining messages to process
        remaining = original_unsegmented_count - processed_count
        if remaining > 0:
            logger.info(
                f"Session {session_id}: processed {processed_count}/{original_unsegmented_count} "
                f"messages, {remaining} remaining for next run"
            )

        return {
            "episodes": episode_count,
            "claims": claim_count,
            "llm_calls": 1,
            "processed_messages": processed_count,
        }
    finally:
        # Always clear fence when done (even on error)
        # This mirrors plast-mem's finalize_job() behavior
        await _clear_fence_async(session_id, user_id=user_id)
        logger.debug(f"Fence cleared for session {session_id}")


# ── Background thread launcher ─────────────────────────────────────────────────


async def _background_worker_async():
    """Async background worker."""
    while True:
        session_to_process, user_id = await _pending_sessions.get()
        if not session_to_process or not user_id:
            _pending_sessions.task_done()
            continue
        try:
            # Retrieve count from DB-persisted fence
            started = time.monotonic()
            for batch_number in range(MAX_BATCHES_PER_WORKER):
                count = await get_message_count_async(
                    session_to_process, user_id=user_id
                )
                result = await run_memory_pipeline_async(
                    session_to_process, count, user_id=user_id
                )
                if (
                    result.get("processed_messages", 0) < BATCH_SIZE
                    or time.monotonic() - started >= MAX_WORKER_RUNTIME_SECONDS
                ):
                    break
                state = await get_pipeline_state_async(session_to_process, user_id)
                last_message_id = state.get("last_segmented_message_id")
                remaining = await get_session_messages_after_id_async(
                    session_to_process,
                    last_message_id or "00000000-00000000-0000-000000000000",
                    limit=BATCH_SIZE + 1,
                    user_id=user_id,
                )
                remaining_count = sum(
                    1
                    for message in remaining
                    if message.get("role") in ("user", "assistant")
                )
                if not await _has_eligible_backlog_async(
                    session_to_process, remaining_count, user_id
                ):
                    break
        except Exception as e:
            logger.error(f"Background worker error: {e}")
        finally:
            _queued_sessions.discard((session_to_process, user_id))
            _pending_sessions.task_done()


async def enqueue_memory_pipeline_async(session_id: str, user_id: str) -> bool:
    """Enqueue a session for background memory pipeline processing.

    Non-blocking — returns immediately.
    """
    global _worker_task

    queue_key = (session_id, user_id)
    if queue_key in _queued_sessions:
        return False

    _queued_sessions.add(queue_key)
    try:
        if _worker_task is None or _worker_task.done():
            _worker_task = asyncio.create_task(_background_worker_async())
        await _pending_sessions.put((session_id, user_id))
    except Exception:
        _queued_sessions.discard(queue_key)
        raise
    return True


async def trigger_memory_pipeline_async(
    session_id: str, current_count: int, user_id: str
) -> bool:
    """Check and trigger memory pipeline in background if threshold met.

    Returns True if pipeline was triggered.
    """
    should_trigger, delta = await should_trigger_segmentation_async(
        session_id, current_count, user_id=user_id
    )

    if not should_trigger:
        return False

    # Try to set fence with current_count (total messages at trigger time)
    if not await _try_set_fence_async(session_id, current_count, user_id=user_id):
        logger.debug("Could not set fence for session %s", session_id)
        return False

    queued = await enqueue_memory_pipeline_async(session_id, user_id)
    if not queued:
        await _clear_fence_async(session_id, user_id=user_id)
        return False
    return True
