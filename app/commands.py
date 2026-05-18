# FILE: app/commands.py
# DESCRIPTION: Tool-block parsing and command dispatch for Yuzu Companion.
#              Implements the <tool>...</tool> protocol for tool invocation.

from __future__ import annotations

import json
import re
from typing import Any

from app.logging_config import get_logger
from app.tools.registry import execute_tool

log = get_logger(__name__)

# --------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------

# Maximum chars for regex input to prevent ReDoS
_REGEX_INPUT_LIMIT = 100000

# Maximum tool blocks per LLM response
_MAX_TOOL_BLOCKS = 3

# Tool block parsing - uses string methods instead of regex to prevent ReDoS
# Opening and closing tags
_TOOL_OPEN = "<tool>"
_TOOL_CLOSE = "</tool>"

# Tools whose argument is a free-form string keyed by a specific field.
_STRING_ARG_TOOLS: dict[str, str] = {
    "imagine": "prompt",
    "image_generate": "prompt",  # Same as imagine (alias resolution)
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
_TOOL_ALIASES: dict[str, str] = {
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
    "Please use <tool>/imagine [prompt]</tool> for image generation."
)


# --------------------------------------------------------------------
# Safe regex helper
# --------------------------------------------------------------------


def _safe_regex_search(pattern: re.Pattern, text: str) -> re.Match | None:
    """Safely search with input length limit to prevent ReDoS."""
    if len(text) > _REGEX_INPUT_LIMIT:
        text = text[:_REGEX_INPUT_LIMIT]
    return pattern.search(text)


# --------------------------------------------------------------------
# Tool Block Parser (NEW PROTOCOL)
# --------------------------------------------------------------------


def parse_tool_blocks(text: str) -> tuple[list[str], str]:
    """Parse <tool>...</tool> blocks from LLM response.

    This is the core parser for the new tool invocation protocol.

    Args:
        text: Raw LLM response text

    Returns:
        (commands, clean_text) tuple where:
        - commands: List of command strings (max 3), stripped of whitespace
        - clean_text: Original text with all tool blocks removed

    Rules:
        - Tool blocks are delimited by <tool> and </tool> tags
        - Content inside tags is stripped of leading/trailing whitespace
        - Empty tool blocks are ignored
        - Nested <tool> tags are invalid and ignored
        - Maximum 3 tool blocks per response (extras ignored)
        - All conversational text outside blocks is preserved exactly

    Example:
        Input:
            Baik saya cek dulu
            <tool>
            ls -la
            </tool>
            <tool>
            pwd
            </tool>
            Mari tunggu hasilnya

        Output:
            commands = ["ls -la", "pwd"]
            clean_text = "Baik saya cek dulu\\nMari tunggu hasilnya"
    """
    if not text:
        return [], ""

    # Limit input to prevent ReDoS
    if len(text) > _REGEX_INPUT_LIMIT:
        text = text[:_REGEX_INPUT_LIMIT]

    # Find all tool blocks
    matches = []
    start = 0
    while True:
        open_idx = text.find(_TOOL_OPEN, start)
        if open_idx == -1:
            break
        close_idx = text.find(_TOOL_CLOSE, open_idx + len(_TOOL_OPEN))
        if close_idx == -1:
            break
        content = text[open_idx + len(_TOOL_OPEN) : close_idx].strip()
        if content:
            matches.append(content)
        start = close_idx + len(_TOOL_CLOSE)

    # Limit to max 3 blocks
    matches = matches[:_MAX_TOOL_BLOCKS]

    # Extract commands (strip whitespace, skip empty)
    commands: list[str] = []
    for match in matches:
        command = match.strip()
        if command:
            commands.append(command)

    # Remove all tool blocks from text using string replacement
    clean_text = text
    while _TOOL_OPEN in clean_text:
        start_idx = clean_text.find(_TOOL_OPEN)
        end_idx = clean_text.find(_TOOL_CLOSE, start_idx)
        if end_idx == -1:
            break
        clean_text = clean_text[:start_idx] + clean_text[end_idx + len(_TOOL_CLOSE) :]

    # Clean up excessive whitespace but preserve structure
    # Remove leading/trailing whitespace from lines but keep line breaks
    lines = clean_text.split("\n")
    cleaned_lines: list[str] = []
    prev_empty = False

    for line in lines:
        stripped = line.strip()
        # Collapse multiple consecutive empty lines into one
        if not stripped:
            if not prev_empty:
                cleaned_lines.append("")
            prev_empty = True
        else:
            cleaned_lines.append(stripped)
            prev_empty = False

    # Remove leading/trailing empty lines
    while cleaned_lines and not cleaned_lines[0]:
        cleaned_lines.pop(0)
    while cleaned_lines and not cleaned_lines[-1]:
        cleaned_lines.pop()

    clean_text = "\n".join(cleaned_lines)

    return commands, clean_text


def has_tool_blocks(text: str) -> bool:
    """Check if text contains any <tool>...</tool> blocks."""
    if not text:
        return False
    if len(text) > _REGEX_INPUT_LIMIT:
        text = text[:_REGEX_INPUT_LIMIT]
    # Use string find instead of regex to prevent ReDoS
    open_idx = text.find(_TOOL_OPEN)
    if open_idx == -1:
        return False
    close_idx = text.find(_TOOL_CLOSE, open_idx)
    return close_idx != -1


# --------------------------------------------------------------------
# Command Parsing (Legacy /command support removed)
# --------------------------------------------------------------------


def _parse_command_string(command_str: str) -> dict[str, str] | None:
    """Parse a command string into {command, args}.

    Command format: /command_name args...
    or just: command_name args...

    Returns None if the command string is invalid.
    """
    stripped = command_str.strip()
    if not stripped:
        return None

    # Handle /command format (legacy but still supported)
    if stripped.startswith("/"):
        stripped = stripped[1:]

    # Split into command name and args
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
    """Parse raw argument string into a dict for the tool.

    Supports:
    - String-arg tools: Just pass the raw string as the keyed arg
    - JSON args: Parse as JSON if it looks like JSON
    - Key=value pairs: Parse as key=value; key2="value with spaces"
    """
    # SECURITY: Limit input size to prevent ReDoS
    if len(raw_args) > 5000:
        raw_args = raw_args[:5000]

    raw_args = raw_args.strip()

    # String-arg tools: single argument mapped to a specific key
    if tool_name in _STRING_ARG_TOOLS:
        key = _STRING_ARG_TOOLS[tool_name]

        # Special case for /write: path + content
        if tool_name == "write":
            parts = raw_args.split(None, 1)
            if len(parts) == 2:
                return {"path": parts[0], "content": parts[1]}
            elif len(parts) == 1:
                return {"path": parts[0], "content": ""}
            return {"path": "", "content": raw_args}

        return {key: raw_args}

    # Try JSON parse first
    if raw_args.startswith("{") and raw_args.endswith("}"):
        try:
            return json.loads(raw_args)
        except json.JSONDecodeError:
            pass

    # Parse key=value; key2="value with spaces"
    # SECURITY: Use string operations instead of regex to prevent ReDoS
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
        # Handle quoted values
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        result[key] = value

    return result


def _parse_key_value_args(raw_args: str) -> dict[str, Any]:
    """Parse key=value args from raw_args string.

    Args format:
    - Plain args: Just text after command
    - JSON args: Parse as JSON if it looks like JSON
    - Key=value pairs: Parse as key=value; key2="value with spaces"
    """
    # SECURITY: Limit input size to prevent ReDoS
    if len(raw_args) > 1000:
        raw_args = raw_args[:1000]

    if not raw_args:
        return {}

    # Try JSON first
    if raw_args.startswith("{") and raw_args.endswith("}"):
        try:
            return json.loads(raw_args)
        except json.JSONDecodeError:
            pass

    # Parse key=value; key2="value with spaces"
    result: dict[str, Any] = {}

    # SECURITY: Use non-backtracking pattern with bounded quantifiers
    # Pattern: key="value with spaces" or key=value
    # Using string operations instead of complex regex for safety
    for pair in raw_args.split(";"):
        pair = pair.strip()
        if "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        key = key.strip()
        if not key:
            continue
        # Handle quoted values
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        result[key] = value

    return result


# --------------------------------------------------------------------
# Command Execution
# --------------------------------------------------------------------


def execute_commands(
    commands: list[str],
    session_id: int | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Execute a list of commands sequentially.

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
            tool_name = _TOOL_ALIASES.get(raw_name, raw_name)
            args = _parse_args(tool_name, parsed["args"])

            log.info("executing tool: %s with args: %s", tool_name, str(args)[:100])
            result = execute_tool(tool_name, args, session_id=session_id)
            results.append((tool_name, result))

        except Exception as e:
            log.error("command execution failed: %s - %s", command_str[:50], e)
            results.append(("unknown", {"ok": False, "error": str(e)}))

    return results


# --------------------------------------------------------------------
# Observation Formatting
# --------------------------------------------------------------------


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
                # Extract common fields
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
                # Include markdown for successful results
                lines.append(f"MARKDOWN:\n{markdown[:500]}")
        else:
            lines.append(f"RESULT: {str(result)[:500]}")

        lines.append("")  # Blank line between commands

    lines.append("</SYSTEM_OBSERVATION>")
    return "\n".join(lines)


# --------------------------------------------------------------------
# Image Helpers
# --------------------------------------------------------------------


def parse_image_path(formatted_result: str) -> str | None:
    """Extract and validate a generated-image path from a tool-contract markdown blob."""
    if not formatted_result:
        return None

    match = _GENERATED_IMAGE_SRC.search(formatted_result)
    if not match:
        return None

    raw_path = match.group(1).strip()
    if not raw_path:
        return None

    # Normalize separators and reject absolute/escape paths
    candidate = raw_path.replace("\\", "/")
    if candidate.startswith("/") or candidate.startswith("../") or "/../" in candidate:
        return None
    if "/./" in candidate or candidate.endswith("/.") or candidate.endswith("/.."):
        return None

    # Allow only known local roots used by the app for generated/served images
    if not (candidate.startswith("static/") or candidate.startswith("uploads/")):
        return None

    # Restrict to common image file extensions
    lowered = candidate.lower()
    if not lowered.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        return None

    return candidate


def is_markdown_image_shortcut(response_text: str | None) -> bool:
    """True when the model emitted a raw ![](static/...) instead of <tool>."""
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


# --------------------------------------------------------------------
# Legacy Compatibility (deprecated, will be removed)
# --------------------------------------------------------------------

# These are kept for backward compatibility during transition
# but should not be used in new code


def detect_command(
    text: str, scan_mode: str = "first_line"
) -> dict[str, str] | list[dict[str, str]] | None:
    """DEPRECATED: Use parse_tool_blocks() instead.

    This function is kept for backward compatibility but will be removed.
    It now checks for both <tool> blocks and legacy /command format.
    """
    log.warning("detect_command() is deprecated, use parse_tool_blocks() instead")

    # Try new tool block format first
    commands, _ = parse_tool_blocks(text)
    if commands:
        parsed = [_parse_command_string(cmd) for cmd in commands]
        parsed = [p for p in parsed if p]  # Filter out None
        if len(parsed) == 1:
            return parsed[0]
        return parsed if parsed else None

    # Fall back to legacy /command detection
    if not text:
        return None

    lines = text.strip().split("\n")
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("/"):
            result = _parse_command_string(stripped)
            if result:
                return result
        # Stop after first non-empty line for first_line mode
        if stripped and scan_mode == "first_line":
            break

    return None


def execute_command(
    command_info: dict[str, str] | list[dict[str, str]],
    session_id: int | None = None,
) -> tuple[str, dict[str, Any]] | list[tuple[str, dict[str, Any]]]:
    """DEPRECATED: Use execute_commands() instead.

    This function is kept for backward compatibility.
    """
    log.warning("execute_command() is deprecated, use execute_commands() instead")

    if isinstance(command_info, list):
        command_strs = []
        for cmd in command_info:
            if cmd.get("full_command"):
                command_strs.append(cmd["full_command"])
            elif cmd.get("command"):
                args = cmd.get("args", "")
                command_strs.append(f"/{cmd['command']} {args}".strip())
        return execute_commands(command_strs, session_id)

    # Single command
    if command_info.get("full_command"):
        command_str = command_info["full_command"]
    else:
        args = command_info.get("args", "")
        command_str = f"/{command_info['command']} {args}".strip()

    results = execute_commands([command_str], session_id)
    return results[0] if results else ("unknown", {"ok": False, "error": "No command"})


# --------------------------------------------------------------------
# StreamFilter - REMOVED
# --------------------------------------------------------------------
# The StreamFilter class was used for sniffing /command at the start of
# streaming responses. With the new <tool> protocol, we parse the full
# response after streaming completes, so StreamFilter is no longer needed.
#
# If streaming with tool detection is needed in the future, it should be
# implemented differently - by buffering until </tool> is seen.
