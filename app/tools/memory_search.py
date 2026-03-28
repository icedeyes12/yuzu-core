# FILE: app/tools/memory_search.py
# DESCRIPTION: Query structured memory - semantic, episodic, and temporal

from app.database import Database
from app.memory.retrieval import retrieve_memory, format_memory
from app.tools.registry import build_markdown_contract


def execute(arguments, **kwargs):
    session_id = kwargs.get("session_id")
    profile = Database.get_profile() or {}
    partner_name = profile.get("partner_name", "Yuzu")

    query = arguments.get("query", "") or ""
    full_command = f"/memory_search {query}" if query else "/memory_search"

    if not session_id:
        return build_markdown_contract(
            "memory_search_tools",
            full_command,
            ["Error: session_id required"],
            partner_name,
        )

    try:
        memory_bundle = retrieve_memory(session_id=session_id, query=query)
    except Exception as e:
        print(f"[memory_search] Retrieval failed: {e}")
        return build_markdown_contract(
            "memory_search_tools",
            full_command,
            [f"Error: retrieval failed: {e}"],
            partner_name,
        )

    formatted = format_memory(memory_bundle)

    if not formatted.strip():
        return build_markdown_contract(
            "memory_search_tools",
            full_command,
            ["No memory results found for this query."],
            partner_name,
        )

    return build_markdown_contract(
        "memory_search_tools",
        full_command,
        [formatted],
        partner_name,
    )
