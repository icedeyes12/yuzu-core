# FILE: app/memory/memory.py
# DESCRIPTION: Background memory pipeline runner.
#              Spawns a daemon thread that processes segmentation, PCL, and memory review
#              in the background without blocking the main chat loop.
#
# Architecture (aligned with plast-mem):
#   1. Segmentation → batch_segment() creates episodes
#   2. PCL → create_episode_and_pcl() extracts semantic facts
#   3. Memory Review → run_memory_review() updates FSRS parameters
#
# Trigger gates (all must pass):
#   - delta >= WINDOW_BASE (40) AND session idle >= IDLE_GATE_HOURS (3h), OR
#   - delta >= WINDOW_MAX (50) — force trigger regardless of idle
#
# Episode creation gates:
#   - Segment must have >= MIN_SEGMENT_MESSAGES (8) messages (small segments merged)
#   - Episode importance must be >= MIN_EPISODE_IMPORTANCE (0.45) — low-surprise
#     segments are skipped to prevent semantic-fact noise
#
# Fence mechanism (aligned with plast-mem):
#   - in_progress_fence: prevents concurrent pipeline runs for same session
#   - fence_ttl_minutes: 120 minutes (stale job cleanup)

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.db import (
    get_memory_state_async,
    update_memory_state_async,
    get_session_messages_async,
    get_message_count_async,
)

__all__ = [
    "trigger_memory_pipeline_async",
    "enqueue_memory_pipeline_async",
    "run_memory_pipeline_async",
    "run_memory_review_async",
    "batch_segment_async",
    "create_episode_and_pcl_async",
    "should_trigger_segmentation_async",
    "mark_segmentation_done_async",
]

logger = logging.getLogger(__name__)

# Segmentation constants (aligned with plast-mem)
# WINDOW_BASE: trigger when delta >= this AND idle > 3 min
# WINDOW_MAX: force trigger regardless of idle
WINDOW_BASE = 40
WINDOW_MAX = 50
MIN_MESSAGES = 10
TIME_GAP_MINUTES = 30
MIN_SEGMENT_MESSAGES = 8  # minimum messages per segment before merging
MIN_EPISODE_IMPORTANCE = 0.45  # skip episodes with importance below this
IDLE_GATE_HOURS = (
    3.0  # session must be idle this long before triggering (unless WINDOW_MAX)
)

# Fence constants (aligned with plast-mem)
FENCE_TTL_MINUTES = 120  # Stale job cleanup threshold

# ── Background state ─────────────────────────────────────────────────────────

_pending_sessions: asyncio.Queue[int] = asyncio.Queue()
_worker_task: Optional[asyncio.Task] = None


async def _get_cached_memory_state_async(session_id: int) -> dict:
    """Get memory state (async)."""
    # Request-scoped cache might still be useful, but for now just proxy
    return await get_memory_state_async(session_id)


async def _try_set_fence_async(session_id: int, fence_count: int) -> bool:
    """Atomically set fence for a session (async)."""
    now = datetime.now()
    state = await _get_cached_memory_state_async(session_id)

    existing_count = state.get("in_progress_fence_count")
    existing_since = state.get("in_progress_fence_since")

    if existing_count is not None and existing_since is not None:
        try:
            existing_dt = datetime.fromisoformat(existing_since)
            age = now - existing_dt
            if age > timedelta(minutes=FENCE_TTL_MINUTES):
                logger.info(f"Clearing stale fence for session {session_id}")
            else:
                return False
        except (ValueError, TypeError):
            pass

    await update_memory_state_async(
        session_id,
        {
            "in_progress_fence_count": fence_count,
            "in_progress_fence_since": now.isoformat(),
        },
    )
    return True


async def _clear_fence_async(session_id: int) -> None:
    """Clear fence (async)."""
    await update_memory_state_async(
        session_id,
        {
            "in_progress_fence_count": None,
            "in_progress_fence_since": None,
        },
    )


async def _is_fence_active_async(session_id: int) -> bool:
    """Check if fence is active (async)."""
    state = await _get_cached_memory_state_async(session_id)
    existing_count = state.get("in_progress_fence_count")
    existing_since = state.get("in_progress_fence_since")

    if existing_count is None or existing_since is None:
        return False

    try:
        existing_dt = datetime.fromisoformat(existing_since)
        age = datetime.now() - existing_dt
        return age <= timedelta(minutes=FENCE_TTL_MINUTES)
    except (ValueError, TypeError):
        return False


async def _get_session_idle_hours_async(session_id: int) -> float | None:
    """Get idle hours (async)."""
    messages = await get_session_messages_async(session_id, limit=1, order="DESC")
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


async def should_trigger_segmentation_async(
    session_id: int, current_count: int
) -> tuple[bool, int]:
    """Check if segmentation should trigger (async)."""
    if await _is_fence_active_async(session_id):
        return False, 0

    state = await _get_cached_memory_state_async(session_id)
    last_count = state.get("last_segmented_count", 0) or 0
    delta = current_count - last_count

    if delta >= WINDOW_MAX:
        return True, delta

    if delta < WINDOW_BASE:
        return False, delta

    idle_hours = await _get_session_idle_hours_async(session_id)
    if idle_hours is not None and idle_hours < IDLE_GATE_HOURS:
        return False, delta

    return True, delta


async def mark_segmentation_done_async(session_id: int, count: int) -> None:
    """Mark segmentation done (async)."""
    actual_total = await get_message_count_async(session_id)

    await update_memory_state_async(
        session_id,
        {
            "last_segmented_count": actual_total,
            "last_segmented_at": datetime.now().isoformat(),
        },
    )


# ── Batch segmentation (single LLM call) ───────────────────────────────────────


def _get_ai_manager():
    """Lazy-import to avoid circular imports."""
    from app.providers import get_ai_manager

    return get_ai_manager()


async def _get_ai_manager_async():
    """Async version - lazy-import to avoid circular imports."""
    from app.providers import get_ai_manager

    return await get_ai_manager()


def _build_batch_segment_prompt(messages: list[dict]) -> tuple[str, str]:
    """Build the batch segmentation prompt.

    Returns (system_prompt, user_prompt).
    """
    conversation = "\n".join(
        f"[{i}] {'User' if m.get('role') == 'user' else 'AI'}: {m.get('content', '')[:200]}"
        for i, m in enumerate(messages)
        if m.get("role") in ("user", "assistant")
    )

    system_prompt = """You are a deterministic conversation segmenter. Split the conversation into contiguous segments based on topic shifts OR surprising turns. Each segment gets a retrieval priority score.

## OUTPUT FORMAT (JSON array ONLY, no other text)
Return exactly a JSON array of segment objects. Each object has these keys: start_idx, end_idx, title, summary, surprise_level.

## FORMAT ILLUSTRATION (placeholders only, never copy these values)
[
  {
    "start_idx": <integer>,
    "end_idx": <integer>,
    "title": "<5-15 word theme>",
    "summary": "<2-3 sentence factual description>",
    "surprise_level": "<low|high|extremely_high>"
  },
  ...
]

## BOUNDARY CRITERIA (apply either)
1. **Topic shift** — The explicit subject, activity, or stated intent changes.
2. **Surprise** — An unexpected reversal, domain jump, or sharp tone contrast. Judge ONLY from explicit textual cues (abrupt theme change, direct contradiction of earlier statement, striking stylistic contrast).

## SURPRISE LEVEL AS RETRIEVAL WEIGHT
These labels carry numerical weights used for vector search priority:
- **low** (weight 0.2): Predictable continuation of topic and tone. Routine segment.
- **high** (weight 0.6): Clear shift to a new, unrelated domain, or a statement contradicting a prior assumption. Important segment.
- **extremely_high** (weight 0.9): Dramatic reversal resetting the entire conversational frame (e.g., casual chat → emergency debugging, revelation of a major life event). Critical segment.

## STRICT RULES
- Cover ALL messages contiguously. Last segment's end_idx must be the last message index.
- Prefer 5-20 messages per segment; only break earlier if a boundary is triggered.
- Base title and summary STRICTLY on conversation content. Do NOT embellish or infer.
- Output the JSON array ONLY. No markdown, no backticks, no surrounding text."""

    user_prompt = f"Segment this conversation:\n\n{conversation}"

    return system_prompt, user_prompt


def _detect_time_gap(messages: list[dict], idx: int) -> bool:
    """Check if there's a time gap >= TIME_GAP_MINUTES at the given index.

    Temporal fast-path: if gap detected, we can segment without LLM.
    Returns True if there's a significant time gap.
    """
    if idx <= 0 or idx >= len(messages):
        return False

    try:
        from datetime import datetime

        prev_msg = messages[idx - 1]
        curr_msg = messages[idx]

        prev_ts = prev_msg.get("timestamp")
        curr_ts = curr_msg.get("timestamp")

        if not prev_ts or not curr_ts:
            return False

        # Parse timestamps
        if isinstance(prev_ts, str):
            try:
                prev_dt = datetime.strptime(prev_ts, "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                prev_dt = datetime.strptime(prev_ts, "%Y-%m-%d %H:%M:%S")
        else:
            prev_dt = prev_ts

        if isinstance(curr_ts, str):
            try:
                curr_dt = datetime.strptime(curr_ts, "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                curr_dt = datetime.strptime(curr_ts, "%Y-%m-%d %H:%M:%S")
        else:
            curr_dt = curr_ts

        # Calculate gap
        gap_minutes = (curr_dt - prev_dt).total_seconds() / 60.0
        return gap_minutes >= TIME_GAP_MINUTES

    except Exception as e:
        logger.debug(f"Time gap detection failed: {e}")
        return False


def _apply_temporal_segmentation(messages: list[dict]) -> list[dict]:
    """Temporal fast-path: segment by time gaps without LLM.

    Returns list of segment boundaries where time gaps >= 15 minutes.
    Each segment has minimal metadata (no title/summary - added later).
    """
    if len(messages) < MIN_MESSAGES:
        return []

    segments = []
    start_idx = 0

    for i in range(1, len(messages)):
        if _detect_time_gap(messages, i):
            # Time gap found - create segment
            segments.append(
                {
                    "start_idx": start_idx,
                    "end_idx": i,
                    "title": None,  # Will be generated by LLM if needed
                    "summary": None,
                    "surprise_level": 0.2,  # Default low
                    "temporal_boundary": True,  # Mark as temporal fast-path
                }
            )
            start_idx = i

    # Final segment
    if start_idx < len(messages):
        segments.append(
            {
                "start_idx": start_idx,
                "end_idx": len(messages),
                "title": None,
                "summary": None,
                "surprise_level": 0.2,
                "temporal_boundary": True,
            }
        )

    return segments


async def batch_segment_async(messages: list[dict]) -> list[dict]:
    """Segment messages (async)."""
    if len(messages) < MIN_MESSAGES:
        return []

    temporal_segments = _apply_temporal_segmentation(messages)

    if len(temporal_segments) <= 1:
        return await _llm_batch_segment_async(messages)

    enhanced = await _enhance_temporal_segments_async(messages, temporal_segments)
    return enhanced


async def _llm_batch_segment_async(messages: list[dict]) -> list[dict]:
    """LLM-only segmentation (async)."""
    try:
        ai = await _get_ai_manager_async()
    except Exception:
        return []

    system_prompt, user_prompt = _build_batch_segment_prompt(messages)

    try:
        response = await ai._internal_llm_call(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=60,
            max_tokens=4096,
        )
        if not response:
            return []

        import json
        import re

        # Strip markdown code blocks if present
        stripped = response.strip()
        if stripped.startswith("```"):
            # Remove ```json or ``` at start
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            # Remove ``` at end
            stripped = re.sub(r"\s*```$", "", stripped)
            stripped = stripped.strip()

        segments = None
        # Try to parse, handle truncation

        # First try as-is
        try:
            segments = json.loads(stripped)
            if not isinstance(segments, list):
                segments = None
        except json.JSONDecodeError:
            segments = None

        # If failed, try to close truncated array
        if segments is None:
            for close_attempt in ["]", "]", "}]"]:
                try:
                    segments = json.loads(stripped + close_attempt)
                    if isinstance(segments, list):
                        break
                except json.JSONDecodeError:
                    continue

        # Last resort: chop from end
        if segments is None:
            for i in range(len(stripped) - 1, 0, -1):
                try:
                    segments = json.loads(stripped[:i] + "]")
                    if isinstance(segments, list):
                        break
                except json.JSONDecodeError:
                    continue

        if not isinstance(segments, list):
            logger.warning(
                f"Batch segment: invalid JSON response (first 200 chars): {stripped[:200]}"
            )
            return []

        # Validate and normalize
        valid = []
        for s in segments:
            if not isinstance(s, dict):
                continue
            start = s.get("start_idx", 0)
            end = s.get("end_idx", 0)
            if end <= start:
                continue
            surprise = s.get("surprise_level", "low")
            if surprise not in ("low", "high", "extremely_high"):
                surprise = "low"
            surprise_map = {"low": 0.2, "high": 0.6, "extremely_high": 0.9}
            valid.append(
                {
                    "start_idx": start,
                    "end_idx": end,
                    "title": str(s.get("title", "Untitled"))[:50],
                    "summary": str(s.get("summary", "")),
                    "surprise_level": surprise_map[surprise],
                }
            )

        return valid

    except Exception as e:
        logger.warning(f"Batch segmentation failed: {e}")
        return []


async def _enhance_temporal_segments_async(
    messages: list[dict], temporal_segments: list[dict]
) -> list[dict]:
    """Enhance temporal segments with LLM (async)."""
    enhanced = []

    for seg in temporal_segments:
        start_idx = seg.get("start_idx", 0)
        end_idx = seg.get("end_idx", len(messages))
        seg_msgs = messages[start_idx:end_idx]

        if len(seg_msgs) < 3:
            # Too short for LLM, use default
            enhanced.append(
                {
                    **seg,
                    "title": f"Segment {start_idx}-{end_idx}",
                    "summary": "Brief conversation segment.",
                }
            )
            continue

        # Generate title and summary via LLM
        try:
            ai = await _get_ai_manager_async()

            conversation = "\n".join(
                f"{'User' if m.get('role') == 'user' else 'AI'}: {m.get('content', '')[:150]}"
                for m in seg_msgs
                if m.get("role") in ("user", "assistant")
            )

            prompt = f"""You are a deterministic segment annotator. Given a conversation segment, output a JSON object with a title and a factual summary.

## OUTPUT FORMAT (JSON object ONLY, no other text)
{{"title": "<5-15 word theme>", "summary": "<2-3 sentence factual description of what was discussed>"}}

## STRICT RULES
- Base the title and summary STRICTLY on the conversation content provided. Do not infer, embellish, or add external context.
- Write the summary in third-person, present tense. Describe only what was explicitly discussed.
- Do NOT mention segment indices or message positions.
- Output the JSON object ONLY. No markdown, no backticks, no surrounding text.

Conversation:
{conversation}"""

            response = await ai._internal_llm_call(
                messages=[{"role": "user", "content": prompt}],
                timeout=30,
                max_tokens=600,  # Naik dari 300 ke 600
            )

            if response:
                import json

                # Parse JSON response
                try:
                    # Strip markdown if present
                    stripped = response.strip()
                    if stripped.startswith("```"):
                        import re

                        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
                        stripped = re.sub(r"\s*```$", "", stripped)

                    parsed = json.loads(stripped)
                    title = str(parsed.get("title", "Untitled"))[:50]
                    summary = str(parsed.get("summary", ""))[:500]
                except (json.JSONDecodeError, TypeError):
                    # Fallback: use first 50 chars
                    title = response[:50].strip()
                    summary = response[:200].strip()

                enhanced.append(
                    {
                        **seg,
                        "title": title,
                        "summary": summary,
                    }
                )
                continue

        except Exception as e:
            logger.debug(f"Enhance temporal segment failed: {e}")

        # Fallback
        enhanced.append(
            {
                **seg,
                "title": f"Segment {start_idx}-{end_idx}",
                "summary": "Conversation segment.",
            }
        )

    return enhanced


def _merge_small_segments(segments: list[dict]) -> list[dict]:
    """Merge segments smaller than MIN_SEGMENT_MESSAGES into adjacent larger segments.

    This prevents trivial micro-segments (e.g. 3 messages) from each creating
    noisy episodes and generating low-value semantic facts.
    """
    if not segments:
        return []

    # First pass: mark tiny segments for absorption
    merged: list[dict] = []
    for seg in segments:
        size = seg["end_idx"] - seg["start_idx"]
        if size < MIN_SEGMENT_MESSAGES and merged:
            # Absorb into previous segment
            merged[-1]["end_idx"] = seg["end_idx"]
            # Keep the higher surprise_level of the two
            prev_surprise = merged[-1].get("surprise_level", 0.2)
            curr_surprise = seg.get("surprise_level", 0.2)
            merged[-1]["surprise_level"] = max(prev_surprise, curr_surprise)
            logger.debug(f"Merged tiny segment ({size} msgs) into previous")
        elif size >= MIN_SEGMENT_MESSAGES:
            merged.append(seg)
        else:
            # Very first segment is tiny and there's nothing to merge into yet — keep it
            merged.append(seg)

    return merged


# ── Episode creation with PCL trigger ──────────────────────────────────────────

FLASHBULB_THRESHOLD = 0.85
BASE_STABILITY = 24.0  # Aligned with FSRS default (24 hours)


async def create_episode_and_pcl_async(
    session_id: int,
    messages: list[dict],
    segment: dict,
) -> Optional[int]:
    """Create an episode and trigger PCL (async)."""
    from app.memory.db_memory import save_fact_async, FACT_TYPE_DYNAMIC
    from app.memory.embedder import embed_text_async
    from app.memory.pcl import run_predict_calibrate_async

    start_idx = segment.get("start_idx", 0)
    end_idx = segment.get("end_idx", len(messages))
    segment_msgs = messages[start_idx:end_idx]

    if not segment_msgs:
        return None

    title = segment.get("title", "Untitled")
    summary = segment.get("summary", "")
    surprise = segment.get("surprise_level", 0.2)

    if not summary:
        summary = title  # Fallback to title if no summary

    # Calculate importance and skip low-importance segments
    importance = 0.5 + surprise * 0.3

    if importance < MIN_EPISODE_IMPORTANCE:
        logger.debug(
            f"Skipping episode '{title}': importance={importance:.2f} < MIN_EPISODE_IMPORTANCE={MIN_EPISODE_IMPORTANCE}"
        )
        return None

    # Embed the summary
    embedding = None
    try:
        embedding = await embed_text_async(summary)
    except Exception as e:
        logger.warning(f"Embedding failed: {e}")

    stability = BASE_STABILITY

    # Flashbulb boost
    if surprise >= FLASHBULB_THRESHOLD:
        stability *= 1.5
        importance = min(importance + 0.1, 1.0)

    start_id = segment_msgs[0].get("id")
    end_id = segment_msgs[-1].get("id")

    # Create episode
    episode_id = await save_fact_async(
        session_id=session_id,
        content=f"{title}\n\n{summary}",
        embedding=embedding,
        fact_type=FACT_TYPE_DYNAMIC,
        metadata={
            "title": title,
            "summary": summary,
            "importance": importance,
            "stability": stability,
            "surprise_level": surprise,
            "source_table": "episodic_memories",
            "start_message_id": start_id,
            "end_message_id": end_id,
            "session_id": session_id,
        },
    )

    if not episode_id:
        logger.warning("Episode creation failed")
        return None

    logger.info(f"Created episode {episode_id}: {title} (importance={importance:.2f})")

    # Trigger PCL pipeline
    try:
        pcl_result = await run_predict_calibrate_async(
            session_id=session_id,
            episode_summary=summary,
            messages=segment_msgs,
            episode_id=episode_id,
        )
        if pcl_result:
            logger.debug(f"PCL result: {pcl_result}")
    except Exception as e:
        logger.warning(f"PCL failed for episode {episode_id}: {e}")

    return episode_id


# ── Memory review (pending reviews) ────────────────────────────────────────────


async def run_memory_review_async(session_id: int) -> dict:
    """Run LLM-based memory review on pending reviews.

    Returns summary: {reviewed: n, ratings: {...}}
    """
    from app.memory.memory_review import review_memory_async
    from app.memory.db_memory import get_facts_by_session_async, FACT_TYPE_STATIC

    try:
        # Get facts pending review
        facts = await get_facts_by_session_async(
            session_id, fact_type=FACT_TYPE_STATIC, limit=50
        )
        pending_ids = [
            f["id"] for f in facts if f.get("metadata", {}).get("pending_review")
        ]

        if not pending_ids:
            logger.debug("No facts pending review")
            return {"reviewed": 0}

        # Get conversation context
        messages = await get_session_messages_async(session_id, limit=20)
        context = (
            "\n".join(
                f"{m.get('role', 'unknown')}: {m.get('content', '')[:200]}"
                for m in messages[-10:]
            )
            if messages
            else ""
        )

        result = await review_memory_async(pending_ids, context, session_id)
        logger.info(f"Memory review: {result}")
        return result
    except Exception as e:
        logger.warning(f"Memory review failed: {e}")
        return {"reviewed": 0}


# ── Main pipeline runner ───────────────────────────────────────────────────────


async def run_memory_pipeline_async(session_id: int, message_count: int) -> dict:
    """Run the full memory pipeline for a session.

    Steps:
      1. Get unsegmented messages
      2. Batch segment (single LLM call)
      3. Create episodes + PCL per segment
      4. Run memory review if pending
      5. Clear fence and mark done

    Returns summary: {segments: n, episodes: n, pcl_runs: n}
    """
    from app.db import get_session_messages_async, get_memory_state_async
    from app.memory.db_memory import get_facts_by_session_async, FACT_TYPE_DYNAMIC

    logger.info(f"Starting for session {session_id}, count={message_count}")

    # Get current total count for marking done
    state = await get_memory_state_async(session_id)
    last_count = state.get("last_segmented_count", 0) or 0
    current_total = last_count  # Will be updated below

    try:
        # Get messages
        all_messages = await get_session_messages_async(session_id, limit=10000)
        if not all_messages:
            return {"segments": 0, "episodes": 0, "pcl_runs": 0}

        # Find where we left off
        segments = await get_facts_by_session_async(
            session_id, fact_type=FACT_TYPE_DYNAMIC, limit=100
        )
        segments = [
            s
            for s in segments
            if s.get("metadata", {}).get("source_table") == "episodic_memories"
        ]

        if segments:
            last_end_id = max(
                s.get("metadata", {}).get("end_message_id", 0) for s in segments
            )
        else:
            last_end_id = 0

        # Filter to unsegmented messages
        unsegmented = [
            m
            for m in all_messages
            if m.get("id", 0) > last_end_id and m.get("role") in ("user", "assistant")
        ]

        # Get actual count of unsegmented messages for marking
        unsegmented_count = len(unsegmented)
        current_total = last_count + unsegmented_count

        if unsegmented_count < MIN_MESSAGES:
            logger.debug(f"Only {unsegmented_count} unsegmented msgs, skipping")
            # Still mark done with current total so we don't re-check these
            await mark_segmentation_done_async(session_id, current_total)
            return {"segments": 0, "episodes": 0, "pcl_runs": 0}

        # Batch segment
        batch_result = await batch_segment_async(unsegmented)
        if not batch_result:
            logger.debug("No segments from batch LLM")
            # Still mark done with current total
            await mark_segmentation_done_async(session_id, current_total)
            return {"segments": 0, "episodes": 0, "pcl_runs": 0}

        logger.info(f"Batch segmentation: {len(batch_result)} segments")

        # Merge small segments
        batch_result = _merge_small_segments(batch_result)

        # Create episodes + PCL
        episode_count = 0
        pcl_count = 0

        for seg in batch_result:
            episode_id = await create_episode_and_pcl_async(
                session_id, unsegmented, seg
            )
            if episode_id:
                episode_count += 1
                pcl_count += 1

        # Run memory review if there are pending reviews
        try:
            await run_memory_review_async(session_id)
        except Exception as e:
            logger.warning(f"Memory review error: {e}")

        # Mark done - update last_segmented_count for next trigger calculation
        await mark_segmentation_done_async(session_id, current_total)

        return {
            "segments": len(batch_result),
            "episodes": episode_count,
            "pcl_runs": pcl_count,
        }
    finally:
        # Always clear fence when done (even on error)
        # This mirrors plast-mem's finalize_job() behavior
        await _clear_fence_async(session_id)
        logger.debug(f"Fence cleared for session {session_id}")


# ── Background thread launcher ─────────────────────────────────────────────────


async def _background_worker_async():
    """Async background worker."""
    while True:
        session_to_process = await _pending_sessions.get()
        try:
            # Retrieve count from DB-persisted fence
            from app.db import get_memory_state_async

            state = await get_memory_state_async(session_to_process)
            count = state.get("in_progress_fence_count", 0) or 0

            await run_memory_pipeline_async(session_to_process, count)
        except Exception as e:
            logger.error(f"Background worker error: {e}")
        finally:
            _pending_sessions.task_done()


async def enqueue_memory_pipeline_async(session_id: int) -> None:
    """Queue a session for background memory processing.

    Non-blocking — returns immediately.
    """
    global _worker_task

    # Start worker thread if not running
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_background_worker_async())

    await _pending_sessions.put(session_id)


async def trigger_memory_pipeline_async(session_id: int, current_count: int) -> bool:
    """Check and trigger memory pipeline in background if threshold met.

    Returns True if pipeline was triggered.
    """
    should_trigger, delta = await should_trigger_segmentation_async(
        session_id, current_count
    )

    if not should_trigger:
        return False

    # Try to set fence with current_count (total messages at trigger time)
    if not await _try_set_fence_async(session_id, current_count):
        logger.debug(f"Could not set fence for session {session_id}")
        return False

    await enqueue_memory_pipeline_async(session_id)
    return True
