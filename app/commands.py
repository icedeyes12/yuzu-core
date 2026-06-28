"""Tool-block parsing and command dispatch — implements the <tool>...</tool> protocol."""

from __future__ import annotations

import json
import re
from typing import Any

from app.logging_config import get_logger
from app.tools.registry import execute_tool

log = get_logger(__name__)

# Maximum chars for regex input to prevent ReDoS
_REGEX_INPUT_LIMIT = 100000

# Maximum tool blocks per LLM response
_MAX_TOOL_BLOCKS = 3

# Tool block parsing - uses string methods instead of regex to prevent ReDoS
# Opening and closing tags.  We accept both <tool> and <command> for
# backward compatibility (AGENTS.md mentions <tool>, older prompts use <command>).
_TOOL_OPEN_TOOLS = ("<tool>", "<command>")
_TOOL_CLOSE_TOOLS = ("</tool>", "</command>")

# Tools whose argument is a free-form string keyed by a specific field.
_STRING_ARG_TOOLS: dict[str, str] = {
    "imagine": "prompt",
    "image_generate": "prompt",  # Same as imagine (alias resolution)
    "image_edit": "prompt",  # Image edit tool
    "http_request": "url",  # HTTP request tool
    "request": "url",  # Alias for http_request
    "memory_store": "fact",
    "memory_search": "query",  # Memory search tool
    # File system tools
    "read": "path",
    "write": "path",  # Also needs content, but path is primary
    "ls": "path",
    "mkdir": "path",
    "rm": "path",
    "bash": "command",
    "python": "code",
    "sql": "query",
    # Ask Rei tool
    "ask_rei": "message",
}

# Aliases the model uses for tool routing.
# Maps tool names from LLM output to registry tool names.
# Public because it acts as a cross-module contract between commands.py
# (parser side) and orchestrator.py (native tool-call executor).
TOOL_ALIASES: dict[str, str] = {
    "imagine": "image_generate",
    "image_generate": "image_generate",
    "http_request": "http_request",
    "request": "http_request",  # Alias for http_request
    "ask-rei": "ask_rei",
}

# Image path patterns for result parsing
_GENERATED_IMAGE_SRC = re.compile(r'src="(static/generated_images/[^"]+)"')
_MARKDOWN_IMAGE_PATH = re.compile(
    r"!\[[^\]]{0,200}\]\((static/|uploads/|generated_images/)[^)]{1,200}\)"
)
_MARKDOWN_IMAGE_ANY = re.compile(r"!\[[^\]]{0,200}\]\(([^)]{1,200})\)")

# Image shortcut warning
IMAGE_SHORTCUT_WARNING = (
    "\n\nImage output detected via incorrect method. "
    "Please use <command>imagine [prompt]</command> for image generation."
)


def _safe_regex_search(pattern: re.Pattern, text: str) -> re.Match | None:
    """Safely search with input length limit to prevent ReDoS."""
    if len(text) > _REGEX_INPUT_LIMIT:
        text = text[:_REGEX_INPUT_LIMIT]
    return pattern.search(text)


# --------------------------------------------------------------------
# Tool Block Parser (NEW PROTOCOL)
# --------------------------------------------------------------------


def _match_open_tag(stripped: str) -> tuple[int, int, int] | None:
    """Check if *stripped* starts with a recognized open tag.

    Returns ``(open_len, close_offset, close_len)`` where *open_len* is the
    length of the matched open tag, *close_offset* is the offset of the
    matching close tag relative to the end of the open tag, and *close_len*
    is the length of the matched close tag.  Returns ``(open_len, -1, 0)``
    when the close tag is not on the same line, or ``None`` if no open tag
    matches.
    """
    for open_tag in _TOOL_OPEN_TOOLS:
        if stripped.startswith(open_tag):
            open_len = len(open_tag)
            for close_tag in _TOOL_CLOSE_TOOLS:
                idx = stripped.find(close_tag, open_len)
                if idx != -1:
                    return open_len, idx - open_len, len(close_tag)
            return open_len, -1, 0
    return None


def _find_close_tag(line: str) -> tuple[int, int] | None:
    """Check if *line* contains a recognized close tag.

    Returns ``(start_idx, tag_len)`` or ``None``.
    """
    for close_tag in _TOOL_CLOSE_TOOLS:
        idx = line.find(close_tag)
        if idx != -1:
            return idx, len(close_tag)
    return None


def parse_tool_blocks(text: str) -> tuple[list[str], str]:
    """Parse <tool>...</tool> or <command>...</command> blocks from LLM response.

    Returns (commands, clean_text): max 3 command strings, plus text with
    all tool blocks removed. Line-start positioning prevents accidental
    parsing of inline tool mentions in narrative.
    """
    if not text:
        return [], ""

    if len(text) > _REGEX_INPUT_LIMIT:
        text = text[:_REGEX_INPUT_LIMIT]

    lines = text.split("\n")

    matches: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        match = _match_open_tag(stripped)
        if match is None:
            i += 1
            continue

        open_len, close_idx, close_len = match
        content_lines: list[str] = []
        found_close = False

        if close_idx != -1:
            # Single-line format: <tool>command</tool>
            after_open = stripped[open_len:]
            before_close = after_open[:close_idx].strip()
            after_close = after_open[close_idx + close_len :].strip()
            if not after_close and before_close:
                matches.append(before_close)
            lines[i] = ""
        else:
            # Multi-line: <tool> ... </tool>
            after_open = stripped[open_len:].strip()
            if after_open:
                content_lines.append(after_open)
            j = i + 1
            while j < len(lines):
                inner_line = lines[j]
                inner_stripped = inner_line.strip()

                close_match = _find_close_tag(inner_line)
                if close_match is not None:
                    close_start, close_len = close_match
                    before_close = inner_line[:close_start].strip()
                    if before_close:
                        content_lines.append(before_close)
                    found_close = True
                    for k in range(i, j + 1):
                        lines[k] = ""
                    break
                else:
                    content_lines.append(inner_line.strip())
                j += 1

            if found_close and content_lines:
                content = "\n".join(content_lines).strip()
                if content:
                    matches.append(content)

        i += 1

    matches = matches[:_MAX_TOOL_BLOCKS]

    clean_text = "\n".join(lines)
    lines = clean_text.split("\n")
    cleaned_lines: list[str] = []
    prev_empty = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if not prev_empty:
                cleaned_lines.append("")
            prev_empty = True
        else:
            cleaned_lines.append(stripped)
            prev_empty = False

    while cleaned_lines and not cleaned_lines[0]:
        cleaned_lines.pop(0)
    while cleaned_lines and not cleaned_lines[-1]:
        cleaned_lines.pop()

    clean_text = "\n".join(cleaned_lines)

    return matches, clean_text


def has_tool_blocks(text: str) -> bool:
    """Check if text contains any <tool>...</tool> or <command>...</command> blocks."""
    if not text:
        return False
    if len(text) > _REGEX_INPUT_LIMIT:
        text = text[:_REGEX_INPUT_LIMIT]

    for open_tag, close_tag in zip(_TOOL_OPEN_TOOLS, _TOOL_CLOSE_TOOLS):
        if open_tag in text and close_tag in text:
            return True

    lines = text.split("\n")
    for line in lines:
        stripped = line.strip()
        if _match_open_tag(stripped) is not None:
            return True

    return False


def _parse_command_string(command_str: str) -> dict[str, str] | None:
    """Parse a command string into {command, args}.

    Command format: /command_name args...
    or just: command_name args...

    Returns None if the command string is invalid.
    """
    stripped = command_str.strip()
    if not stripped:
        return None

    if stripped.startswith("/"):
        stripped = stripped[1:]

    parts = stripped.split(None, 1)
    if not parts:
        return None

    command_name = parts[0]
    args = parts[1] if len(parts) > 1 else ""

    return {
        "command": command_name,
        "args": args,
        "full_command": f"/{command_name} {args}".strip(),
    }


def _parse_args(tool_name: str, raw_args: str) -> dict[str, Any]:
    """Parse raw argument string into a dict for the tool."""
    if len(raw_args) > 5000:
        raw_args = raw_args[:5000]

    raw_args = raw_args.strip()

    if tool_name in ("image_edit",):
        return _parse_key_value_args(raw_args)

    if tool_name in _STRING_ARG_TOOLS:
        key = _STRING_ARG_TOOLS[tool_name]

        if tool_name == "write":
            parts = raw_args.split(None, 1)
            if len(parts) == 2:
                return {"path": parts[0], "content": parts[1]}
            elif len(parts) == 1:
                return {"path": parts[0], "content": ""}
            return {"path": "", "content": raw_args}

        return {key: raw_args}

    if raw_args.startswith("{") and raw_args.endswith("}"):
        try:
            return json.loads(raw_args)
        except json.JSONDecodeError:
            pass

    result: dict[str, Any] = {}
    if not raw_args:
        return result

    for pair in raw_args.split(";"):
        pair = pair.strip()
        if "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        result[key] = value

    return result


def _parse_key_value_args(raw_args: str) -> dict[str, Any]:
    """Parse key=value args from raw_args string."""
    if len(raw_args) > 1000:
        raw_args = raw_args[:1000]

    if not raw_args:
        return {}

    if raw_args.startswith("{") and raw_args.endswith("}"):
        try:
            return json.loads(raw_args)
        except json.JSONDecodeError:
            pass

    result: dict[str, Any] = {}
    for pair in raw_args.split(";"):
        pair = pair.strip()
        if "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        result[key] = value

    return result


async def execute_commands(
    commands: list[str],
    session_id: str | None = None,
    user_id: str | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Execute a list of commands sequentially (async).

    All commands are executed in order, even if one fails.
    Errors are logged but don't stop execution.

    Args:
        commands: List of command strings (from parse_tool_blocks)
        session_id: Optional session ID for context

    Returns:
        List of (tool_name, result_dict) tuples for each command
    """
    results: list[tuple[str, dict[str, Any]]] = []

    for command_str in commands:
        try:
            parsed = _parse_command_string(command_str)
            if not parsed:
                log.warning("failed to parse command: %s", command_str[:100])
                results.append(
                    ("unknown", {"ok": False, "error": "Failed to parse command"})
                )
                continue

            raw_name = parsed["command"]
            tool_name = TOOL_ALIASES.get(raw_name, raw_name)
            args = _parse_args(tool_name, parsed["args"])

            log.info("executing tool: %s with args: %s", tool_name, str(args)[:100])
            result = await execute_tool(
                tool_name, args, session_id=session_id, user_id=user_id
            )
            results.append((tool_name, result))

        except Exception as e:
            log.error("command execution failed: %s - %s", command_str[:50], e)
            results.append(("unknown", {"ok": False, "error": str(e)}))

    return results


def format_observation(results: list[tuple[str, dict[str, Any]]]) -> str:
    """Format tool execution results as a system observation.

    Creates a structured observation block for appending to conversation history.

    Args:
        results: List of (tool_name, result_dict) tuples

    Returns:
        Formatted observation string wrapped in <SYSTEM_OBSERVATION> tags
    """
    if not results:
        return ""

    lines = ["<SYSTEM_OBSERVATION>"]

    for i, (tool_name, result) in enumerate(results, 1):
        lines.append(f"Command {i}:")
        lines.append(f"TOOL: {tool_name}")

        if isinstance(result, dict):
            ok = result.get("ok", False)
            lines.append(f"STATUS: {'SUCCESS' if ok else 'FAILED'}")

            data = result.get("data", {})
            if isinstance(data, dict):
                if "command" in data:
                    lines.append(f"COMMAND: {data['command']}")
                if "exit_code" in data:
                    lines.append(f"EXIT_CODE: {data['exit_code']}")
                if "stdout" in data:
                    stdout = data["stdout"]
                    if stdout:
                        lines.append(f"STDOUT:\n{stdout}")
                    else:
                        lines.append("STDOUT: (empty)")
                if "stderr" in data:
                    stderr = data["stderr"]
                    if stderr:
                        lines.append(f"STDERR:\n{stderr}")
                    else:
                        lines.append("STDERR: (empty)")
                if "output" in data:
                    lines.append(f"OUTPUT:\n{data['output']}")
                if "image_path" in data:
                    lines.append(f"IMAGE: {data['image_path']}")

            error = result.get("error")
            if error:
                lines.append(f"ERROR: {error}")

            markdown = result.get("markdown")
            if markdown and ok:
                lines.append(f"MARKDOWN:\n{markdown[:500]}")
        else:
            lines.append(f"RESULT: {str(result)[:500]}")

        lines.append("")

    lines.append("</SYSTEM_OBSERVATION>")
    return "\n".join(lines)


def parse_image_path(formatted_result: str) -> str | None:
    """Extract and validate a generated-image path from markdown blob."""
    if not formatted_result:
        return None

    match = _GENERATED_IMAGE_SRC.search(formatted_result)
    if not match:
        return None

    raw_path = match.group(1).strip()
    if not raw_path:
        return None

    candidate = raw_path.replace("\\", "/")
    if candidate.startswith("/") or candidate.startswith("../") or "/../" in candidate:
        return None
    if "/./" in candidate or candidate.endswith("/.") or candidate.endswith("/.."):
        return None

    if not (candidate.startswith("static/") or candidate.startswith("uploads/")):
        return None

    # Restrict to common image file extensions
    lowered = candidate.lower()
    if not lowered.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        return None

    return candidate


def is_markdown_image_shortcut(response_text: str | None) -> bool:
    if not response_text:
        return False
    if len(response_text) > _REGEX_INPUT_LIMIT:
        response_text = response_text[:_REGEX_INPUT_LIMIT]
    return bool(_MARKDOWN_IMAGE_PATH.search(response_text))


def extract_markdown_image_path(response_text: str) -> str | None:
    """Return the first markdown image path/URL in *response_text*, if any."""
    if len(response_text) > _REGEX_INPUT_LIMIT:
        response_text = response_text[:_REGEX_INPUT_LIMIT]
    match = _MARKDOWN_IMAGE_ANY.search(response_text)
    return match.group(1) if match else None
