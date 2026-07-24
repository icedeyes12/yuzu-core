from __future__ import annotations

import logging

from app.db import Database
from app.tools.schemas import ToolDefinition, ToolParam, error_result, ok_result

logger = logging.getLogger(__name__)

TOOL_DEFINITION = ToolDefinition(
    name="memory_search",
    description="Search graph memory and return relevant inferred knowledge.",
    role="memory_search_tools",
    parameters=[
        ToolParam(
            name="query",
            description="Natural language search query.",
            type="string",
            required=False,
            default="",
        )
    ],
    needs_session=True,
)


async def execute(arguments, **kwargs):
    session_id = kwargs.get("session_id")
    user_id = kwargs.get("user_id")
    profile = await Database.get_profile(user_id) or {}
    partner_name = profile.get("partner_name", "Yuzu")
    query = str(arguments.get("query", "") or "").strip()
    if not session_id or not user_id:
        return error_result(
            "session_id and user_id required",
            TOOL_DEFINITION,
            "/memory_search",
            partner_name,
        )

    try:
        from app.memory.retrieval import retrieve_memory_async

        bundle = await retrieve_memory_async(
            session_id=session_id, query=query, user_id=user_id
        )
    except Exception as exc:
        logger.warning("graph memory search failed: %s", exc)
        return error_result(
            "Retrieval failed. Please try again later.",
            TOOL_DEFINITION,
            "/memory_search",
            partner_name,
        )

    results = bundle.get("static", []) + bundle.get("dynamic", [])
    return ok_result(
        {"results": results, "count": len(results)},
        TOOL_DEFINITION,
        f"/memory_search {query}".strip(),
        partner_name,
    )
