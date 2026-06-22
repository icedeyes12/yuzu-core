from __future__ import annotations
# FILE: app/tools/memory_search.py
# DESCRIPTION: Query structured memory - semantic, episodic, and temporal


import logging
from app.tools.schemas import ToolDefinition, ToolParam, ok_result, error_result

logger = logging.getLogger(__name__)

TOOL_DEFINITION = ToolDefinition(
    name="memory_search",
    description="Search the user's stored memories and facts across all categories. "
    "Returns relevant memories ranked by relevance.",
    role="memory_search_tools",
    parameters=[
        ToolParam(
            name="query",
            description="Natural language search query to find relevant memories",
            type="string",
            required=False,
            default="",
        ),
    ],
    needs_session=True,
    is_terminal=True,
)


async def execute(arguments, **kwargs):
    session_id = kwargs.get("session_id")
    user_id = kwargs.get("user_id")
    from app.db import Database
    from app.memory.retrieval import retrieve_memory_async, format_memory

    profile = await Database.get_profile_async(user_id) or {}
    partner_name = profile.get("partner_name", "Yuzu")

    query = arguments.get("query", "") or ""
    full_command = f"/memory_search {query}" if query else "/memory_search"

    if not session_id:
        return error_result(
            "session_id required",
            TOOL_DEFINITION,
            full_command,
            partner_name,
        )

    try:
        memory_bundle = await retrieve_memory_async(
            session_id=session_id, query=query, user_id=user_id
        )
    except Exception as e:
        logger.warning(f"[memory_search] Retrieval failed: {e}")
        return error_result(
            "Retrieval failed. Please try again later.",
            TOOL_DEFINITION,
            full_command,
            partner_name,
        )

    formatted = format_memory(memory_bundle)

    if not formatted.strip():
        return ok_result(
            {"results": [], "count": 0},
            TOOL_DEFINITION,
            full_command,
            partner_name,
        )

    return ok_result(
        {"results": formatted, "count": 1},
        TOOL_DEFINITION,
        full_command,
        partner_name,
    )
