import json
import re

SCHEMA = {
    "type": "function",
    "function": {
        "name": "memory_sql",
        "description": "Execute a SQL query against the conversation database to recall past messages, events, or facts. Only SELECT and UPDATE are allowed.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The SQL query to execute (SELECT or UPDATE only)"
                }
            },
            "required": ["query"]
        }
    }
}

# Destructive operations that are always blocked
_BLOCKED_KEYWORDS = [
    "INSERT",
    "DELETE",
    "DROP",
    "TRUNCATE",
    "ALTER TABLE",
    "CREATE TABLE",
    "PRAGMA WRITABLE_SCHEMA",
    "VACUUM INTO",
]

_BLOCKED_RE = re.compile(
    r'\b(?:' + '|'.join(re.escape(kw) for kw in _BLOCKED_KEYWORDS) + r')\b',
    re.IGNORECASE,
)


def _validate_query(query):
    """Return an error string if the query is not allowed, else None."""
    stripped = query.strip().rstrip(';').strip()
    upper = stripped.upper()

    if _BLOCKED_RE.search(upper):
        return "Blocked: only SELECT and UPDATE queries are allowed."

    if not (upper.startswith("SELECT") or upper.startswith("UPDATE")):
        return "Blocked: only SELECT and UPDATE queries are allowed."

    return None


def _inject_role_filter(query):
    """Ensure queries on the messages table exclude memory_tool rows."""
    if re.search(r'\bmessages\b', query, re.IGNORECASE):
        if not re.search(r"role\s*!=\s*'memory_tool'", query, re.IGNORECASE):
            if re.search(r'\bWHERE\b', query, re.IGNORECASE):
                query = re.sub(
                    r'\bWHERE\b',
                    "WHERE role != 'memory_tool' AND",
                    query,
                    count=1,
                    flags=re.IGNORECASE,
                )
            else:
                query = re.sub(
                    r'\b(FROM\s+messages)\b',
                    r"\1 WHERE role != 'memory_tool'",
                    query,
                    count=1,
                    flags=re.IGNORECASE,
                )
    return query


def execute(arguments, **kwargs):
    query = arguments.get("query", "").strip()
    if not query:
        return json.dumps({"error": "No query provided"})

    error = _validate_query(query)
    if error:
        return json.dumps({"error": error})

    query = _inject_role_filter(query)

    try:
        from database import get_engine
        from sqlalchemy import text

        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text(query))

            if query.strip().upper().startswith("SELECT"):
                rows = [dict(row._mapping) for row in result.fetchall()]
                return json.dumps({"rows": rows, "count": len(rows)}, default=str)
            else:
                conn.commit()
                return json.dumps({"affected_rows": result.rowcount})

    except Exception as e:
        return json.dumps({"error": f"SQL execution failed: {str(e)}"})
