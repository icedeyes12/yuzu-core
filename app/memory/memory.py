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
# Trigger: After every N messages (WINDOW_BASE=20) or time-gated per session.
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
]

logger = logging.getLogger(__name__)

# Segmentation constants (aligned with plast-mem)
WINDOW_BASE = 20  # trigger count
WINDOW_MAX = 40  # force process
MIN_MESSAGES = 5
TIME_GAP_MINUTES = 15

# Fence constants (aligned with plast-mem)
FENCE_TTL_MINUTES = 120  # Stale job cleanup threshold

# ── Background thread state ───────────────────────────────────────────────────

_pipeline_thread: threading.Thread | None = None
_pipeline_lock = threading.Lock()
_pending_sessions: set[int] = set()  # Sessions queued for processing

# ── Fence state (per-session) ─────────────────────────────────────────────────

# in_progress_fence: session_id -> (fence_count, timestamp)
# Mirrors plast-mem's in_progress_fence + in_progress_since columns
_in_progress_fence: dict[int, tuple[int, datetime]] = {}
_fence_lock = threading.Lock()

# ── Message counter tracking (per-session) ─────────────────────────────────────


def _try_set_fence(session_id: int, fence_count: int) -> bool:
    """Atomically set fence for a session if not already set.
    
    Mirrors plast-mem's try_set_fence():
    - Returns True if fence was set (no existing fence)
    - Returns False if fence already exists
    
    This is the CAS (Compare-And-Swap) operation that prevents concurrent jobs.
    """
    with _fence_lock:
        now = datetime.now()
        
        # Check if fence exists
        if session_id in _in_progress_fence:
            existing_count, existing_since = _in_progress_fence[session_id]
            
            # Check if fence is stale (TTL exceeded)
            age = now - existing_since
            if age > timedelta(minutes=FENCE_TTL_MINUTES):
                # Clear stale fence
                logger.info(f"Clearing stale fence for session {session_id} (age={age})")
                del _in_progress_fence[session_id]
            else:
                # Fence is active, cannot set
                return False
        
        # Set new fence
        _in_progress_fence[session_id] = (fence_count, now)
        return True


def _clear_fence(session_id: int) -> None:
    """Clear the fence for a session after processing completes.
    
    Mirrors plast-mem's finalize_job() fence clearing.
    """
    with _fence_lock:
        _in_progress_fence.pop(session_id, None)


def _is_fence_active(session_id: int) -> bool:
    """Check if a session has an active (non-stale) fence."""
    with _fence_lock:
        if session_id not in _in_progress_fence:
            return False
        
        _, existing_since = _in_progress_fence[session_id]
        age = datetime.now() - existing_since
        return age <= timedelta(minutes=FENCE_TTL_MINUTES)


def should_trigger_segmentation(session_id: int, current_count: int) -> bool:
    """Check if segmentation should trigger based on message count delta.
    
    Returns True if:
    - Delta from last_segmented_count >= WINDOW_BASE (periodic trigger)
    - OR current_count >= WINDOW_MAX (force trigger)
    - AND no active fence exists (prevents concurrent jobs)
    - AND enough time has passed since last segmentation (time gap)
    """
    from app.database import get_pipeline_state
    
    # Check fence first (like plast-mem's check())
    if _is_fence_active(session_id):
        logger.debug(f"Segmentation skipped for session {session_id}: fence active")
        return False
    
    # Get last segmented count from persisted state
    state = get_pipeline_state(session_id)
    last_count = state.get("last_segmented_count", 0)
    last_segmented_at = state.get("last_segmented_at")
    
    # Calculate delta
    delta = current_count - last_count
    
    # Not enough new messages
    if delta < WINDOW_BASE:
        logger.debug(f"Segmentation skipped: delta={delta} < WINDOW_BASE={WINDOW_BASE}")
        return False
    
    # Check time gap (minimum TIME_GAP_MINUTES since last segmentation)
    if last_segmented_at:
        try:
            from datetime import datetime
            last_dt = datetime.fromisoformat(last_segmented_at)
            age = datetime.now() - last_dt
            if age < timedelta(minutes=TIME_GAP_MINUTES):
                logger.debug(f"Segmentation skipped: time gap {age} < {TIME_GAP_MINUTES}min")
                return False
        except (ValueError, TypeError):
            pass  # Invalid timestamp, proceed
    
    # Force trigger at WINDOW_MAX (overrides time check)
    if current_count >= WINDOW_MAX:
        logger.info(f"Force trigger: current_count={current_count} >= WINDOW_MAX={WINDOW_MAX}")
        return True
    
    # Periodic trigger: delta >= WINDOW_BASE
    logger.info(f"Trigger: delta={delta} >= WINDOW_BASE={WINDOW_BASE}")
    return True


def mark_segmentation_done(session_id: int, count: int) -> None:
    """Mark that segmentation completed for this session at this count.
    
    Persists last_segmented_count and last_segmented_at to session's memory_json.
    Called AFTER processing completes (not before).
    """
    from app.database import update_pipeline_state
    
    update_pipeline_state(session_id, {
        "last_segmented_count": count,
        "last_segmented_at": datetime.now().isoformat(),
    })
    logger.info(f"Marked segmentation done: session={session_id}, count={count}")


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


# ── Episode creation with PCL trigger ──────────────────────────────────────────

FLASHBULB_THRESHOLD = 0.85
BASE_STABILITY = 24.0  # Aligned with FSRS default (24 hours)


def create_episode_and_pcl(
    session_id: int,
    messages: list[dict],
    segment: dict,
) -> Optional[int]:
    """Create an episode from a segment and trigger PCL pipeline.
    
    Returns episode ID or None on failure.
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
    
    # Embed the summary
    embedding = None
    try:
        embedding = embed_text(summary)
    except Exception as e:
        logger.warning(f"Embedding failed: {e}")
    
    # Calculate importance and stability based on surprise
    importance = 0.5 + surprise * 0.3
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
    
    logger.info(f"Created episode {episode_id}: {title}")
    
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
    from app.database import get_session_messages
    from app.memory.db_memory import get_facts_by_session, FACT_TYPE_DYNAMIC
    
    logger.info(f"Starting for session {session_id}, count={message_count}")
    
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
        
        if len(unsegmented) < MIN_MESSAGES:
            logger.debug(f"Only {len(unsegmented)} unsegmented msgs, skipping")
            return {"segments": 0, "episodes": 0, "pcl_runs": 0}
        
        # Batch segment
        batch_result = batch_segment(unsegmented)
        if not batch_result:
            logger.debug("No segments from batch LLM")
            return {"segments": 0, "episodes": 0, "pcl_runs": 0}
        
        logger.info(f"Batch segmentation: {len(batch_result)} segments")
        
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
        
        # Mark done
        mark_segmentation_done(session_id, message_count)
        
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
                from app.database import Database
                session_memory = Database.get_session_memory(session_to_process)
                count = session_memory.get("message_count", 0) if session_memory else 0
                
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
    
    Flow (aligned with plast-mem):
      1. Check if thresholds met (count/time)
      2. Try to set fence (CAS operation)
      3. If fence set, enqueue for background processing
      4. Fence is cleared AFTER processing completes in run_memory_pipeline
    """
    if should_trigger_segmentation(session_id, current_count):
        # Try to set fence - prevents concurrent jobs
        if not _try_set_fence(session_id, current_count):
            logger.debug(f"Could not set fence for session {session_id}")
            return False
        
        # Enqueue for background processing
        # mark_segmentation_done is called AFTER processing in run_memory_pipeline
        enqueue_memory_pipeline(session_id)
        return True
    return False
