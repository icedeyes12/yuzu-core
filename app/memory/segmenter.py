# FILE: app/memory/segmenter.py
# DESCRIPTION: Conversation segmentation engine - uses db_memory for storage

from __future__ import annotations

__all__ = ["segment_session", "_detect_boundaries", "_create_segment"]

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


def _llm_detect_boundary(messages: list, prev_summary: str | None = None) -> dict:
    """LLM dual-channel boundary detection — topic shift + surprise.

    Returns:
        dict: {should_segment: bool, surprise_level: float, topic_shift: bool}
    """
    if len(messages) < 3:
        return {"should_segment": False, "surprise_level": 0.0, "topic_shift": False}

    try:
        ai_manager = __import__("app").get_ai_manager()
    except Exception:
        return {"should_segment": False, "surprise_level": 0.0, "topic_shift": False}

    # Build a compact representation of this message group
    conversation = "\n".join(
        f"{'User' if m.get('role') == 'user' else 'AI'}: {m.get('content', '')}"
        for m in messages[-6:]  # last 6 messages max
        if m.get("role") in ("user", "assistant")
    )

    prev_context = f"\n\nPrevious segment summary: {prev_summary}" if prev_summary else ""

    system_prompt = """You are a conversation boundary detector. Analyze the last few messages and respond with ONLY a JSON object, no markdown, no explanation.

Respond with this exact format:
{"should_segment": true/false, "surprise_level": 0.0-1.0, "topic_shift": true/false}

Rules:
- should_segment = true if there is a meaningful topic change OR a surprising event
- surprise_level = how emotionally or contextually surprising this segment is (0.0=normal, 1.0=shocking)
- topic_shift = true if the conversation moved to a substantially different topic

Emotional reactions alone (happy/sad/angry) without topic shift should NOT trigger segmentation unless surprise_level >= 0.7."""

    user_prompt = f"""Analyze this recent conversation:{prev_context}\n\n{conversation}\n\nRespond with ONLY the JSON object."""

    try:
        import json
        response = ai_manager._internal_llm_call(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=15,
            max_tokens=100,
        )
        if not response:
            return {"should_segment": False, "surprise_level": 0.0, "topic_shift": False}

        # Parse JSON, handle truncation
        try:
            result = json.loads(response)
        except json.JSONDecodeError:
            for i in range(len(response), 0, -1):
                try:
                    result = json.loads(response[:i])
                    if isinstance(result, dict):
                        break
                except json.JSONDecodeError:
                    continue
            else:
                return {"should_segment": False, "surprise_level": 0.0, "topic_shift": False}

        return {
            "should_segment": bool(result.get("should_segment", False)),
            "surprise_level": float(result.get("surprise_level", 0.0)),
            "topic_shift": bool(result.get("topic_shift", False)),
        }
    except Exception as e:
        print(f"[WARNING] LLM boundary detection failed: {e}")
        return {"should_segment": False, "surprise_level": 0.0, "topic_shift": False}


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


def segment_session(session_id: int, prev_summary: str | None = None) -> int:
    """Segment unsegmented messages in a session.

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