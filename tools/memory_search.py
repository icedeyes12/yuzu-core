import json
import re
from datetime import datetime, timedelta


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
    query_lower = query.lower()
    for name, num in MONTH_NAMES.items():
        if name in query_lower:
            return num
    return None


def _has_temporal_cues(query):
    query_lower = query.lower()
    return any(cue in query_lower for cue in TEMPORAL_CUES)


def _detect_time_window(query):
    now = datetime.now()
    query_lower = query.lower()

    month = _detect_month(query)
    if month is not None:
        year = now.year
        if month > now.month:
            year -= 1
        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month + 1, 1)
        return start, end

    for cue, calc in RELATIVE_CUES.items():
        if cue in query_lower:
            return calc(now)

    return None


def _parse_timestamp(ts):
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
    from database import get_db_session, Message

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


def execute(arguments, **kwargs):
    from database import Database
    from tools.registry import build_markdown_contract

    query = arguments.get("query", "")
    session_id = kwargs.get("session_id")

    profile = Database.get_profile() or {}
    partner_name = profile.get("partner_name", "Yuzu")
    full_command = f"/memory_search {query}"

    if not session_id:
        return build_markdown_contract(
            "memory_search_tools", full_command,
            ["Error: session_id required"],
            partner_name,
        )

    lines = []

    # Step 1: Embedding-based semantic retrieval (pass query for similarity search)
    try:
        from memory.retrieval import retrieve_memory, format_memory
        memory_bundle = retrieve_memory(session_id, query=query)
        semantic = memory_bundle.get("semantic", [])
        episodic = memory_bundle.get("episodic", [])
        segments = memory_bundle.get("segments", [])

        if semantic:
            lines.append("--- Semantic Memories (by relevance) ---")
            for item in semantic:
                lines.append(
                    f"- [{item['score']:.2f}] {item['entity']} {item['relation']} {item['target']}"
                )
        if episodic:
            lines.append("--- Episodic Memories ---")
            for item in episodic:
                summary = item.get('summary', '')[:150]
                lines.append(f"- [{item['score']:.2f}] {summary}")
        if segments:
            lines.append("--- Conversation Segments ---")
            for item in segments:
                summary = item.get('summary', '')[:150]
                lines.append(f"- [{item['score']:.2f}] {summary}")
    except Exception as e:
        print(f"[memory_search] Embedding retrieval failed: {e}")

    # Step 2: Temporal window query — direct DB scan
    time_window = _detect_time_window(query)
    if time_window:
        start, end = time_window
        try:
            temporal_msgs = _search_temporal_messages(session_id, start, end)
            if temporal_msgs:
                lines.append(f"--- Messages ({start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}) ---")
                for msg in temporal_msgs:
                    lines.append(f"[{msg['timestamp']}] {msg['role']}: {msg['content']}")
        except Exception as e:
            print(f"[memory_search] Temporal scan failed: {e}")

    if not lines:
        lines.append("No memory results found")

    return build_markdown_contract("memory_search_tools", full_command, lines, partner_name)
