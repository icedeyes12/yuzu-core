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


def execute_tool(tool_name: str, arguments: dict, session_id: Optional[str] = None) -> dict:
    """Dispatch a tool call and return a structured result dict.

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
                ["Error: Unknown tool. Available tools: " + ", ".join(_TOOL_DEFINITIONS.keys())],
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
            _get_partner_name(),
        )

    try:
        result = module.execute(arguments, session_id=session_id)

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
                _get_partner_name(),
            ),
        }

    except Exception as e:
        logger.info(f"[tool_error] {tool_name}: {e}")
        return error_result(
            "Tool execution failed. Please try again later.",
            tool_def,
            f"/{tool_name}",
            _get_partner_name(),
        )


def _get_partner_name() -> str:
    """Get partner name from profile for error messages."""
    try:
        from app.db_pg_models import get_profile
        profile = get_profile() or {}
        return profile.get("partner_name", "Yuzu")
    except Exception:
        return "Yuzu"
