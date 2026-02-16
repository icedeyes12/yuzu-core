# [FILE: memory/segmenter.py]
# [DESCRIPTION: Conversation segmentation engine]

from datetime import datetime
from database import (
    get_db_session, Message, ConversationSegment
)
from memory.extractor import generate_episodic_summary


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
        # Find the last segmented message id
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
            # Check time gap
            prev_ts = _parse_timestamp(current_group[-1].get('timestamp'))
            curr_ts = _parse_timestamp(msg.get('timestamp'))
            if prev_ts and curr_ts:
                gap = (curr_ts - prev_ts).total_seconds() / 60.0
                if gap >= TIME_GAP_MINUTES:
                    segments.append(current_group)
                    current_group = []

            # Check max size
            if len(current_group) >= MAX_MESSAGES_PER_SEGMENT:
                segments.append(current_group)
                current_group = []

        current_group.append(msg)

    # Don't create segments from groups that are too small (less than 5)
    # unless there are no other segments
    if current_group and len(current_group) >= 5:
        segments.append(current_group)

    return segments


def _create_segment(session_id, group):
    """Create a conversation segment from a message group."""
    if not group:
        return

    start_id = group[0]['id']
    end_id = group[-1]['id']

    summary = generate_episodic_summary(group)

    with get_db_session() as session:
        segment = ConversationSegment(
            session_id=session_id,
            start_message_id=start_id,
            end_message_id=end_id,
            summary=summary,
            importance=0.5,
        )
        session.add(segment)
        session.commit()


def segment_session(session_id):
    """Segment unsegmented messages in a session.

    Returns the number of segments created.
    """
    messages = _get_unsegmented_messages(session_id)
    if not messages:
        return 0

    groups = _detect_boundaries(messages)
    count = 0
    for group in groups:
        try:
            _create_segment(session_id, group)
            count += 1
        except Exception:
            pass  # Don't crash on segmentation errors

    return count
