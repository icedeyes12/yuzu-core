import json
import re
from datetime import datetime, timedelta


SCHEMA = {
    "type": "function",
    "function": {
        "name": "memory_search",
        "description": "Search past memories and conversation history. Use when the user asks about past events, personal history, specific dates, time-based recollection, or things not in recent messages.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for in memory"
                }
            },
            "required": ["query"]
        }
    }
}

TEMPORAL_CUES = [
    "kemarin", "minggu lalu", "waktu itu", "terakhir", "pas aku",
    "last time", "yesterday", "last week", "before", "remember when",
    "dulu", "tadi", "bulan lalu", "tahun lalu", "pernah",
    "last month", "last year", "earlier", "previously", "ago"
]

MONTH_NAMES = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4,
    "mei": 5, "juni": 6, "juli": 7, "agustus": 8,
    "september": 9, "oktober": 10, "november": 11, "desember": 12,
    "january": 1, "february": 2, "march": 3, "may": 5,
    "june": 6, "july": 7, "august": 8, "october": 10, "december": 12,
}

RELATIVE_CUES = {
    "kemarin": lambda now: (now - timedelta(days=1), now),
    "yesterday": lambda now: (now - timedelta(days=1), now),
    "tadi": lambda now: (now.replace(hour=0, minute=0, second=0), now),
    "minggu lalu": lambda now: (now - timedelta(weeks=1), now),
    "last week": lambda now: (now - timedelta(weeks=1), now),
    "bulan lalu": lambda now: (now - timedelta(days=30), now),
    "last month": lambda now: (now - timedelta(days=30), now),
    "tahun lalu": lambda now: (now - timedelta(days=365), now),
    "last year": lambda now: (now - timedelta(days=365), now),
}


def _detect_month(query):
    """Detect month reference in query, return month number or None."""
    query_lower = query.lower()
    for name, num in MONTH_NAMES.items():
        if name in query_lower:
            return num
    return None


def _has_temporal_cues(query):
    query_lower = query.lower()
    return any(cue in query_lower for cue in TEMPORAL_CUES)


def _detect_time_window(query):
    """Detect a time window from the query. Returns (start, end) or None."""
    now = datetime.now()
    query_lower = query.lower()

    # Check specific month reference first
    month = _detect_month(query)
    if month is not None:
        # Determine the year: if month is in the future, use last year
        year = now.year
        if month > now.month:
            year -= 1
        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month + 1, 1)
        return start, end

    # Check relative cues
    for cue, calc in RELATIVE_CUES.items():
        if cue in query_lower:
            return calc(now)

    return None


def _parse_timestamp(ts):
    """Parse timestamp string to datetime, return None on failure."""
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(str(ts), fmt)
        except (ValueError, TypeError):
            continue
    return None


def _search_temporal_messages(session_id, start, end, limit=200):
    """Query messages table directly for a specific time window."""
    from database import Database, get_db_session, Message

    results = []
    try:
        start_str = start.strftime('%Y-%m-%d %H:%M:%S')
        end_str = end.strftime('%Y-%m-%d %H:%M:%S')

        with get_db_session() as session:
            messages = (
                session.query(Message)
                .filter(
                    Message.session_id == session_id,
                    Message.role.in_(['user', 'assistant']),
                    Message.timestamp >= start_str,
                    Message.timestamp <= end_str,
                )
                .order_by(Message.timestamp.asc())
                .limit(limit)
                .all()
            )
            for msg in messages:
                content = msg.content
                if msg.content_encrypted:
                    try:
                        from encryption import encryptor
                        content = encryptor.decrypt(content)
                    except Exception:
                        content = "[ENCRYPTED]"
                results.append({
                    "timestamp": msg.timestamp,
                    "role": msg.role,
                    "content": content[:500],
                })
    except Exception as e:
        print(f"[memory_search] Temporal query failed: {e}")

    return results


def _search_raw_messages(session_id, query, limit=20):
    """Search raw messages for contextual/keyword queries."""
    from database import Database
    
    chat_history = Database.get_chat_history(session_id=session_id, limit=2000, recent=True)
    
    if not chat_history:
        return []

    query_lower = query.lower()
    all_cue_words = set(TEMPORAL_CUES) | set(MONTH_NAMES.keys())
    keywords = [w for w in query_lower.split() if len(w) > 2 and w not in all_cue_words]
    
    target_month = _detect_month(query)
    
    scored_messages = []
    for msg in chat_history:
        content = msg.get('content', '')
        if not content:
            continue
        content_lower = content.lower()
        
        score = 0
        for kw in keywords:
            if kw in content_lower:
                score += 1
        
        if target_month:
            ts = _parse_timestamp(msg.get('timestamp'))
            if ts and ts.month == target_month:
                score += 2
        
        if score > 0:
            scored_messages.append({
                "timestamp": msg.get('timestamp', ''),
                "content": content[:300],
                "score": score
            })

    scored_messages.sort(key=lambda x: x['score'], reverse=True)
    return scored_messages[:limit]


def execute(arguments, **kwargs):
    query = arguments.get("query", "")
    session_id = kwargs.get("session_id")

    if not query or not session_id:
        return json.dumps({"error": "query and session_id required"})

    result = {
        "structured": {"semantic": [], "episodic": [], "segments": []},
        "raw_messages": [],
    }

    # Step 1: Structured memory retrieval
    try:
        from memory.retrieval import retrieve_memory
        memory_bundle = retrieve_memory(session_id)
        result["structured"]["semantic"] = memory_bundle.get("semantic", [])
        result["structured"]["episodic"] = memory_bundle.get("episodic", [])
        result["structured"]["segments"] = memory_bundle.get("segments", [])
    except Exception as e:
        print(f"[memory_search] Structured retrieval failed: {e}")

    # Step 2: Temporal window query — direct DB scan
    time_window = _detect_time_window(query)
    if time_window:
        start, end = time_window
        try:
            temporal_msgs = _search_temporal_messages(session_id, start, end)
            if temporal_msgs:
                result["raw_messages"] = temporal_msgs
                result["time_window"] = {
                    "start": start.strftime('%Y-%m-%d %H:%M:%S'),
                    "end": end.strftime('%Y-%m-%d %H:%M:%S'),
                }
                return json.dumps(result, default=str)
        except Exception as e:
            print(f"[memory_search] Temporal scan failed: {e}")

    # Step 3: Keyword-based raw message search
    try:
        result["raw_messages"] = _search_raw_messages(session_id, query)
    except Exception as e:
        print(f"[memory_search] Raw message search failed: {e}")

    return json.dumps(result, default=str)
