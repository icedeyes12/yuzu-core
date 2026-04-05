# FILE: app/memory/segmenter.py
# DESCRIPTION: Conversation segmentation engine - uses db_memory for storage

from __future__ import annotations

__all__ = ["segment_session", "segment_session_init", "_detect_boundaries", "_create_segment"]

from datetime import datetime
from app.db_pg_models import get_session_messages
from app.memory.db_memory import save_fact, FACT_TYPE_DYNAMIC


# Segmentation limits
MAX_MESSAGES_PER_SEGMENT = 20
MIN_MESSAGES_PER_SEGMENT = 5  # enforced on all segments except the final flush group
TIME_GAP_MINUTES = 15
# Surprise threshold for flashbulb memory boost
FLASHBULB_SURPRISE_THRESHOLD = 0.85


def _parse_timestamp(ts):
    """Parse a message timestamp string into a datetime."""
    try:
        return datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return None


def _get_unsegmented_messages(session_id: int) -> list[dict]:
    """Get messages that have not yet been assigned to a segment."""
    messages = get_session_messages(session_id, limit=10000)

    from app.memory.db_memory import get_facts_by_session
    segments = get_facts_by_session(session_id, fact_type=FACT_TYPE_DYNAMIC, limit=100)
    segments = [s for s in segments if s.get("metadata", {}).get("source_table") == "conversation_segments"]

    if segments:
        last_end_id = max(s.get("metadata", {}).get("end_message_id", 0) for s in segments)
    else:
        last_end_id = 0

    return [
        m for m in messages
        if m.get("id", 0) > last_end_id and m.get("role") in ("user", "assistant")
    ]


def _build_message_context(messages: list[dict], max_msgs: int = 6) -> str:
    """Build compact conversation string from message list."""
    return "\n".join(
        f"{'User' if m.get('role') == 'user' else 'AI'}: {m.get('content', '')}"
        for m in messages[-max_msgs:]
        if m.get("role") in ("user", "assistant")
    )


def _should_segment_fastpath(prev_group, current_group) -> bool:
    """Fast-path segmentation: True if time gap OR group size warrants a boundary.

    NO LLM calls — safe for session-init (no conversation context available).
    """
    if not prev_group or not current_group:
        return False

    prev_ts = _parse_timestamp(prev_group[-1].get('timestamp'))
    curr_ts = _parse_timestamp(current_group[0].get('timestamp'))

    # Rule 1: Time gap
    if prev_ts and curr_ts:
        gap_minutes = (curr_ts - prev_ts).total_seconds() / 60.0
        if gap_minutes >= TIME_GAP_MINUTES:
            return True

    # Rule 2: Size-based
    if len(prev_group) >= MAX_MESSAGES_PER_SEGMENT:
        return True

    return False


def _default_boundary_result() -> dict:
    """Default return when LLM boundary detection fails or has no context."""
    return {"should_segment": False, "surprise_level": 0.0, "topic_shift": False}


def _get_ai_manager():
    """Lazy-import to avoid circular imports."""
    from app import get_ai_manager
    return get_ai_manager()


def _llm_detect_boundary(current_group, prev_summary, surprise_boost=0.0):
    """LLM refinement channel — only used during active conversation, not init.

    Returns dict: {should_segment: bool, surprise_level: float, topic_shift: bool}
    """
    if not prev_summary or len(current_group) < 3:
        return _default_boundary_result()

    conversation = "\n".join(
        f"{'User' if m.get('role') == 'user' else 'AI'}: {m.get('content', '')}"
        for m in current_group
        if m.get("role") in ("user", "assistant")
    )

    system_prompt = """You are a conversation boundary detector.

Given the PREVIOUS segment summary and the CURRENT message group, decide if there is a meaningful conversation boundary.

Respond with ONLY a valid JSON object, no markdown, no explanation:
{"should_segment": true/false, "surprise_level": 0.0-1.0, "topic_shift": true/false, "reason": "brief reason"}

Consider:
- topic_shift: did the conversation topic change significantly?
- surprise_level: was there a significant emotional or informational shift?
- should_segment: is the boundary meaningful enough to start a new segment?"""

    user_prompt = f"Previous segment summary: {prev_summary}\n\nCurrent messages:\n{conversation[:1000]}"

    try:
        ai = _get_ai_manager()
        response = ai._internal_llm_call(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=15,
            max_tokens=100,
        )
        if not response:
            return _default_boundary_result()

        import json
        result = None
        for i in range(len(response), 0, -1):
            try:
                result = json.loads(response[:i])
                if isinstance(result, dict) and "should_segment" in result:
                    break
            except json.JSONDecodeError:
                continue

        if not isinstance(result, dict):
            return _default_boundary_result()

        return {
            "should_segment": bool(result.get("should_segment", False)),
            "surprise_level": float(result.get("surprise_level", 0.0)),
            "topic_shift": bool(result.get("topic_shift", False)),
        }

    except Exception as e:
        print(f"[segmenter] LLM boundary detection failed: {e}")
        return _default_boundary_result()


def _should_segment(messages: list, prev_summary: str | None = None) -> dict:
    """Dual-channel segmentation decision: time-gap rule OR LLM decision.

    Time-gap is the fast-path. LLM is the refinement channel.
    Returns the LLM result dict (with should_segment reflecting the OR decision).
    """
    if not messages or len(messages) < 2:
        return {"should_segment": False, "surprise_level": 0.0, "topic_shift": False}

    # Channel 1: Time-gap (fast-path — no LLM needed)
    prev_ts = _parse_timestamp(messages[-2].get("timestamp"))
    curr_ts = _parse_timestamp(messages[-1].get("timestamp"))
    if prev_ts and curr_ts:
        gap_minutes = (curr_ts - prev_ts).total_seconds() / 60.0
        if gap_minutes >= TIME_GAP_MINUTES:
            return {"should_segment": True, "surprise_level": 0.0, "topic_shift": True, "reason": "time_gap"}

    # Channel 2: LLM dual-channel detection
    llm_result = _llm_detect_boundary(messages, prev_summary)
    if llm_result.get("should_segment"):
        llm_result["reason"] = "llm"
        return llm_result

    return llm_result


def _create_segment(session_id: int, group: list, precomputed_summary: str | None = None,
                    surprise_level: float = 0.0):
    """Create a conversation segment from a message group.

    Args:
        session_id: session this segment belongs to
        group: list of message dicts
        precomputed_summary: optional LLM summary from prior extraction pass
        surprise_level: 0.0-1.0, used for flashbulb stability boost
    """
    if not group:
        return None

    start_id = group[0].get("id")
    end_id = group[-1].get("id")

    summary = precomputed_summary

    embedding = None
    if summary:
        try:
            from app.memory.embedder import embed_text
            embedding = embed_text(summary)
        except Exception as e:
            print(f"[segmenter] Embedding skipped: {e}")

    # Flashbulb stability boost: high-surprise episodes decay slower
    if surprise_level >= FLASHBULB_SURPRISE_THRESHOLD:
        base_importance = 0.5 + surprise_level * 0.4  # 0.85+ surprise → importance ~0.84
        stability_boost = 1.0 + surprise_level * 0.5  # boost stability multiplier
    else:
        base_importance = 0.5
        stability_boost = 1.0

    save_fact(
        session_id=session_id,
        content=summary or "",
        embedding=embedding,
        fact_type=FACT_TYPE_DYNAMIC,
        metadata={
            "start_message_id": start_id,
            "end_message_id": end_id,
            "importance": base_importance,
            "stability_boost": stability_boost,
            "surprise_level": surprise_level,
            "source_table": "conversation_segments",
            "session_id": session_id,
        },
    )

    return summary


def _detect_boundaries(messages: list[dict], prev_summary: str | None = None) -> list[list[dict]]:
    """Split messages into segment groups using dual-channel decision.

    Rules:
    - Time-gap >= 15 min → hard segment boundary (no LLM needed)
    - LLM dual-channel: should_segment OR topic_shift → segment
    - Max 20 messages per segment
    - Final group always flushed (no MIN threshold)
    """
    if not messages:
        return []

    segments = []
    current_group = []
    last_known_summary = prev_summary

    for i, msg in enumerate(messages):
        if current_group:
            # Check time-gap first (fast-path, no LLM)
            prev_ts = _parse_timestamp(current_group[-1].get("timestamp"))
            curr_ts = _parse_timestamp(msg.get("timestamp"))
            time_gap_boundary = False
            if prev_ts and curr_ts:
                gap_minutes = (curr_ts - prev_ts).total_seconds() / 60.0
                if gap_minutes >= TIME_GAP_MINUTES:
                    time_gap_boundary = True

            # Decide: time-gap OR LLM dual-channel
            should_close = time_gap_boundary

            if not should_close and len(current_group) >= MAX_MESSAGES_PER_SEGMENT:
                should_close = True

            if not should_close and len(current_group) >= 3:
                # Ask LLM only when there's enough context to judge
                prev_for_llm = last_known_summary
                llm_decision = _llm_detect_boundary(current_group, prev_for_llm)
                if llm_decision.get("should_segment") or llm_decision.get("topic_shift"):
                    should_close = True

            if should_close:
                segments.append(current_group)
                current_group = []

        current_group.append(msg)

    # Always flush final group — no minimum threshold
    if current_group:
        segments.append(current_group)

    return segments


def _detect_boundaries_fast(messages: list[dict]) -> list[list[dict]]:
    """Time-gap-only segmentation — NO LLM calls. Safe for session-init."""
    if not messages:
        return []

    segments = []
    current_group = []

    for msg in messages:
        if current_group:
            prev_ts = _parse_timestamp(current_group[-1].get("timestamp"))
            curr_ts = _parse_timestamp(msg.get("timestamp"))
            if prev_ts and curr_ts:
                gap_minutes = (curr_ts - prev_ts).total_seconds() / 60.0
                if gap_minutes >= TIME_GAP_MINUTES:
                    segments.append(current_group)
                    current_group = []

            if len(current_group) >= MAX_MESSAGES_PER_SEGMENT:
                segments.append(current_group)
                current_group = []

        current_group.append(msg)

    if current_group:
        segments.append(current_group)

    return segments


def segment_session_init(session_id: int) -> int:
    """Fast-path session initialization — time-gap segmentation only, NO LLM.

    Called from start_session to quickly chunk old messages without burning
    API credits on boundary detection that has no useful prior context.

    Returns:
        int: number of segments created.
    """
    messages = _get_unsegmented_messages(session_id)
    if not messages:
        return 0

    groups = _detect_boundaries_fast(messages)
    count = 0

    for group in groups:
        try:
            if len(group) < MIN_MESSAGES_PER_SEGMENT:
                continue
            _create_segment(session_id, group, precomputed_summary=None, surprise_level=0.0)
            count += 1
        except Exception as e:
            print(f"[WARNING] Fast segmentation failed for group: {e}")

    return count


def segment_session(session_id: int, prev_summary: str | None = None) -> int:
    """Segment unsegmented messages in a session.

    Uses time-gap rules AND LLM boundary detection (dual-channel).
    For session-init with no prior context, use segment_session_init() instead.

    Args:
        session_id: session to segment
        prev_summary: summary of the last created segment (for LLM context)

    Returns:
        int: number of segments created.
    """
    messages = _get_unsegmented_messages(session_id)
    if not messages:
        return 0

    groups = _detect_boundaries(messages, prev_summary=prev_summary)
    count = 0
    last_summary = prev_summary

    for group in groups:
        try:
            if len(group) < MIN_MESSAGES_PER_SEGMENT:
                continue

            # Use LLM to detect surprise level for this group
            llm_decision = _llm_detect_boundary(group, last_summary)
            surprise = llm_decision.get("surprise_level", 0.0)

            seg_summary = _create_segment(session_id, group, precomputed_summary=None, surprise_level=surprise)
            if seg_summary:
                last_summary = seg_summary

            count += 1
        except Exception as e:
            print(f"[WARNING] Segmentation failed for group: {e}")

    return count