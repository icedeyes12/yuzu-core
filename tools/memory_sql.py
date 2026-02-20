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
    from database import Database
    from tools.registry import build_markdown_contract

    query = arguments.get("query", "").strip()
    profile = Database.get_profile() or {}
    partner_name = profile.get("partner_name", "Yuzu")

    if not query:
        return build_markdown_contract(
            "memory_sql_tools", "/memory_sql", ["Error: No query provided"], partner_name
        )

    full_command = f"/memory_sql {query}"

    error = _validate_query(query)
    if error:
        return build_markdown_contract(
            "memory_sql_tools", full_command, [f"Warning: {error}"], partner_name
        )

    query = _inject_role_filter(query)

    try:
        from database import get_engine
        from sqlalchemy import text

        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text(query))

            if query.strip().upper().startswith("SELECT"):
                rows = [dict(row._mapping) for row in result.fetchall()]
                lines = [f"Rows returned: {len(rows)}"]
                for row in rows:
                    lines.append(str(row))
                return build_markdown_contract("memory_sql_tools", full_command, lines, partner_name)
            else:
                conn.commit()
                lines = [f"Affected rows: {result.rowcount}"]
                return build_markdown_contract("memory_sql_tools", full_command, lines, partner_name)

    except Exception as e:
        return build_markdown_contract(
            "memory_sql_tools", full_command,
            [f"Error: SQL execution failed: {str(e)}"],
            partner_name,
        )
