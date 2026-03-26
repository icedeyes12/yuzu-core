# FILE: app/memory/segmenter.py
# DESCRIPTION: Conversation segmentation engine

from __future__ import annotations

__all__ = ["segment_session", "_detect_boundaries", "_create_segment"]

from datetime import datetime
from app.database import (
    get_db_session, Message, ConversationSegment
)
from app.memory.extractor import generate_episodic_summary


# Segmentation limits
MAX_MESSAGES_PER_SEGMENT = 20
TIME_GAP_MINUTES = 15


def _parse_timestamp(ts):
    """Parse a message timestamp string into a datetime."""
    try:
        return datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return None


def _get_unsegmented_messages(session_id):
    """Get messages that have not yet been assigned to a segment."""
    with get_db_session() as session:
        last_segment = session.query(ConversationSegment).filter(
            ConversationSegment.session_id == session_id
        ).order_by(ConversationSegment.end_message_id.desc()).first()

        last_id = last_segment.end_message_id if last_segment else 0

        messages = session.query(Message).filter(
            Message.session_id == session_id,
            Message.id > last_id,
            Message.role.in_(['user', 'assistant']),
        ).order_by(Message.id.asc()).all()

        return [
            {
                'id': m.id,
                'role': m.role,
                'content': m.content,
                'timestamp': m.timestamp,
            }
            for m in messages
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


def _create_segment(session_id, group):
    """Create a conversation segment from a message group.
    
    Returns the generated summary string so callers can reuse it
    without calling the LLM again (avoids double summarization).
    """
    if not group:
        return None

    start_id = group[0]['id']
    end_id = group[-1]['id']

    # Generate summary ONCE — caller reuses this, no second LLM call
    summary = generate_episodic_summary(group)

    embedding_blob = None
    try:
        from app.memory.embedder import embed_text, vec_to_blob
        vec = embed_text(summary or "")
        if vec is not None:
            embedding_blob = vec_to_blob(vec)
    except Exception as e:
        print(f"[segmenter] Embedding skipped: {e}")

    with get_db_session() as session:
        segment = ConversationSegment(
            session_id=session_id,
            start_message_id=start_id,
            end_message_id=end_id,
            summary=summary,
            importance=0.5,
            embedding=embedding_blob,
        )
        session.add(segment)
        session.commit()

    return summary


def segment_session(session_id):
    """Segment unsegmented messages in a session.

    Returns:
        dict with 'segments_created' count and 'summaries' list.
        Summaries are reused by process_messages_for_memory to avoid
        double LLM summarization.
    """
    messages = _get_unsegmented_messages(session_id)
    if not messages:
        return {'segments_created': 0, 'summaries': []}

    groups = _detect_boundaries(messages)
    summaries = []
    count = 0
    for group in groups:
        try:
            summary = _create_segment(session_id, group)
            if summary:
                summaries.append(summary)
            count += 1
        except Exception as e:
            print(f"[WARNING] Segmentation failed for group: {e}")

    return {'segments_created': count, 'summaries': summaries}
