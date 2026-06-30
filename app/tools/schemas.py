from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Tool parameter & definition
# ---------------------------------------------------------------------------


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
    - Capability metadata for provider negotiation
    """

    name: str  # unique, matches module name, e.g. "image_generate"
    description: str  # human-readable; LLM uses this to decide when to call
    role: str  # DB storage role, e.g. "image_tools", "request_tools"
    parameters: list[ToolParam] = field(default_factory=list)

    # Internal fields (not serialized to LLM schema)
    needs_session: bool = False  # if True, dispatcher injects session_id from context

    # Capability metadata (used by provider layer for FC negotiation)
    supports_native_fc: bool = True  # tool is compatible with native function calling
    supports_streaming_fc: bool = True  # tool works in streaming FC mode

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


# ---------------------------------------------------------------------------
# Canonical tool-event envelope
#
# Every tool lifecycle moment is represented as one of these structured
# events.  Providers, orchestration, persistence, streaming, and UI all
# speak this same shape — no more inferring intent from text blocks.
# ---------------------------------------------------------------------------


@dataclass
class ToolCallEvent:
    """A single tool-call request emitted by the LLM.

    Attributes:
        id:       Opaque provider-assigned call ID (or generated if absent).
        name:     Tool name as the LLM invoked it.
        arguments: Parsed argument dict.
        turn_id:  Correlates all events belonging to one orchestrator turn.
    """

    id: str
    name: str
    arguments: dict[str, Any]
    turn_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": "tool_call",
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
            "turn_id": self.turn_id,
        }


@dataclass
class ToolResultEvent:
    """The result of executing a tool.

    Attributes:
        call_id:     Matches ToolCallEvent.id.
        name:        Tool name.
        ok:          True if execution succeeded.
        data:        Structured result data (for programmatic consumers).
        markdown:    Human-readable output (for presentation only).
        error:       Error message when ok=False.
        turn_id:     Correlates to the orchestrator turn.
        tool_ms:     Execution duration in milliseconds (optional, telemetry).
    """

    call_id: str
    name: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    markdown: str = ""
    error: str = ""
    turn_id: str = ""
    tool_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "event": "tool_result",
            "call_id": self.call_id,
            "name": self.name,
            "ok": self.ok,
            "data": self.data,
            "markdown": self.markdown,
            "turn_id": self.turn_id,
        }
        if self.error:
            d["error"] = self.error
        if self.tool_ms:
            d["tool_ms"] = self.tool_ms
        return d


@dataclass
class StreamToolEvent:
    """Wraps a tool event for SSE transport.

    The SSE envelope carries one of:
      - {"type": "token", "content": "..."}            (text delta)
      - {"type": "tool_call",  "data": {...}}           (ToolCallEvent.to_dict())
      - {"type": "tool_result", "data": {...}}           (ToolResultEvent.to_dict())
      - {"type": "done"}                                 (turn complete)
    """

    type: str  # "token" | "tool_call" | "tool_result" | "done"
    data: dict[str, Any] | str = ""

    def to_sse(self) -> dict[str, Any]:
        """Shape ready for json.dumps() in an SSE frame."""
        if self.type == "token":
            return {"type": "token", "content": self.data}
        if self.type == "done":
            return {"type": "done"}
        # tool_call / tool_result
        return {"type": self.type, "data": self.data}


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def make_tool_call_event(
    *,
    id: str = "",
    name: str,
    arguments: dict[str, Any],
    turn_id: str = "",
) -> ToolCallEvent:
    """Create a ToolCallEvent, auto-generating an id if the provider didn't give one."""
    return ToolCallEvent(
        id=id or f"call_{uuid.uuid4().hex[:12]}",
        name=name,
        arguments=arguments,
        turn_id=turn_id,
    )


def make_tool_result_event(
    *,
    call_id: str,
    name: str,
    ok: bool,
    data: dict[str, Any] | None = None,
    markdown: str = "",
    error: str = "",
    turn_id: str = "",
    tool_ms: int = 0,
) -> ToolResultEvent:
    return ToolResultEvent(
        call_id=call_id,
        name=name,
        ok=ok,
        data=data or {},
        markdown=markdown,
        error=error,
        turn_id=turn_id,
        tool_ms=tool_ms,
    )


def new_turn_id() -> str:
    """Generate a correlation ID for one orchestrator turn."""
    return f"turn_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# Legacy markdown contract helpers
#
# These remain for backward compatibility during the migration.
# They are presentation-only — never parsed for runtime semantics.
# FC7 will remove them.
# ---------------------------------------------------------------------------


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
    lines: list[str] = []
    file_ext = data.get("file_ext", "")

    for key, value in data.items():
        if key == "file_ext":
            continue
        elif isinstance(value, str) and value.startswith("<"):
            lines.append(value)
        elif key == "content" and isinstance(value, str) and "\n" in value:
            lines.append(f"{key}:")
            lines.append("")
            if file_ext == ".md":
                lines.append(value)
            else:
                lang = LANG_HINTS.get(file_ext, "")
                lines.append(f"```{lang}")
                lines.append(value)
                lines.append("```")
        else:
            lines.append(f"{key}: {value}")
    return lines
