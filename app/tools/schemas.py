from __future__ import annotations
# FILE: app/tools/schemas.py
# DESCRIPTION: Standard tool definition schema for function calling.
# All tools MUST expose a TOOL_DEFINITION and implement execute(arguments, session_id=None).


from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolParam:
    """A single parameter for a tool's execute() function."""

    name: str
    description: str
    type: str = "string"  # string | number | boolean | object | array
    required: bool = True
    default: Any = None
    enum: list[str] | None = None


@dataclass
class ToolDefinition:
    """Complete definition of a callable tool.

    This object is the single source of truth for:
    - The LLM's tools[] array (serialized to function-calling schema)
    - Dispatcher routing (tool_name → module)
    - Role categorization for DB storage
    - Terminal/non-terminal classification for second LLM pass
    """

    name: str  # unique, matches module name, e.g. "image_generate"
    description: str  # human-readable; LLM uses this to decide when to call
    role: str  # DB storage role, e.g. "image_tools", "request_tools"
    parameters: list[ToolParam] = field(default_factory=list)
    is_terminal: bool = False  # if True, skip second LLM pass on success

    # Internal fields (not serialized to LLM schema)
    needs_session: bool = False  # if True, dispatcher injects session_id from context

    def to_llm_schema(self) -> dict:
        """Serialize to OpenAI function-calling schema format."""
        properties = {}
        required = []

        for p in self.parameters:
            prop = {"type": p.type, "description": p.description}
            if p.enum:
                prop["enum"] = p.enum
            if not p.required and p.default is not None:
                prop["default"] = p.default
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


# --------------------------------------------------------------------
# Tool result standard
# --------------------------------------------------------------------
# Every tool's execute() MUST return this shape:
#
#   {"ok": True,  "data": {...}, "markdown": "<tools>...</tools>"}
#   {"ok": False, "error": "...", "markdown": "<tools>...</tools>"}
#
# markdown is the rendered output stored in DB and shown in UI.
# --------------------------------------------------------------------


def build_tool_contract(
    tool_def: ToolDefinition,
    full_command: str,
    output_lines: list[str],
    partner_name: str = "Yuzu",
) -> str:
    """Build the unified markdown contract for tool output.

    Returns a ``<tools>`` block — the ONLY format stored in DB
    and rendered by the frontend.
    """
    quoted = []
    raw = []
    in_code_fence = False

    for line in output_lines:
        if line.strip() == "```":
            in_code_fence = not in_code_fence
            raw.append(line)
        elif in_code_fence:
            raw.append(line)
        elif line.startswith("<img ") or line.startswith("<video "):
            raw.append(line)
        else:
            quoted.append(line)

    formatted_output = "\n".join(quoted)
    if raw:
        formatted_output += "\n\n" + "\n".join(raw)

    return f"<tools>\n🔧 {tool_def.role}\n\n{formatted_output}\n\n</tools>"


def ok_result(
    data: dict,
    tool_def: ToolDefinition,
    full_command: str,
    partner_name: str = "Yuzu",
) -> dict:
    """Construct a successful tool result."""
    return {
        "ok": True,
        "data": data,
        "markdown": build_tool_contract(
            tool_def, full_command, _flatten_lines(data), partner_name
        ),
    }


def error_result(
    message: str,
    tool_def: ToolDefinition,
    full_command: str,
    partner_name: str = "Yuzu",
) -> dict:
    """Construct an error tool result."""
    return {
        "ok": False,
        "error": message,
        "markdown": build_tool_contract(
            tool_def, full_command, [f"Error: {message}"], partner_name
        ),
    }


# Language hints for common file extensions
LANG_HINTS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".xml": "xml",
    ".lua": "lua",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".r": "r",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hs": "haskell",
    ".clj": "clojure",
    ".vim": "vim",
    ".dockerfile": "dockerfile",
    ".makefile": "makefile",
}


def _flatten_lines(data: dict) -> list[str]:
    """Flatten a result dict into displayable lines."""
    lines = []
    file_ext = data.get("file_ext", "")

    for key, value in data.items():
        if key == "file_ext":
            # Skip, already extracted
            continue
        elif isinstance(value, str) and value.startswith("<"):
            lines.append(value)
        elif key == "content" and isinstance(value, str) and "\n" in value:
            # Add newline after "content:" label
            lines.append(f"{key}:")
            lines.append("")

            # Check if markdown file - don't fence, render directly
            if file_ext == ".md":
                lines.append(value)
            else:
                # Wrap in code fence with language hint
                lang = LANG_HINTS.get(file_ext, "")
                lines.append(f"```{lang}")
                lines.append(value)
                lines.append("```")
        else:
            lines.append(f"{key}: {value}")
    return lines
