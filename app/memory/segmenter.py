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


def _parse_timestamp(ts):
    """Parse a message timestamp string into a datetime."""
    try:
        return datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return None


def _get_unsegmented_messages(session_id):
    """Get messages that have not yet been assigned to a segment."""
    # Get all messages for session
    messages = get_session_messages(session_id, limit=10000)
    
    # Check for last segment in semantic_facts
    from app.memory.db_memory import get_facts_by_session
    segments = get_facts_by_session(session_id, fact_type=FACT_TYPE_DYNAMIC, limit=100)
    segments = [s for s in segments if s.get("metadata", {}).get("source_table") == "conversation_segments"]
    
    if segments:
        last_end_id = max(s.get("metadata", {}).get("end_message_id", 0) for s in segments)
    else:
        last_end_id = 0
    
    # Filter messages after last segment
    return [
        m for m in messages
        if m.get("id", 0) > last_end_id and m.get("role") in ("user", "assistant")
    ]


def _detect_boundaries(messages):
    """Split messages into segment groups based on rules.

    Rules:
    - Max 20 messages per segment
    - Time gap > 15 minutes
    """
    if not messages:
        return []

    segments = []
    current_group = []

    for msg in messages:
        if current_group:
            prev_ts = _parse_timestamp(current_group[-1].get('timestamp'))
            curr_ts = _parse_timestamp(msg.get('timestamp'))
            if prev_ts and curr_ts:
                gap = (curr_ts - prev_ts).total_seconds() / 60.0
                if gap >= TIME_GAP_MINUTES:
                    segments.append(current_group)
                    current_group = []

            if len(current_group) >= MAX_MESSAGES_PER_SEGMENT:
                segments.append(current_group)
                current_group = []

        current_group.append(msg)

    # Always flush the final group — no minimum threshold.
    # Segments with 1 message are better than silent data loss.
    if current_group:
        segments.append(current_group)

    return segments


def _create_segment(session_id, group, precomputed_summary=None):
    """Create a conversation segment from a message group.

    Args:
        session_id: session this segment belongs to
        group: list of message dicts
        precomputed_summary: optional LLM summary from prior extraction pass.
            If None, a trivial placeholder is stored.
    """
    if not group:
        return None

    start_id = group[0].get('id')
    end_id = group[-1].get('id')

    summary = precomputed_summary

    embedding = None
    if summary:
        try:
            from app.memory.embedder import embed_text
            embedding = embed_text(summary)
        except Exception as e:
            print(f"[segmenter] Embedding skipped: {e}")

    save_fact(
        session_id=session_id,
        content=summary or "",
        embedding=embedding,
        fact_type=FACT_TYPE_DYNAMIC,
        metadata={
            "start_message_id": start_id,
            "end_message_id": end_id,
            "importance": 0.5,
            "source_table": "conversation_segments",
            "session_id": session_id,
        },
    )

    return summary


def segment_session(session_id):
    """Segment unsegmented messages in a session.

    Returns:
        int: number of segments created.
    """
    messages = _get_unsegmented_messages(session_id)
    if not messages:
        return 0

    groups = _detect_boundaries(messages)
    count = 0
    for group in groups:
        try:
            if len(group) >= MIN_MESSAGES_PER_SEGMENT:
                _create_segment(session_id, group, precomputed_summary=None)
                count += 1
        except Exception as e:
            print(f"[WARNING] Segmentation failed for group: {e}")

    return count