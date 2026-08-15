from __future__ import annotations

import re
from typing import Any

from psycopg import Error as PgError
from psycopg.errors import QueryCanceled

from app.core.logging_config import get_logger
from app.db.connection import PgSession
from app.tools.schemas import ToolDefinition, ToolParam, error_result, ok_result

log = get_logger(__name__)

TOOL_NAME = "sql"
TOOL_SQL = "sql"

WRITE_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "CREATE",
    "ALTER",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
}

MAX_ROWS = 100

QUERY_TIMEOUT = 30

TOOL_DEFINITION = ToolDefinition(
    name=TOOL_NAME,
    description="Execute SQL queries on the PostgreSQL database. READ-ONLY by default. Use --write flag for INSERT/UPDATE/DELETE.",
    role="sql_tools",
    parameters=[
        ToolParam(
            name="query",
            type="string",
            description="SQL query to execute. Use --write prefix for mutations.",
            required=True,
        ),
    ],
)


def _is_write_query(query: str) -> bool:
    clean = re.sub(r"--.*$", "", query, flags=re.MULTILINE)
    clean = re.sub(r"/\*.*?\*/", "", clean, flags=re.DOTALL)
    clean = clean.strip().upper()

    first_word = clean.split()[0] if clean.split() else ""
    return first_word in WRITE_KEYWORDS


def _validate_query(query: str, write_mode: bool) -> tuple[bool, str]:
    if not query or not query.strip():
        return False, "Empty query"

    if _is_write_query(query) and not write_mode:
        return (
            False,
            f"Write operation detected. Use --write flag: /sql --write {query[:50]}...",
        )

    dangerous = ["DROP DATABASE", "DROP SCHEMA public", "TRUNCATE TABLE pg_"]
    for pattern in dangerous:
        if pattern in query.upper():
            return False, f"Blocked dangerous pattern: {pattern}"

    return True, ""


def _format_table(
    rows: list[dict[str, Any]], columns: list[str], max_rows: int = MAX_ROWS
) -> str:
    if not rows:
        return "No results"

    truncated = len(rows) > max_rows
    display_rows = rows[:max_rows]

    widths = {col: len(col) for col in columns}
    for row in display_rows:
        for col in columns:
            val = str(row.get(col, ""))
            widths[col] = max(widths[col], min(len(val), 50))

    header = "| " + " | ".join(col.ljust(widths[col]) for col in columns) + " |"
    separator = "|" + "|".join("-" * (widths[col] + 2) for col in columns) + "|"

    lines = [header, separator]
    for row in display_rows:
        cells = []
        for col in columns:
            val = str(row.get(col, ""))
            if len(val) > 50:
                val = val[:47] + "..."
            cells.append(val.ljust(widths[col]))
        lines.append("| " + " | ".join(cells) + " |")

    if truncated:
        lines.append(f"\n*Showing {max_rows} of {len(rows)} rows*")

    return "\n".join(lines)


def _run_query(query: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Execute *query* on the shared connection pool.

    Returns (rows, columns). Values are stringified so the result stays
    JSON-serializable for tool events; writes without a result set yield a
    single "result" row carrying the command tag (e.g. "INSERT 0 1").
    """
    with PgSession() as session:
        session.execute(f"SET LOCAL statement_timeout = {QUERY_TIMEOUT * 1000}")
        with session.conn.cursor() as cur:
            cur.execute(query)
            status = cur.statusmessage
            if cur.description is None:
                rows = [{"result": status}] if status else []
                return rows, ["result"]
            columns = [d.name for d in cur.description]
            rows = [
                {col: ("" if v is None else str(v)) for col, v in row.items()}
                for row in cur.fetchall()
            ]
            return rows, columns


def execute(
    arguments: dict[str, Any], session_id: str | None = None, tool_name: str = "sql"
) -> dict[str, Any]:
    query_arg = arguments.get("query", "").strip()

    if not query_arg:
        return error_result(
            "Empty query. Provide a SQL query.",
            TOOL_DEFINITION,
            "/sql",
            "Yuzu",
        )

    write_mode = query_arg.startswith("--write")
    if write_mode:
        query = query_arg[7:].strip()
    else:
        query = query_arg

    if query.startswith("```"):
        lines = query.split("\n")
        query = "\n".join(lines[1:-1] if len(lines) > 2 else lines[1:])

    valid, error_msg = _validate_query(query, write_mode)
    if not valid:
        return error_result(
            error_msg,
            TOOL_DEFINITION,
            query[:100],
        )

    try:
        rows, columns = _run_query(query)

        table_md = _format_table(rows, columns)

        result_data = {
            "query": query,
            "write_mode": write_mode,
            "rows": rows,
            "row_count": len(rows),
            "columns": columns,
            "output": table_md,
        }

        return ok_result(
            result_data,
            TOOL_DEFINITION,
            f"/sql {'--write ' if write_mode else ''}{query[:50]}{'...' if len(query) > 50 else ''}",
            "Yuzu",
        )

    except QueryCanceled:
        return error_result(
            f"Query timed out after {QUERY_TIMEOUT}s",
            TOOL_DEFINITION,
            query[:100],
        )
    except PgError as e:
        return error_result(
            f"Query failed: {e}",
            TOOL_DEFINITION,
            query[:100],
        )
    except Exception as e:
        log.error(f"[sql] Execution error: {e}")
        return error_result(
            f"Execution error: {str(e)}",
            TOOL_DEFINITION,
            query[:100],
        )
