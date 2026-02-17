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


def _has_temporal_cues(query):
    query_lower = query.lower()
    return any(cue in query_lower for cue in TEMPORAL_CUES)


def _search_raw_messages(session_id, query, limit=20):
    """Search raw messages for contextual/temporal queries."""
    from database import Database
    
    chat_history = Database.get_chat_history(session_id=session_id, limit=1000, recent=True)
    
    if not chat_history:
        return []

    query_lower = query.lower()
    keywords = [w for w in query_lower.split() if len(w) > 2 and w not in TEMPORAL_CUES]
    
    scored_messages = []
    for msg in chat_history:
        content = msg.get('content', '')
        content_lower = content.lower()
        
        score = 0
        for kw in keywords:
            if kw in content_lower:
                score += 1
        
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

    # Step 2: Raw message search (if structured insufficient or temporal cues present)
    structured_count = (
        len(result["structured"]["semantic"])
        + len(result["structured"]["episodic"])
        + len(result["structured"]["segments"])
    )
    
    if structured_count < 3 or _has_temporal_cues(query):
        try:
            result["raw_messages"] = _search_raw_messages(session_id, query)
        except Exception as e:
            print(f"[memory_search] Raw message search failed: {e}")

    return json.dumps(result, default=str)
