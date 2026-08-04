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
import logging
import time
from datetime import datetime, timedelta
from typing import Any

from app.core.context import (
    RequestKeyring,
    clear_request_keyring,
    get_request_keyrings,
    set_request_keyrings,
)
from app.core.byok import YUZU_PORTAL, get_provider_key
from app.db import (
    Database,
    claim_pipeline_fence_async,
    clear_pipeline_fence_async,
    get_message_count_async,
    get_pipeline_state_async,
    get_session_messages_after_id_async,
    get_session_messages_async,
    update_pipeline_state_async,
)
from app.memory.embedder import embed_texts_async
from app.memory.extractor import build_adaptive_batches, estimate_message_tokens, extract_batch_async
from app.memory.graph import GraphMemoryRepository

__all__ = [
    "trigger_memory_pipeline_async",
    "enqueue_memory_pipeline_async",
    "run_memory_pipeline_async",
    "extract_memory_batch_async",
    "should_trigger_segmentation_async",
    "mark_segmentation_done_async",
]

logger = logging.getLogger(__name__)

# Batch trigger constants
WINDOW_BASE = 40
IDLE_WINDOW_BASE = 20
IDLE_GATE_HOURS = 3.0
BATCH_SIZE = 100
MESSAGE_FETCH_LIMIT = 512
EXTRACTION_TOKEN_BUDGET = 6000
MAX_EXTRACTION_RETRIES = 3
MAX_BATCHES_PER_WORKER = 5
MAX_WORKER_RUNTIME_SECONDS = 300.0

# Fence constants
FENCE_TTL_MINUTES = 120

# Historical backlog logging threshold
HISTORICAL_BACKLOG_THRESHOLD = 1000

# ── Background state ─────────────────────────────────────────────────────────

_pending_sessions: asyncio.Queue[tuple[str, str | None, dict[str, RequestKeyring]]] = (
    asyncio.Queue()
)
_queued_sessions: set[tuple[str, str]] = set()
_worker_task: asyncio.Task[None] | None = None


async def _get_cached_pipeline_state_async(
    session_id: str, user_id: str | None
) -> dict[str, Any]:
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
    stale_before = now - timedelta(minutes=FENCE_TTL_MINUTES)
    claimed = await claim_pipeline_fence_async(
        session_id,
        user_id,
        fence_count,
        now.isoformat(),
        stale_before.isoformat(),
    )
    return claimed is not None


async def _clear_fence_async(session_id: str, user_id: str | None = None) -> None:
    """Clear a fence only on the owning session."""
    if not user_id:
        return
    await clear_pipeline_fence_async(session_id, user_id)


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
    if isinstance(last_message_id, int):
        last_message_id = "00000000-0000-0000-0000-000000000000"

    try:
        messages_after = await get_session_messages_after_id_async(
            session_id,
            last_message_id or "00000000-0000-0000-0000-000000000000",
            limit=MESSAGE_FETCH_LIMIT,
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

    _ = await update_pipeline_state_async(session_id, state_update, user_id=user_id)


# ── Single-pass extraction ────────────────────────────────────────────────────


async def extract_memory_batch_async(
    messages: list[dict[str, Any]], profile: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Extract episodes and claims with one structured LLM call."""
    return await extract_batch_async(messages, profile=profile)


async def _extract_with_retries_async(
    messages: list[dict[str, Any]], profile: dict[str, Any] | None = None
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], int]:
    retry_batch = messages
    for retry_count in range(MAX_EXTRACTION_RETRIES):
        try:
            extracted = await extract_memory_batch_async(retry_batch, profile=profile)
            return extracted, retry_batch, retry_count + 1
        except Exception as exc:
            if retry_count + 1 >= MAX_EXTRACTION_RETRIES:
                logger.error(
                    "memory extraction skipped retries=%s tokens=%s error=%s",
                    retry_count + 1,
                    sum(estimate_message_tokens(m) for m in retry_batch),
                    type(exc).__name__,
                )
                return None, retry_batch, retry_count + 1
            midpoint = max(1, len(retry_batch) // 2)
            retry_batch = retry_batch[:midpoint]
            logger.warning(
                "memory extraction retry=%s reduced_messages=%s error=%s",
                retry_count + 1,
                len(retry_batch),
                type(exc).__name__,
            )
    return None, retry_batch, MAX_EXTRACTION_RETRIES


# ── Main pipeline runner ───────────────────────────────────────────────────────


async def run_memory_pipeline_async(
    session_id: str, message_count: int, user_id: str
) -> dict[str, Any]:
    """Run the full memory pipeline for a session.

    Steps:
      1. Get unsegmented messages after last_segmented_message_id
      2. Extract episodes and claims in one LLM call
      3. Persist episodes, claims, and provenance
      4. Clear fence and mark done with message ID

    Returns summary: {episodes: n, claims: n, llm_calls: n}
    """
    try:
        profile = await Database.get_profile(user_id)
        if not get_provider_key(YUZU_PORTAL):
            logger.info("memory disabled: missing Yuzu Portal API key")
            return {"episodes": 0, "claims": 0, "llm_calls": 0, "processed_messages": 0}

        logger.info("memory enabled via Yuzu Portal")
        logger.info("Starting for session %s, count=%s", session_id, message_count)

        # Get current state for tracking
        state = await get_pipeline_state_async(session_id, user_id)
        last_message_id = state.get("last_segmented_message_id")
        if isinstance(last_message_id, int):
            last_message_id = "00000000-0000-0000-0000-000000000000"
        last_count = state.get("last_segmented_count", 0) or 0

        # ID-based query: fetch messages AFTER the last processed message ID
        if last_message_id:
            try:
                all_messages = await get_session_messages_after_id_async(
                    session_id, last_message_id, limit=MESSAGE_FETCH_LIMIT, user_id=user_id
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
                    session_id, limit=MESSAGE_FETCH_LIMIT, user_id=user_id
                )
                conversation_messages = [
                    m for m in all_messages if m.get("role") in ("user", "assistant")
                ]
                unsegmented = conversation_messages[last_count:]
        else:
            # Initial state: use count-based
            all_messages = await get_session_messages_async(
                session_id, limit=MESSAGE_FETCH_LIMIT, user_id=user_id
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
        batches = build_adaptive_batches(
            unsegmented,
            token_budget=EXTRACTION_TOKEN_BUDGET,
            max_messages=BATCH_SIZE,
        )
        unsegmented = batches[0]
        unsegmented_count = len(unsegmented)
        estimated_tokens = sum(estimate_message_tokens(message) for message in unsegmented)
        logger.info(
            "memory batch session=%s messages=%s/%s tokens=%s range=%s..%s",
            session_id,
            unsegmented_count,
            original_unsegmented_count,
            estimated_tokens,
            unsegmented[0].get("id") if unsegmented else None,
            unsegmented[-1].get("id") if unsegmented else None,
        )

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

        started = time.monotonic()
        extracted, unsegmented, llm_calls = await _extract_with_retries_async(
            unsegmented, profile=profile
        )
        if extracted is None:
            logger.error(
                "memory extraction failed session=%s retries=%s elapsed_ms=%s checkpoint_preserved=true",
                session_id,
                llm_calls,
                int((time.monotonic() - started) * 1000),
            )
            return {"episodes": 0, "claims": 0, "llm_calls": llm_calls}
        processed_count = len(unsegmented)
        logger.info(
            "memory extraction session=%s retries=%s elapsed_ms=%s extracted=%s/%s processed_messages=%s",
            session_id,
            llm_calls,
            int((time.monotonic() - started) * 1000),
            len(extracted.get("episodes", [])),
            len(extracted.get("claims", [])),
            processed_count,
        )
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
        consolidation_candidates = 0
        consolidation_archived = 0
        episode_ids: list[str] = []
        embedding_texts = [
            episode["summary"] for episode in extracted["episodes"]
        ] + [
            f"{claim['entity']} {claim['relation']} {claim['target']}"
            for claim in extracted["claims"]
        ]
        embeddings = await embed_texts_async(embedding_texts, profile=profile)
        logger.info(
            "memory batch embeddings provider=%s requested=%s returned=%s",
            YUZU_PORTAL,
            len(embedding_texts),
            len(embeddings),
        )
        episode_embeddings = embeddings[: len(extracted["episodes"])]
        claim_embeddings = embeddings[len(extracted["episodes"]):]
        for episode_index, episode in enumerate(extracted["episodes"]):
            segment_messages = unsegmented[
                episode["start_index"] : episode["end_index"]
            ]
            source_ids = [str(message.get("id")) for message in segment_messages]
            embedding = episode_embeddings[episode_index] if episode_index < len(episode_embeddings) else None
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

        for claim_index, claim in enumerate(extracted["claims"]):
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
                embedding=claim_embeddings[claim_index] if claim_index < len(claim_embeddings) else None,
                confidence=claim["confidence"],
                importance=0.7,
                embedding_model="gemini-embedding-2-preview",
                embedding_dimensions=1536,
            )
            if node_row:
                node_id = str(node_row["id"])
                if episode_id:
                    evidence_message_ids = metadata.get("evidence_message_ids", [])
                    if not isinstance(evidence_message_ids, list):
                        evidence_message_ids = []
                    evidence_message_ids = [
                        item
                        for item in evidence_message_ids
                        if isinstance(item, (str, int))
                    ]
                    _ = await GraphMemoryRepository.add_evidence(
                        user_id=user_id,
                        node_id=node_id,
                        episode_id=episode_id,
                        message_ids=evidence_message_ids,
                    )
                claim_count += 1
                consolidation = await GraphMemoryRepository.consolidate_node(
                    user_id=user_id,
                    node_id=node_id,
                    node_type="fact",
                    content=node_content,
                )
                consolidation_candidates += consolidation["candidates"]
                consolidation_archived += consolidation["archived"]

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
                        _ = await GraphMemoryRepository.add_edge(
                            user_id=user_id,
                            from_node_id=node_id,
                            to_node_id=str(related_node["id"]),
                            edge_type="related_to",
                            confidence=min(
                                claim["confidence"], related_claim["confidence"]
                            ),
                        )

        logger.info(
            "memory extraction complete episodes=%s claims=%s consolidation_candidates=%s consolidation_archived=%s llm_calls=%s elapsed_ms=%s",
            episode_count,
            claim_count,
            consolidation_candidates,
            consolidation_archived,
            llm_calls,
            int((time.monotonic() - started) * 1000),
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
            "consolidation_candidates": consolidation_candidates,
            "consolidation_archived": consolidation_archived,
        }
    finally:
        await _clear_fence_async(session_id, user_id=user_id)
        logger.debug(f"Fence cleared for session {session_id}")


# ── Background thread launcher ─────────────────────────────────────────────────


async def _background_worker_async():
    """Async background worker."""
    while True:
        item = await _pending_sessions.get()
        session_to_process, user_id, keyrings = item[0], item[1], item[2]
        if not session_to_process or not user_id:
            _pending_sessions.task_done()
            continue
        try:
            if keyrings:
                set_request_keyrings(keyrings)
            # Retrieve count from DB-persisted fence
            started = time.monotonic()
            for _ in range(MAX_BATCHES_PER_WORKER):
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
                if isinstance(last_message_id, int):
                    last_message_id = "00000000-0000-0000-0000-000000000000"

                remaining = await get_session_messages_after_id_async(
                    session_to_process,
                    last_message_id or "00000000-0000-0000-0000-000000000000",
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
            clear_request_keyring()
            _queued_sessions.discard((session_to_process, user_id))
            _pending_sessions.task_done()


async def enqueue_memory_pipeline_async(session_id: str, user_id: str) -> bool:
    """Enqueue a session for background memory pipeline processing.

    Non-blocking — returns immediately. Disabled memory never starts a worker.
    """
    global _worker_task

    profile = await Database.get_profile(user_id)
    if not get_provider_key(YUZU_PORTAL):
        logger.info("memory enqueue skipped: missing Yuzu Portal API key")
        return False

    queue_key = (session_id, user_id)
    if queue_key in _queued_sessions:
        return False

    _queued_sessions.add(queue_key)
    keyrings = get_request_keyrings()
    try:
        if _worker_task is None or _worker_task.done():
            _worker_task = asyncio.create_task(_background_worker_async())
        await _pending_sessions.put((session_id, user_id, keyrings))
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
    profile = await Database.get_profile(user_id)
    if not get_provider_key(YUZU_PORTAL):
        logger.info("memory job skipped: missing Yuzu Portal API key")
        return False

    should_trigger, _ = await should_trigger_segmentation_async(
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
