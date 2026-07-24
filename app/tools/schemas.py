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
    name: str
    description: str
    parameters: list[ToolParam] = field(default_factory=list)

    role: str | None = None
    needs_session: bool = False

    supports_native_fc: bool = True
    supports_streaming_fc: bool = True

    def to_llm_schema(self) -> dict:
        """Serialize to OpenAI function-calling schema format."""
        properties: dict[str, dict[str, Any]] = {}
        required: list[str] = []

        for p in self.parameters:
            prop: dict[str, Any] = {"type": p.type, "description": p.description}
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
        """(｡•̀ᴗ-)✧"""
        if self.type == "token":
            return {"type": "token", "content": self.data}
        if self.type == "done":
            return {"type": "done"}
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
    error: str = "",
    turn_id: str = "",
    tool_ms: int = 0,
) -> ToolResultEvent:
    return ToolResultEvent(
        call_id=call_id,
        name=name,
        ok=ok,
        data=data or {},
        error=error,
        turn_id=turn_id,
        tool_ms=tool_ms,
    )


def new_turn_id() -> str:
    """Generate a correlation ID for one orchestrator turn."""
    return f"turn_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# Legacy format removal - build_tool_contract removed as UI renderer handles this
# ---------------------------------------------------------------------------


def ok_result(
    data: dict,
    tool_def: ToolDefinition | None = None,
    full_command: str = "",
    partner_name: str = "Yuzu",
) -> dict:
    """Construct a successful tool result payload (pure data)."""
    return {
        "ok": True,
        "data": data,
    }


def error_result(
    message: str,
    tool_def: ToolDefinition | None = None,
    full_command: str = "",
    partner_name: str = "Yuzu",
) -> dict:
    """Construct an error tool result payload."""
    return {
        "ok": False,
        "error": message,
        "data": {"error": message},
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
