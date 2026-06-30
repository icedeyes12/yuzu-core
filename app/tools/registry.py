"""Central tool registry — single dispatch point for all tool execution."""

from __future__ import annotations


from typing import Any, Optional
import logging
import asyncio
import time

from app.tools.schemas import (
    ToolDefinition,
    ToolCallEvent,
    ToolResultEvent,
    StreamToolEvent,
    make_tool_call_event,
    make_tool_result_event,
    new_turn_id,
    error_result,
    build_tool_contract,
)

logger = logging.getLogger(__name__)

# Lazy-load tool modules on first dispatch
_TOOL_MODULES: dict = {}


# Lazily populated on first get_tool_definitions() call
_TOOL_DEFINITIONS: dict = {}
_DEFINITIONS_INITIALIZED = False


def _load_tool_module(tool_name: str):
    """Lazy-import a tool module by name."""
    if tool_name not in _TOOL_MODULES:
        if tool_name == "image_generate":
            from app.tools import image_generate

            _TOOL_MODULES[tool_name] = image_generate
        elif tool_name == "image_edit":
            from app.tools import image_edit

            _TOOL_MODULES[tool_name] = image_edit
        elif tool_name == "imagine":
            # Alias for image_generate
            from app.tools import image_generate

            _TOOL_MODULES[tool_name] = image_generate
        elif tool_name == "request" or tool_name == "http_request":
            from app.tools import http_request

            _TOOL_MODULES[tool_name] = http_request
        elif tool_name == "memory_store":
            from app.tools import memory_store

            _TOOL_MODULES[tool_name] = memory_store
        elif tool_name == "memory_search":
            from app.tools import memory_search

            _TOOL_MODULES[tool_name] = memory_search
        elif tool_name == "multimodal":
            from app.tools import multimodal

            _TOOL_MODULES[tool_name] = multimodal
        # File system tools
        elif tool_name in ("read", "write", "ls", "mkdir", "rm"):
            from app.tools import fs_operations

            _TOOL_MODULES[tool_name] = fs_operations
        elif tool_name == "bash":
            from app.tools import shell_exec

            _TOOL_MODULES[tool_name] = shell_exec
        elif tool_name == "python":
            from app.tools import python_exec

            _TOOL_MODULES[tool_name] = python_exec
        elif tool_name == "sql":
            from app.tools import db_query

            _TOOL_MODULES[tool_name] = db_query
        elif tool_name == "ask_rei":
            from app.tools import ask_rei

            _TOOL_MODULES[tool_name] = ask_rei
        else:
            return None
    return _TOOL_MODULES.get(tool_name)


def _collect_definitions():
    """Lazily import and register all tool definitions."""
    global _TOOL_DEFINITIONS, _DEFINITIONS_INITIALIZED
    if _DEFINITIONS_INITIALIZED:
        return

    try:
        from app.tools import image_generate

        _TOOL_DEFINITIONS["image_generate"] = image_generate.TOOL_DEFINITION
        _TOOL_DEFINITIONS["imagine"] = image_generate.TOOL_DEFINITION  # alias
    except Exception as e:
        logger.info(f"[registry] Failed to load image_generate definition: {e}")

    try:
        from app.tools import image_edit

        _TOOL_DEFINITIONS["image_edit"] = image_edit.TOOL_DEFINITION
    except Exception as e:
        logger.info(f"[registry] Failed to load image_edit definition: {e}")

    try:
        from app.tools import http_request

        _TOOL_DEFINITIONS["http_request"] = http_request.TOOL_DEFINITION
        _TOOL_DEFINITIONS["request"] = http_request.TOOL_DEFINITION  # alias
    except Exception as e:
        logger.info(f"[registry] Failed to load http_request definition: {e}")

    try:
        from app.tools import memory_store

        _TOOL_DEFINITIONS["memory_store"] = memory_store.TOOL_DEFINITION
    except Exception as e:
        logger.info(f"[registry] Failed to load memory_store definition: {e}")

    try:
        from app.tools import memory_search

        _TOOL_DEFINITIONS["memory_search"] = memory_search.TOOL_DEFINITION
    except Exception as e:
        logger.info(f"[registry] Failed to load memory_search definition: {e}")

    # File system tools
    try:
        from app.tools import fs_operations

        for name in ["read", "write", "ls", "mkdir", "rm"]:
            _TOOL_DEFINITIONS[name] = getattr(fs_operations, f"TOOL_{name.upper()}")
        _TOOL_MODULES["fs_operations"] = fs_operations
    except Exception as e:
        logger.info(f"[registry] Failed to load fs_operations definitions: {e}")

    # Shell execution tool
    try:
        from app.tools import shell_exec

        for name, defn in shell_exec.TOOL_DEFINITION.items():
            _TOOL_DEFINITIONS[name] = defn
        _TOOL_MODULES["shell_exec"] = shell_exec
    except Exception as e:
        logger.info(f"[registry] Failed to load shell_exec definition: {e}")

    # Python execution tool
    try:
        from app.tools import python_exec

        _TOOL_DEFINITIONS["python"] = python_exec.TOOL_DEFINITION
        _TOOL_MODULES["python_exec"] = python_exec
    except Exception as e:
        logger.info(f"[registry] Failed to load python_exec definition: {e}")

    # SQL query tool
    try:
        from app.tools import db_query

        _TOOL_DEFINITIONS["sql"] = db_query.TOOL_DEFINITION
        _TOOL_MODULES["db_query"] = db_query
    except Exception as e:
        logger.info(f"[registry] Failed to load db_query definition: {e}")

    # Ask Rei tool
    try:
        from app.tools import ask_rei

        _TOOL_DEFINITIONS["ask_rei"] = ask_rei.TOOL_DEFINITION
        _TOOL_MODULES["ask_rei"] = ask_rei
    except Exception as e:
        logger.info(f"[registry] Failed to load ask_rei definition: {e}")

    _DEFINITIONS_INITIALIZED = True


# --------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------


def get_tool_definitions() -> list:
    """Return all tool definitions for LLM tools[] array."""
    _collect_definitions()
    return list(_TOOL_DEFINITIONS.values())


def get_tool_definition(name: str):
    """Return a single tool definition by name, or None."""
    _collect_definitions()
    return _TOOL_DEFINITIONS.get(name)


def get_tools_by_role(role: str) -> list:
    """Return all tools that match the given role prefix."""
    _collect_definitions()
    return [t for t in _TOOL_DEFINITIONS.values() if t.role == role]


def get_tool_role(tool_name: str) -> str:
    """Get the storage role for a tool name (for DB)."""
    _collect_definitions()
    tool_def = _TOOL_DEFINITIONS.get(tool_name)
    if tool_def:
        return tool_def.role
    return f"{tool_name}_tools"


# --------------------------------------------------------------------
# Legacy support
# --------------------------------------------------------------------


# --------------------------------------------------------------------
# Main dispatch
# --------------------------------------------------------------------


async def execute_tool(
    tool_name: str,
    arguments: dict,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> dict:
    """Dispatch a tool call and return a structured result dict (async).

    This is the SINGLE source of truth for tool dispatch.
    All tool execution MUST go through this function.

    Returns:
        {"ok": True,  "data": {...}, "markdown": "..."}
        {"ok": False, "error": "...", "markdown": "..."}
    """
    _collect_definitions()

    tool_def = _TOOL_DEFINITIONS.get(tool_name)
    if not tool_def:
        return {
            "ok": False,
            "error": f"Unknown tool: {tool_name}",
            "markdown": build_tool_contract(
                ToolDefinition(name="", description="", role=f"{tool_name}_tools"),
                f"/{tool_name}",
                [
                    "Error: Unknown tool. Available tools: "
                    + ", ".join(_TOOL_DEFINITIONS.keys())
                ],
                "Yuzu",
            ),
        }

    # Inject session_id if tool expects it
    if tool_def.needs_session and "session_id" not in arguments:
        arguments = {**arguments, "session_id": session_id}

    module = _load_tool_module(tool_name)
    if not module:
        return error_result(
            f"Tool module unavailable: {tool_name}",
            tool_def,
            f"/{tool_name}",
            await _get_partner_name_async(user_id),
        )

    try:
        if asyncio.iscoroutinefunction(module.execute):
            result = await module.execute(
                arguments, session_id=session_id, tool_name=tool_name, user_id=user_id
            )
        else:
            # Fallback for sync tools - run in thread to avoid blocking loop
            result = await asyncio.to_thread(
                module.execute,
                arguments,
                session_id=session_id,
                tool_name=tool_name,
                user_id=user_id,
            )

        # New-style structured result (already a dict with ok/data/markdown)
        if isinstance(result, dict) and "ok" in result:
            return result

        # Old-style: tools still return markdown directly — wrap it
        if isinstance(result, str) and result.strip().startswith("<details>"):
            return {
                "ok": True,
                "data": {},
                "markdown": result,
            }

        # Fallback: treat as raw text
        return {
            "ok": True,
            "data": {"result": result},
            "markdown": build_tool_contract(
                ToolDefinition(name="", description="", role=tool_def.role),
                f"/{tool_name}",
                [str(result)],
                await _get_partner_name_async(user_id),
            ),
        }

    except Exception as e:
        logger.info(f"[tool_error] {tool_name}: {e}")
        return error_result(
            "Tool execution failed. Please try again later.",
            tool_def,
            f"/{tool_name}",
            await _get_partner_name_async(user_id),
        )


async def _get_partner_name_async(user_id: str | None = None) -> str:
    """Get partner name from profile for error messages (async)."""
    try:
        from app.db import Database

        profile = await Database.get_profile(user_id) if user_id else {}
        return profile.get("partner_name", "Yuzu")
    except Exception:
        return "Yuzu"


def _get_partner_name(user_id: str | None = None) -> str:
    """Legacy sync wrapper."""
    return asyncio.run(_get_partner_name_async(user_id))


# ---------------------------------------------------------------------------
# Canonical tool-event API (FC1 — native function calling contract)
# ---------------------------------------------------------------------------


def get_tool_schemas(*, only_native_fc: bool = False) -> list[dict[str, Any]]:
    """Return tool schemas for the LLM's ``tools[]`` array.

    This is the SINGLE source of truth for what tools the LLM sees.
    Every layer that needs tool definitions calls this — no more
    inferring tool shape from legacy command markup.

    Args:
        only_native_fc: If True, filter to tools that support native FC.
    """
    _collect_definitions()
    schemas: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tool in _TOOL_DEFINITIONS.values():
        if only_native_fc and not tool.supports_native_fc:
            continue
        schema = tool.to_llm_schema()
        name = schema.get("function", {}).get("name", "")
        if name and name not in seen:
            seen.add(name)
            schemas.append(schema)
    return schemas


def get_tool_capabilities(tool_name: str) -> dict[str, bool]:
    """Return capability flags for a single tool."""
    _collect_definitions()
    tool_def = _TOOL_DEFINITIONS.get(tool_name)
    if not tool_def:
        return {"supports_native_fc": False, "supports_streaming_fc": False}
    return {
        "supports_native_fc": tool_def.supports_native_fc,
        "supports_streaming_fc": tool_def.supports_streaming_fc,
    }


def get_all_capabilities() -> dict[str, dict[str, bool]]:
    """Return capability map for all registered tools."""
    _collect_definitions()
    return {
        name: {
            "supports_native_fc": t.supports_native_fc,
            "supports_streaming_fc": t.supports_streaming_fc,
        }
        for name, t in _TOOL_DEFINITIONS.items()
    }


async def execute_tool_event(
    call_event: ToolCallEvent,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> ToolResultEvent:
    """Execute a ToolCallEvent and return a ToolResultEvent.

    This is the canonical execution entry point for native FC.
    The legacy ``execute_tool()`` still works but delegates here.
    """
    started = int(time.time() * 1000)
    result = await execute_tool(
        call_event.name,
        call_event.arguments,
        session_id=session_id,
        user_id=user_id,
    )
    elapsed = int(time.time() * 1000) - started

    return make_tool_result_event(
        call_id=call_event.id,
        name=call_event.name,
        ok=result.get("ok", False),
        data=result.get("data", {}),
        markdown=result.get("markdown", ""),
        error=result.get("error", ""),
        turn_id=call_event.turn_id,
        tool_ms=elapsed,
    )
