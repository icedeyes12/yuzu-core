# FILE: app/tools/db_query.py
# DESCRIPTION: SQL query execution tool for PostgreSQL database access
#              Provides read-only by default with --write flag for mutations

from __future__ import annotations

import os
import subprocess
import re

from app.logging_config import get_logger
from app.tools.schemas import ToolDefinition, error_result, ok_result, ToolParam

log = get_logger(__name__)

# ------------------------------------------------------------
# Constants
# ------------------------------------------------------------

TOOL_NAME = "sql"
TOOL_SQL = "sql"

# SQL keywords that modify data (require --write flag)
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

# Maximum rows to return
MAX_ROWS = 100

# Query timeout in seconds
QUERY_TIMEOUT = 30

# ------------------------------------------------------------
# Tool Definition
# ------------------------------------------------------------

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
    is_terminal=False,
)

# ------------------------------------------------------------
# Database Connection
# ------------------------------------------------------------


def _get_db_connection_params() -> dict[str, str]:
    """Get database connection parameters from environment."""
    return {
        "host": os.environ.get("PGHOST", os.environ.get("PG_HOST", "localhost")),
        "port": os.environ.get("PGPORT", os.environ.get("PG_PORT", "5432")),
        "dbname": os.environ.get("PGDATABASE", os.environ.get("PG_DBNAME", "yuzu")),
        "user": os.environ.get("PGUSER", os.environ.get("PG_USER", "postgres")),
        "password": os.environ.get("PGPASSWORD", os.environ.get("PG_PASSWORD", "")),
    }


def _build_psql_command(query: str, write_mode: bool = False) -> list[str]:
    """Build psql command with connection params."""
    params = _get_db_connection_params()

    cmd = [
        "psql",
        "-h",
        params["host"],
        "-p",
        params["port"],
        "-U",
        params["user"],
        "-d",
        params["dbname"],
        "-t",  # Tuple-only output
        "-A",  # Unaligned output
        "-F,",  # Field separator
        "-X",  # Skip .psqlrc and suppress config noise
        "-c",
        query,
    ]

    # Set password via environment
    if params["password"]:
        os.environ["PGPASSWORD"] = params["password"]

    return cmd


# ------------------------------------------------------------
# Query Validation
# ------------------------------------------------------------


def _is_write_query(query: str) -> bool:
    """Check if query modifies data."""
    # Remove comments and normalize
    clean = re.sub(r"--.*$", "", query, flags=re.MULTILINE)
    clean = re.sub(r"/\*.*?\*/", "", clean, flags=re.DOTALL)
    clean = clean.strip().upper()

    # Check first keyword
    first_word = clean.split()[0] if clean.split() else ""
    return first_word in WRITE_KEYWORDS


def _validate_query(query: str, write_mode: bool) -> tuple[bool, str]:
    """Validate query safety."""
    if not query or not query.strip():
        return False, "Empty query"

    # Check for write operations without --write flag
    if _is_write_query(query) and not write_mode:
        return (
            False,
            f"Write operation detected. Use --write flag: /sql --write {query[:50]}...",
        )

    # Block dangerous patterns
    dangerous = ["DROP DATABASE", "DROP SCHEMA public", "TRUNCATE TABLE pg_"]
    for pattern in dangerous:
        if pattern in query.upper():
            return False, f"Blocked dangerous pattern: {pattern}"

    return True, ""


# ------------------------------------------------------------
# Output Formatting
# ------------------------------------------------------------


def _format_table(
    rows: list[dict], columns: list[str], max_rows: int = MAX_ROWS
) -> str:
    """Format query results as markdown table."""
    if not rows:
        return "No results"

    # Truncate if needed
    truncated = len(rows) > max_rows
    display_rows = rows[:max_rows]

    # Calculate column widths
    widths = {col: len(col) for col in columns}
    for row in display_rows:
        for col in columns:
            val = str(row.get(col, ""))
            widths[col] = max(widths[col], min(len(val), 50))  # Cap at 50 chars

    # Build header
    header = "| " + " | ".join(col.ljust(widths[col]) for col in columns) + " |"
    separator = "|" + "|".join("-" * (widths[col] + 2) for col in columns) + "|"

    # Build rows
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


def _parse_psql_output(
    output: str, columns: list[str] | None = None
) -> tuple[list[dict], list[str]]:
    """Parse psql CSV output into rows."""
    if not output or not output.strip():
        return [], columns or []

    lines = output.strip().split("\n")
    rows = []

    for line in lines:
        if not line.strip():
            continue
        values = line.split(",")
        if columns:
            row = {}
            for i, col in enumerate(columns):
                row[col] = values[i] if i < len(values) else None
            rows.append(row)
        else:
            rows.append({"value": v} for v in values)

    return rows, columns or ["value"]


# ------------------------------------------------------------
# Main Execution
# ------------------------------------------------------------


def execute(
    arguments: dict, session_id: str | None = None, tool_name: str = "sql"
) -> dict:
    """Execute SQL query and return structured result.

    Args:
        arguments: {"query": "SQL query string, optionally prefixed with --write"}
        session_id: Optional session ID for context

    Returns:
        Result dict with ok, data, markdown fields
    """
    query_arg = arguments.get("query", "").strip()

    if not query_arg:
        return error_result(
            "Empty query. Provide a SQL query.",
            TOOL_DEFINITION,
            "/sql",
            _get_partner_name(),
        )

    # Check for --write flag
    write_mode = query_arg.startswith("--write")
    if write_mode:
        query = query_arg[7:].strip()  # Remove "--write "
    else:
        query = query_arg

    # Handle code block format
    if query.startswith("```"):
        lines = query.split("\n")
        # Remove first and last line (code fence)
        query = "\n".join(lines[1:-1] if len(lines) > 2 else lines[1:])

    # Validate query
    valid, error_msg = _validate_query(query, write_mode)
    if not valid:
        return error_result(
            error_msg,
            TOOL_DEFINITION,
            query[:100],
        )

    # Execute query
    try:
        cmd = _build_psql_command(query, write_mode)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=QUERY_TIMEOUT,
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        exit_code = result.returncode

        # Parse output
        if exit_code != 0:
            return error_result(
                f"Query failed: {stderr}",
                TOOL_DEFINITION,
                query[:100],
            )

        # For SELECT queries, try to format as table
        rows = []
        columns = []

        if stdout:
            # Simple parsing - each line is a row
            lines = [line for line in stdout.split("\n") if line.strip()]
            if lines:
                # Try to detect columns from first row
                first_values = lines[0].split(",")
                if len(first_values) > 1:
                    columns = [f"col{i}" for i in range(len(first_values))]
                    for line in lines:
                        values = line.split(",")
                        rows.append({col: val for col, val in zip(columns, values)})
                else:
                    # Single column
                    columns = ["result"]
                    rows = [{"result": line} for line in lines]

        # Build output
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
            _get_partner_name(),
        )

    except subprocess.TimeoutExpired:
        return error_result(
            f"Query timed out after {QUERY_TIMEOUT}s",
            TOOL_DEFINITION,
            query[:100],
        )
    except FileNotFoundError:
        return error_result(
            "psql not found. Please install postgresql-client.",
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


def _get_partner_name() -> str:
    """Get partner name from profile for tool output."""
    try:
        from app.db.db_queries import get_active_profile

        profile = get_active_profile()
        return profile.get("partner_name", "Yuzu")
    except Exception:
        return "Yuzu"
