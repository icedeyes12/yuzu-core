import json
import re
from datetime import datetime, timedelta


SCHEMA = {
    "type": "function",
    "function": {
        "name": "memory_search",
        "description": "Search past memories and conversation history. Use when the user asks about past events, personal history, or things not in recent messages.",
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


def _search_raw_messages(session_id, query, limit=20):
    """Search raw messages for contextual/temporal queries."""
    from database import Database
    
    chat_history = Database.get_chat_history(session_id=session_id, limit=2000, recent=True)
    
    if not chat_history:
        return []

    query_lower = query.lower()
    all_cue_words = set(TEMPORAL_CUES) | set(MONTH_NAMES.keys())
    keywords = [w for w in query_lower.split() if len(w) > 2 and w not in all_cue_words]
    
    # Detect month filter
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
        
        # Boost messages matching target month
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
        "raw_messages": []
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

    # Step 2: Always search raw messages for completeness
    try:
        result["raw_messages"] = _search_raw_messages(session_id, query)
    except Exception as e:
        print(f"[memory_search] Raw message search failed: {e}")

    return json.dumps(result, default=str)
