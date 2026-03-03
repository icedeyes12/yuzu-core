from tools import image_generate, http_request, memory_search, memory_sql, image_analyze
import json

# Tool name → tool role used for DB storage
# Terminal tools (like image_tools) do NOT trigger a second LLM pass on success
# NOTE: web_search and weather are handled via /request (DuckDuckGo/Open-Meteo APIs)
TOOL_ROLE_MAP = {
    "image_generate": "image_tools",
    "imagine": "image_tools",
    "request": "request_tools",
    "memory_search": "memory_search_tools",
    "memory_sql": "memory_sql_tools",
    "image_analyze": "image_analyze_tools",
}

# Tools that are TERMINAL — no second LLM pass after successful execution
# NOTE: All tools now trigger second pass for deterministic two-pass architecture
TERMINAL_TOOL_ROLES = set()

_TOOLS = {
    "image_generate": image_generate,
    "request": http_request,
    "memory_search": memory_search,
    "memory_sql": memory_sql,
    "image_analyze": image_analyze,
}

def build_markdown_contract(tool_role, full_command, output_lines, partner_name):
    """Build the unified markdown contract for tool output.

    Returns a ``<details>`` block that is the *only* format stored in DB
    and rendered by the frontend.
    """
    executor = partner_name or "Yuzu"
    formatted_output = "\n".join(f"> {line}" for line in output_lines)

    return (
        f"<details>\n"
        f"<summary>🔧 {tool_role}</summary>\n"
        f"\n"
        f"```bash\n"
        f"{executor}$ {full_command}\n"
        f"```\n"
        f"\n"
        f"{formatted_output}\n"
        f"\n"
        f"</details>"
    )


def execute_tool(tool_name, arguments, session_id=None):
    """Dispatch a tool call and return the result string.
    
    This is the SINGLE source of truth for tool dispatch.
    All tool execution MUST go through this function.
    """
    if tool_name not in _TOOLS:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    module = _TOOLS[tool_name]
    try:
        result = module.execute(arguments, session_id=session_id)
        return result
    except Exception as e:
        print(f"[tool_error] {tool_name}: {e}")
        # Return structured tool output, not raw exception
        profile = {}
        try:
            from database import Database
            profile = Database.get_profile() or {}
        except Exception:
            pass
        partner_name = profile.get("partner_name", "Yuzu")
        return build_markdown_contract(
            TOOL_ROLE_MAP.get(tool_name, f"{tool_name}_tools"),
            f"/{tool_name}",
            [f"Error: Tool execution failed: {str(e)}"],
            partner_name,
        )


def is_terminal_tool(tool_role):
    """Check if a tool role is terminal (no second LLM pass after success)."""
    return tool_role in TERMINAL_TOOL_ROLES


def get_tool_role(tool_name):
    """Get the tool role for a given tool name."""
    return TOOL_ROLE_MAP.get(tool_name, f"{tool_name}_tools")
