from tools import web_search, weather, memory_search, image_generate, image_analyze, http_request
from tools import memory_sql

# Tool name → tool role used for DB storage
TOOL_ROLE_MAP = {
    "weather": "weather_tools",
    "web_search": "web_search_tools",
    "memory_sql": "memory_sql_tools",
    "memory_search": "memory_search_tools",
    "image_generate": "image_tools",
    "imagine": "image_tools",
    "image_analyze": "image_analyze_tools",
    "request": "request_tools",
}

_TOOLS = {
    "web_search": web_search,
    "weather": weather,
    "memory_search": memory_search,
    "memory_sql": memory_sql,
    "image_generate": image_generate,
    "image_analyze": image_analyze,
    "request": http_request,
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


def get_tool_schemas():
    """Return list of tool schemas in OpenRouter format."""
    return [mod.SCHEMA for mod in _TOOLS.values()]


def execute_tool(tool_name, arguments, session_id=None):
    """Dispatch a tool call and return the result string."""
    if tool_name not in _TOOLS:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    module = _TOOLS[tool_name]
    try:
        result = module.execute(arguments, session_id=session_id)
        return result
    except Exception as e:
        print(f"[tool_error] {tool_name}: {e}")
        return json.dumps({"error": f"Tool {tool_name} failed: {str(e)}"})
