from __future__ import annotations
# FILE: app/tools/registry.py
# DESCRIPTION: Central tool registry — single source of truth for dispatch.
#
# Architecture:
#   - TOOL_DEFINITIONS: dict[name -> ToolDefinition] — lazily populated
#   - _TOOL_MODULES: dict[name -> module] — lazy-loaded on first dispatch
#   - execute_tool(): calls tool.execute() and returns structured result
#   - get_tool_definitions(): returns list for LLM tools[] array
#   - get_tools_by_role(): filters tools by role
#
# How to register a new tool:
#   1. Add TOOL_DEFINITION to the tool's module (e.g. image_generate.py)
#   2. Import it in _collect_definitions() below (at the bottom of this file)
#   3. The tool must have execute(arguments, session_id=None) -> dict


from typing import Optional
import logging
import asyncio

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


def is_terminal_tool(tool_name: str) -> bool:
    """Check if a tool is terminal (skips second LLM pass on success)."""
    _collect_definitions()
    tool_def = _TOOL_DEFINITIONS.get(tool_name)
    if tool_def:
        return tool_def.is_terminal
    return False


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
    from app.tools.schemas import error_result, build_tool_contract, ToolDefinition

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
            await _get_partner_name_async(),
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
                await _get_partner_name_async(),
            ),
        }

    except Exception as e:
        logger.info(f"[tool_error] {tool_name}: {e}")
        return error_result(
            "Tool execution failed. Please try again later.",
            tool_def,
            f"/{tool_name}",
            await _get_partner_name_async(),
        )


async def _get_partner_name_async() -> str:
    """Get partner name from profile for error messages (async)."""
    try:
        from app.db import Database

        profile = await Database.get_profile_async() or {}
        return profile.get("partner_name", "Yuzu")
    except Exception:
        return "Yuzu"


def _get_partner_name() -> str:
    """Legacy sync wrapper."""
    return asyncio.run(_get_partner_name_async())
