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

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

__all__ = [
    "trigger_memory_pipeline_async",
    "enqueue_memory_pipeline",
    "run_memory_pipeline",
    "run_memory_review",
    "batch_segment",
    "create_episode_and_pcl",
    "should_trigger_segmentation",
    "mark_segmentation_done",
    "_clear_request_cache",  # Exported for orchestrator to call at end of request
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
IDLE_GATE_HOURS = 3.0  # session must be idle this long before triggering (unless WINDOW_MAX)

# Fence constants (aligned with plast-mem)
FENCE_TTL_MINUTES = 120  # Stale job cleanup threshold

# ── Background thread state ───────────────────────────────────────────────────

_pipeline_thread: threading.Thread | None = None
_pipeline_lock = threading.Lock()
_pending_sessions: set[int] = set()  # Sessions queued for processing

# ── Fence state (per-session) ─────────────────────────────────────────────────

# Fence is now persisted to DB (memo) for crash safety.
# Fields: in_progress_fence_count, in_progress_fence_since

_fence_lock = threading.Lock()

# ── Request-scoped cache ───────────────────────────────────────────────────────

_request_cache = threading.local()


def _get_cached_memory_state(session_id: int) -> dict:
    """Get memory state with request-scoped cache.
    
    Prevents multiple DB calls for same session within single request.
    """
    cache_key = f"memory_state_{session_id}"
    if hasattr(_request_cache, cache_key):
        return getattr(_request_cache, cache_key)
    
    from app.database import get_memory_state
    state = get_memory_state(session_id)
    setattr(_request_cache, cache_key, state)
    return state


def _clear_request_cache(session_id: int | None = None) -> None:
    """Clear request-scoped cache at end of request."""
    if session_id is not None:
        key = f"memory_state_{session_id}"
        if hasattr(_request_cache, key):
            delattr(_request_cache, key)
    else:
        # Clear all memory_state_* attributes
        for attr in list(dir(_request_cache)):
            if attr.startswith("memory_state_"):
                delattr(_request_cache, attr)


def _try_set_fence(session_id: int, fence_count: int) -> bool:
    """Atomically set fence for a session if not already set.
    
    Persists fence to DB for crash safety.
    Returns True if fence was set (no existing fence).
    """
    from app.database import update_memory_state
    
    with _fence_lock:
        now = datetime.now()
        state = _get_cached_memory_state(session_id)
        
        # Check if fence exists
        existing_count = state.get("in_progress_fence_count")
        existing_since = state.get("in_progress_fence_since")
        
        logger.debug(f"_try_set_fence: session={session_id}, fence_count={fence_count}, existing_count={existing_count}, existing_since={existing_since}")
        
        if existing_count is not None and existing_since is not None:
            # Check if fence is stale (TTL exceeded)
            try:
                existing_dt = datetime.fromisoformat(existing_since)
                age = now - existing_dt
                if age > timedelta(minutes=FENCE_TTL_MINUTES):
                    # Clear stale fence
                    logger.info(f"Clearing stale fence for session {session_id} (age={age})")
                else:
                    # Fence is active, cannot set
                    return False
            except (ValueError, TypeError):
                pass  # Invalid timestamp, proceed to overwrite
        
        # Set new fence in DB
        update_memory_state(session_id, {
            "in_progress_fence_count": fence_count,
            "in_progress_fence_since": now.isoformat(),
        })
        return True


def _clear_fence(session_id: int) -> None:
    """Clear the fence for a session after processing completes."""
    from app.database import update_memory_state
    
    with _fence_lock:
        update_memory_state(session_id, {
            "in_progress_fence_count": None,
            "in_progress_fence_since": None,
        })
        # Invalidate cache since we just modified state
        _clear_request_cache(session_id)


def _is_fence_active(session_id: int) -> bool:
    """Check if a session has an active (non-stale) fence."""
    with _fence_lock:
        state = _get_cached_memory_state(session_id)
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


def _get_session_idle_hours(session_id: int) -> float | None:
    """Get hours since last message in session. Returns None if no messages."""
    from app.database import get_session_messages
    # Need newest message — use DESC order
    messages = get_session_messages(session_id, limit=1, order="DESC")
    if not messages:
        return None
    last_ts = messages[0].get("timestamp")
    if not last_ts:
        return None
    try:
        last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00").replace("+00:00", ""))
        return (datetime.now() - last_dt).total_seconds() / 3600.0
    except Exception:
        return None


def should_trigger_segmentation(session_id: int, current_count: int) -> tuple[bool, int]:
    """Check if segmentation should trigger based on delta from last segmented.
    
    Returns (should_trigger, unsegmented_count) tuple.
    
    Logic: trigger when:
      - delta >= WINDOW_BASE AND session has been idle >= IDLE_GATE_HOURS, OR
      - delta >= WINDOW_MAX (force trigger regardless of idle)
    """
    # Check fence first
    if _is_fence_active(session_id):
        logger.debug("Segmentation skipped: fence active")
        return False, 0
    
    # Get last segmented count from persisted state (cached)
    state = _get_cached_memory_state(session_id)
    last_count = state.get("last_segmented_count", 0) or 0
    
    # Calculate delta (new unsegmented messages)
    delta = current_count - last_count
    
    # Force trigger regardless of idle
    if delta >= WINDOW_MAX:
        logger.info(f"Trigger: delta={delta} >= WINDOW_MAX={WINDOW_MAX} (force)")
        return True, delta
    
    # Not enough new messages
    if delta < WINDOW_BASE:
        logger.debug(f"Segmentation skipped: delta={delta} < WINDOW_BASE={WINDOW_BASE}")
        return False, delta
    
    # Gate: require session to be idle for IDLE_GATE_HOURS before processing
    idle_hours = _get_session_idle_hours(session_id)
    if idle_hours is not None and idle_hours < IDLE_GATE_HOURS:
        logger.debug(f"Segmentation skipped: idle={idle_hours:.1f}h < IDLE_GATE_HOURS={IDLE_GATE_HOURS}h")
        return False, delta
    
    logger.info(f"Trigger: delta={delta} >= WINDOW_BASE={WINDOW_BASE}, idle={idle_hours:.1f}h")
    return True, delta


def mark_segmentation_done(session_id: int, count: int) -> None:
    """Mark that segmentation completed for this session at this count.
    
    Persists last_segmented_count and last_segmented_at to session's memory_state.
    Called AFTER processing completes (not before).
    
    count should be the total conversation message count (user+assistant)
    at the time of marking. We re-read it from the DB to be safe since the
    fence's in_progress_fence_count may not reflect the true total.
    """
    from app.database import get_message_count, update_memory_state
    
    # Re-read actual current total from DB — fence count may be stale or 0
    actual_total = get_message_count(session_id)
    
    update_memory_state(session_id, {
        "last_segmented_count": actual_total,
        "last_segmented_at": datetime.now().isoformat(),
    })
    logger.info(f"Marked segmentation done: session={session_id}, count={actual_total}")


# ── Batch segmentation (single LLM call) ───────────────────────────────────────

def _get_ai_manager():
    """Lazy-import to avoid circular imports."""
    from app import get_ai_manager
    return get_ai_manager()


def _build_batch_segment_prompt(messages: list[dict]) -> tuple[str, str]:
    """Build the batch segmentation prompt.
    
    Returns (system_prompt, user_prompt).
    """
    conversation = "\n".join(
        f"[{i}] {'User' if m.get('role') == 'user' else 'AI'}: {m.get('content', '')[:200]}"
        for i, m in enumerate(messages)
        if m.get("role") in ("user", "assistant")
    )
    
    system_prompt = """You are a conversation segmenter. Split the conversation into meaningful episodes.

IMPORTANT: Output ONLY a raw JSON array. Do NOT use markdown code blocks, do NOT wrap in ```json. Start with [ and end with ].

Schema:
[
  {
    "start_idx": 0,
    "end_idx": 5,
    "title": "5-15 word theme",
    "summary": "2-3 sentence third-person narrative of what happened",
    "surprise_level": "low" | "high" | "extremely_high"
  }
]

Boundary criteria (OR):
1. Topic shift — subject, activity, or intent changes
2. Surprise — emotional reversal, domain jump, tone change

Guidelines:
- Each segment should be 5-20 messages
- surprise_level: low (0.2), high (0.6), extremely_high (0.9)
- Cover ALL messages — last segment should end at the last message index"""

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
            segments.append({
                "start_idx": start_idx,
                "end_idx": i,
                "title": None,  # Will be generated by LLM if needed
                "summary": None,
                "surprise_level": 0.2,  # Default low
                "temporal_boundary": True,  # Mark as temporal fast-path
            })
            start_idx = i
    
    # Final segment
    if start_idx < len(messages):
        segments.append({
            "start_idx": start_idx,
            "end_idx": len(messages),
            "title": None,
            "summary": None,
            "surprise_level": 0.2,
            "temporal_boundary": True,
        })
    
    return segments


def batch_segment(messages: list[dict]) -> list[dict]:
    """Segment messages into episodes using dual-channel detection.
    
    Channel 1 (Fast-path): Temporal rule - time gaps >= 15 minutes
    Channel 2 (LLM): Topic shift + surprise detection
    
    Returns list of segment dicts:
        [{start_idx, end_idx, title, summary, surprise_level}, ...]
    """
    if len(messages) < MIN_MESSAGES:
        return []
    
    # Channel 1: Temporal fast-path
    temporal_segments = _apply_temporal_segmentation(messages)
    
    # If temporal segmentation yields exactly 1 segment covering all messages,
    # fall through to LLM for more granular detection
    if len(temporal_segments) <= 1:
        # No obvious time gaps - use LLM for topic shift detection
        return _llm_batch_segment(messages)
    
    # Temporal boundaries found - use them, but still run LLM for titles/summaries
    logger.info(f"Temporal fast-path: {len(temporal_segments)} segments via time-gap detection")
    
    # Run LLM to enhance segments with titles and summaries
    enhanced = _enhance_temporal_segments(messages, temporal_segments)
    return enhanced


def _llm_batch_segment(messages: list[dict]) -> list[dict]:
    """LLM-only segmentation (original batch_segment logic)."""
    try:
        ai = _get_ai_manager()
    except Exception as e:
        logger.warning(f"AI manager unavailable: {e}")
        return []
    
    system_prompt, user_prompt = _build_batch_segment_prompt(messages)
    
    try:
        response = ai._internal_llm_call(
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
            logger.warning(f"Batch segment: invalid JSON response (first 200 chars): {stripped[:200]}")
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
            valid.append({
                "start_idx": start,
                "end_idx": end,
                "title": str(s.get("title", "Untitled"))[:50],
                "summary": str(s.get("summary", "")),
                "surprise_level": surprise_map[surprise],
            })
        
        return valid
    
    except Exception as e:
        logger.warning(f"Batch segmentation failed: {e}")
        return []


def _enhance_temporal_segments(messages: list[dict], temporal_segments: list[dict]) -> list[dict]:
    """Enhance temporal segments with LLM-generated titles and summaries.
    
    This is called when temporal fast-path finds time gaps.
    Instead of running full segmentation, we just generate metadata.
    """
    enhanced = []
    
    for seg in temporal_segments:
        start_idx = seg.get("start_idx", 0)
        end_idx = seg.get("end_idx", len(messages))
        seg_msgs = messages[start_idx:end_idx]
        
        if len(seg_msgs) < 3:
            # Too short for LLM, use default
            enhanced.append({
                **seg,
                "title": f"Segment {start_idx}-{end_idx}",
                "summary": "Brief conversation segment.",
            })
            continue
        
        # Generate title and summary via LLM
        try:
            ai = _get_ai_manager()
            
            conversation = "\n".join(
                f"{'User' if m.get('role') == 'user' else 'AI'}: {m.get('content', '')[:150]}"
                for m in seg_msgs
                if m.get("role") in ("user", "assistant")
            )
            
            prompt = f"""Summarize this conversation segment in 2-3 sentences (third-person narrative).
Then give it a 5-15 word title.

Respond as JSON:
{{"title": "...", "summary": "..."}}

Conversation:
{conversation}"""
            
            response = ai._internal_llm_call(
                messages=[{"role": "user", "content": prompt}],
                timeout=30,
                max_tokens=300,
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
                
                enhanced.append({
                    **seg,
                    "title": title,
                    "summary": summary,
                })
                continue
                
        except Exception as e:
            logger.debug(f"Enhance temporal segment failed: {e}")
        
        # Fallback
        enhanced.append({
            **seg,
            "title": f"Segment {start_idx}-{end_idx}",
            "summary": "Conversation segment.",
        })
    
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


def create_episode_and_pcl(
    session_id: int,
    messages: list[dict],
    segment: dict,
) -> Optional[int]:
    """Create an episode from a segment and trigger PCL pipeline.

    Returns episode ID or None on failure (e.g. segment skipped for low importance).
    """
    from app.memory.db_memory import save_fact, FACT_TYPE_DYNAMIC
    from app.memory.embedder import embed_text
    from app.memory.pcl import run_predict_calibrate

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
        embedding = embed_text(summary)
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
    episode_id = save_fact(
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
        pcl_result = run_predict_calibrate(
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

def run_memory_review(session_id: int) -> dict:
    """Run LLM-based memory review on pending reviews.
    
    Returns summary: {reviewed: n, ratings: {...}}
    """
    from app.memory.memory_review import review_memory
    from app.memory.db_memory import get_facts_by_session, FACT_TYPE_STATIC
    from app.database import get_session_messages
    
    try:
        # Get facts pending review
        facts = get_facts_by_session(session_id, fact_type=FACT_TYPE_STATIC, limit=50)
        pending_ids = [
            f["id"] for f in facts
            if f.get("metadata", {}).get("pending_review")
        ]
        
        if not pending_ids:
            logger.debug("No facts pending review")
            return {"reviewed": 0}
        
        # Get conversation context
        messages = get_session_messages(session_id, limit=20)
        context = "\n".join(
            f"{m.get('role', 'unknown')}: {m.get('content', '')[:200]}"
            for m in messages[-10:]
        ) if messages else ""
        
        result = review_memory(pending_ids, context, session_id)
        logger.info(f"Memory review: {result}")
        return result
    except Exception as e:
        logger.warning(f"Memory review failed: {e}")
        return {"reviewed": 0}


# ── Main pipeline runner ───────────────────────────────────────────────────────

def run_memory_pipeline(session_id: int, message_count: int) -> dict:
    """Run the full memory pipeline for a session.
    
    Steps:
      1. Get unsegmented messages
      2. Batch segment (single LLM call)
      3. Create episodes + PCL per segment
      4. Run memory review if pending
      5. Clear fence and mark done
    
    Returns summary: {segments: n, episodes: n, pcl_runs: n}
    """
    from app.database import get_session_messages, get_memory_state
    from app.memory.db_memory import get_facts_by_session, FACT_TYPE_DYNAMIC
    
    logger.info(f"Starting for session {session_id}, count={message_count}")
    
    # Get current total count for marking done
    state = get_memory_state(session_id)
    last_count = state.get("last_segmented_count", 0) or 0
    current_total = last_count  # Will be updated below
    
    try:
        # Get messages
        all_messages = get_session_messages(session_id, limit=10000)
        if not all_messages:
            return {"segments": 0, "episodes": 0, "pcl_runs": 0}
        
        # Find where we left off
        segments = get_facts_by_session(session_id, fact_type=FACT_TYPE_DYNAMIC, limit=100)
        segments = [s for s in segments if s.get("metadata", {}).get("source_table") == "episodic_memories"]
        
        if segments:
            last_end_id = max(s.get("metadata", {}).get("end_message_id", 0) for s in segments)
        else:
            last_end_id = 0
        
        # Filter to unsegmented messages
        unsegmented = [
            m for m in all_messages
            if m.get("id", 0) > last_end_id and m.get("role") in ("user", "assistant")
        ]
        
        # Get actual count of unsegmented messages for marking
        unsegmented_count = len(unsegmented)
        current_total = last_count + unsegmented_count
        
        if unsegmented_count < MIN_MESSAGES:
            logger.debug(f"Only {unsegmented_count} unsegmented msgs, skipping")
            # Still mark done with current total so we don't re-check these
            mark_segmentation_done(session_id, current_total)
            return {"segments": 0, "episodes": 0, "pcl_runs": 0}
        
        # Batch segment
        batch_result = batch_segment(unsegmented)
        if not batch_result:
            logger.debug("No segments from batch LLM")
            # Still mark done with current total
            mark_segmentation_done(session_id, current_total)
            return {"segments": 0, "episodes": 0, "pcl_runs": 0}
        
        logger.info(f"Batch segmentation: {len(batch_result)} segments")
        
        # Merge small segments
        batch_result = _merge_small_segments(batch_result)
        
        # Create episodes + PCL
        episode_count = 0
        pcl_count = 0
        
        for seg in batch_result:
            episode_id = create_episode_and_pcl(session_id, unsegmented, seg)
            if episode_id:
                episode_count += 1
                pcl_count += 1
        
        # Run memory review if there are pending reviews
        try:
            run_memory_review(session_id)
        except Exception as e:
            logger.warning(f"Memory review error: {e}")
        
        # Mark done - update last_segmented_count for next trigger calculation
        mark_segmentation_done(session_id, current_total)
        
        return {
            "segments": len(batch_result),
            "episodes": episode_count,
            "pcl_runs": pcl_count,
        }
    finally:
        # Always clear fence when done (even on error)
        # This mirrors plast-mem's finalize_job() behavior
        _clear_fence(session_id)
        logger.debug(f"Fence cleared for session {session_id}")


# ── Background thread launcher ─────────────────────────────────────────────────

def _background_worker():
    """Background thread worker — processes queued sessions."""
    global _pending_sessions
    
    while True:
        session_to_process = None
        
        with _pipeline_lock:
            if _pending_sessions:
                session_to_process = _pending_sessions.pop()
        
        if session_to_process:
            try:
                # Retrieve count from DB-persisted fence
                from app.database import get_memory_state
                state = get_memory_state(session_to_process)
                count = state.get("in_progress_fence_count", 0) or 0
                
                run_memory_pipeline(session_to_process, count)
            except Exception as e:
                logger.error(f"Background worker error: {e}")
        else:
            time.sleep(1)  # No work, wait


def enqueue_memory_pipeline(session_id: int) -> None:
    """Queue a session for background memory processing.
    
    Non-blocking — returns immediately.
    """
    global _pending_sessions, _pipeline_thread
    
    # Start worker thread if not running
    if _pipeline_thread is None or not _pipeline_thread.is_alive():
        _pipeline_thread = threading.Thread(target=_background_worker, daemon=True)
        _pipeline_thread.start()
        logger.info("Started background worker thread")
    
    with _pipeline_lock:
        _pending_sessions.add(session_id)
    
    logger.info(f"Queued session {session_id} for background processing")


def trigger_memory_pipeline_async(session_id: int, current_count: int) -> bool:
    """Check and trigger memory pipeline in background if threshold met.
    
    Returns True if pipeline was triggered.
    """
    should_trigger, delta = should_trigger_segmentation(session_id, current_count)
    
    if not should_trigger:
        return False
    
    # Try to set fence with current_count (total messages at trigger time)
    if not _try_set_fence(session_id, current_count):
        logger.debug(f"Could not set fence for session {session_id}")
        return False
    
    enqueue_memory_pipeline(session_id)
    return True
