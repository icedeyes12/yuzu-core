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

from __future__ import annotations

import logging
import threading
import time
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

# ── Background thread state ───────────────────────────────────────────────────

_pipeline_thread: threading.Thread | None = None
_pipeline_lock = threading.Lock()
_pending_sessions: set[int] = set()  # Sessions queued for processing


# ── Message counter tracking (per-session) ─────────────────────────────────────

_last_processed_count: dict[int, int] = {}  # session_id -> last processed count


def should_trigger_segmentation(session_id: int, current_count: int) -> bool:
    """Check if segmentation should trigger based on message count.
    
    Returns True if:
    - Count reaches WINDOW_MAX (force trigger)
    - Count reaches multiple of WINDOW_BASE (periodic trigger)
    """
    last_count = _last_processed_count.get(session_id, 0)
    delta = current_count - last_count
    
    # Force trigger at WINDOW_MAX
    if current_count >= WINDOW_MAX and delta >= WINDOW_MAX:
        return True
    
    # Periodic trigger every WINDOW_BASE
    if delta >= WINDOW_BASE:
        return True
    
    return False


def mark_segmentation_done(session_id: int, count: int) -> None:
    """Mark that segmentation completed for this session at this count."""
    _last_processed_count[session_id] = count


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


def batch_segment(messages: list[dict]) -> list[dict]:
    """Single LLM call to segment messages into episodes.
    
    Returns list of segment dicts:
        [{start_idx, end_idx, title, summary, surprise_level}, ...]
    """
    if len(messages) < MIN_MESSAGES:
        return []
    
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


# ── Episode creation with PCL trigger ──────────────────────────────────────────

SURPRISE_BOOST_FACTOR = 0.5
FLASHBULB_THRESHOLD = 0.85


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
    stability = 24.0 * (1 + SURPRISE_BOOST_FACTOR * surprise)
    
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
    from app.db_pg_models import get_session_messages
    
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
    
    Returns summary: {segments: n, episodes: n, pcl_runs: n}
    """
    from app.db_pg_models import get_session_messages
    from app.memory.db_memory import get_facts_by_session, FACT_TYPE_DYNAMIC
    
    logger.info(f"Starting for session {session_id}, count={message_count}")
    
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
    """
    if should_trigger_segmentation(session_id, current_count):
        enqueue_memory_pipeline(session_id)
        return True
    return False
