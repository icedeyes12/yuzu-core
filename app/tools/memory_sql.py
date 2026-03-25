# [FILE: app/tools/memory_sql.py]
# [DESCRIPTION: Direct SQL query tool for memory debugging]

from app.database import Database
from app.tools.registry import build_markdown_contract


def execute(arguments, **kwargs):
    session_id = kwargs.get("session_id")
    profile = Database.get_profile() or {}
    partner_name = profile.get("partner_name", "Yuzu")

    query = arguments.get("query", "").strip()
    full_command = f"/memory_sql {query}"

    if not session_id:
        return build_markdown_contract(
            "memory_sql_tools",
            full_command,
            ["Error: session_id required"],
            partner_name,
        )

    return build_markdown_contract(
        "memory_sql_tools",
        full_command,
        ["Direct SQL query tool — not yet implemented. Use /memory_search instead."],
        partner_name,
    )
