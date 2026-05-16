# FILE: app/commands.py
# DESCRIPTION: /command detection, dispatch, and markdown-image guards.
#              All pure helpers - no side effects beyond log

from __future__ import annotations

import json
import re
from typing import Any, Iterator

from app.logging_config import get_logger
from app.tools.registry import execute_tool

log = get_logger(__name__)

# Tools whose argument is a free-form string keyed by a specific field.
_STRING_ARG_TOOLS: dict[str, str] = {
    "imagine": "prompt",
    "request": "url",
    "memory_store": "fact",
    # File system tools
    "read": "path",
    "ls": "path",
    "mkdir": "path",
    "rm": "path",
    "bash": "command",  # Fixed: was "code"
    "python": "code",
    "sql": "query",     # Fixed: was "sql"
    # write is handled specially in _parse_args (path + content)
}

# Aliases the model uses for tool routing.
# These map /command names to registry tool names.
_TOOL_ALIASES: dict[str, str] = {
    "imagine": "image_generate",
    "image_generate": "image_generate",
}

_MARKDOWN_IMAGE_PATH = re.compile(
    r'!\[[^\]]{0,200}\]\((static/|uploads/|generated_images/)[^)]{1,200}\)'
)
_MARKDOWN_IMAGE_ANY = re.compile(r'!\[[^\]]{0,200}\]\(([^)]{1,200})\)')
_GENERATED_IMAGE_SRC = re.compile(r'src="(static/generated_images/[^"]+)"')

# Maximum chars to buffer while sniffing for a leading /command.
# Generous enough for any realistic command line, but bounded so we never
# starve the user of streamed output if the model omits a newline.
_COMMAND_SNIFF_LIMIT = 512

# Maximum length for regex input to prevent ReDoS
_REGEX_INPUT_LIMIT = 10000

# Maximum commands to detect in batch mode
_MAX_BATCH_COMMANDS = 3


def _safe_regex_search(pattern: re.Pattern, text: str) -> re.Match | None:
    """Safely search with input length limit to prevent ReDoS."""
    if len(text) > _REGEX_INPUT_LIMIT:
        text = text[:_REGEX_INPUT_LIMIT]
    return pattern.search(text)


def _is_inside_inline_code(line: str, position: int) -> bool:
    """Check if position in line is inside inline code (between backticks).
    
    Simple heuristic: count backticks before position.
    If odd, position is inside inline code.
    """
    backtick_count = line[:position].count("`")
    return backtick_count % 2 == 1


def _parse_command_line(line: str) -> dict[str, str] | None:
    """Parse a /command line into {command, args, full_command}.
    
    Returns None if line doesn't start with /.
    """
    stripped = line.strip()
    if not stripped.startswith("/"):
        return None
    
    # Extract command name (first word after /)
    parts = stripped.split(None, 1)
    if not parts:
        return None
    
    cmd_with_slash = parts[0]
    cmd_name = cmd_with_slash[1:]  # Remove leading /
    
    # Accept any command name - validation happens at execution time
    return {
        "command": cmd_name,
        "args": parts[1] if len(parts) > 1 else "",
        "full_command": stripped,
    }


def detect_command(
    response_text: str,
    scan_mode: str = "first_line",
) -> list[dict[str, Any]]:
    """Detect inline /command calls in model output.

    Returns a list of dicts, each with keys:
        command: str   — tool name without the leading /
        args: str      — raw argument string
        full_command: str — the full matched line

    scan_mode:
        "first_line" — only scan the first non-blank line (for streaming)
        "full"       — scan the entire text (for non-streaming / synthesis)
    """
    if len(response_text) > _REGEX_INPUT_LIMIT:
        response_text = response_text[:_REGEX_INPUT_LIMIT]

    if scan_mode == "first_line":
        first_line = response_text.split("\n", 1)[0].strip()
        result = _parse_command_line(first_line)
        if result:
            # For multi-line tools, try to extract code block from full text
            cmd = result.get("command", "")
            if cmd in ("sql", "python", "bash"):
                block_content = _extract_code_block(response_text, cmd)
                if block_content is not None:
                    result["args"] = block_content
                    result["full_command"] = f"/{cmd} {block_content}"
                else:
                    # No code block — take everything after command name from full text
                    full_stripped = response_text.lstrip()
                    if full_stripped.startswith(f"/{cmd}"):
                        remainder = full_stripped[len(f"/{cmd}"):].strip()
                        if remainder:
                            result["args"] = remainder
                            result["full_command"] = f"/{cmd} {remainder}"
            return [result]
        return []

    # Full scan mode
    results = []
    for match in _find_naked_commands_in_line(response_text):
        pass
    return results


def _find_naked_commands_in_line(line: str) -> list[dict[str, str]]:
    """Find all naked /command occurrences in a line.
    
    A command is "naked" if NOT inside:
    - Inline code (`...`)
    - Quotes ("..." or '...')
    
    Returns list of {command, args, full_command} dicts.
    """
    results = []
    
    # Pattern: /word followed by optional args (until end of line or next wrapper)
    # Command must be preceded by start of line, whitespace, or certain punctuation
    pattern = re.compile(r'(?:^|[\s\-–—\(])(/[a-zA-Z_][a-zA-Z0-9_]*)')
    
    for match in pattern.finditer(line):
        slash_pos = match.start(1)  # Position of the / in the match
        
        # Check if inside inline code
        if _is_inside_inline_code(line, slash_pos):
            continue
        
        # Check if inside quotes
        if _is_inside_quotes(line, slash_pos):
            continue
        
        # Extract the full command from this position
        remainder = line[slash_pos:]
        cmd_info = _parse_command_line(remainder)
        if cmd_info:
            results.append(cmd_info)
    
    return results


def _is_inside_quotes(line: str, position: int) -> bool:
    """Check if position in line is inside quotes ("..." or '...').
    
    Simple heuristic: count unescaped quotes before position.
    If odd for either type, position is inside that quote type.
    """
    prefix = line[:position]
    
    # Count unescaped double quotes
    double_count = prefix.count('"') - prefix.count('\\"')
    if double_count % 2 == 1:
        return True
    
    # Count unescaped single quotes  
    single_count = prefix.count("'") - prefix.count("\\'")
    if single_count % 2 == 1:
        return True
    
    return False


def _parse_args(tool_name: str, args_str: str) -> dict[str, Any]:
    """Parse a /command argument string into a kwargs dict for the tool."""
    if not args_str:
        return {}
    if tool_name in _STRING_ARG_TOOLS:
        return {_STRING_ARG_TOOLS[tool_name]: args_str}
    
    # Special handling for /write: first word is path, rest is content
    if tool_name == "write":
        # Check for heredoc syntax: /write path <<DELIM\ncontent\nDELIM
        heredoc_match = re.match(r'^(\S+)\s+<<(\S+)\s*\n?(.*)', args_str, re.DOTALL)
        if heredoc_match:
            path = heredoc_match.group(1)
            delimiter = heredoc_match.group(2)
            body = heredoc_match.group(3)
            # Extract content up to the closing delimiter
            end_marker = f"\n{delimiter}"
            if end_marker in body:
                content = body[:body.index(end_marker)]
            elif body.rstrip().endswith(delimiter):
                content = body[:body.rindex(delimiter)].rstrip()
            else:
                content = body
            return {"path": path, "content": content}
        # Standard: first word is path, rest is content
        parts = args_str.split(None, 1)
        if len(parts) == 1:
            return {"path": parts[0], "content": ""}
        return {"path": parts[0], "content": parts[1]}
    
    # Try JSON parse
    try:
        parsed = json.loads(args_str)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return {"query": args_str}


def _extract_code_block(text: str, tool_name: str) -> str | None:
    """Extract content from a fenced code block for multi-line tools.

    Looks for ```<lang> ... ``` blocks where lang matches the tool.
    Returns the inner content if found, None otherwise.

    Example:
        /sql ```sql
        SELECT id, role
        FROM users
        ```
        -> "SELECT id, role\nFROM users"
    """
    # Map tool names to code block language identifiers
    lang_map = {
        "sql": "sql",
        "python": "python",
        "bash": "bash",
    }
    lang = lang_map.get(tool_name, tool_name)

    # Pattern: ```lang\n...content...```
    # Use DOTALL so . matches newlines
    pattern = re.compile(rf'```{lang}\s*\n(.*?)```', re.DOTALL)
    match = pattern.search(text)
    if match:
        return match.group(1).strip()

    # Also try without language tag: ```\n...content...```
    if tool_name in lang_map:
        pattern = re.compile(r'```\s*\n(.*?)```', re.DOTALL)
        match = pattern.search(text)
        if match:
            return match.group(1).strip()

    return None


class StreamFilter:
    """Stateful filter that holds back chunks until a /command on the first
    line can be confirmed or ruled out.

    Usage:
        sf = StreamFilter()
        for chunk in upstream:
            for safe in sf.feed(chunk):
                yield safe
        for safe in sf.flush():
            yield safe

        # After streaming completes:
        if sf.command:
            ...  # don't render command line; suppressed via emit
        full_text = sf.full_text

    Behavior:
      - First non-whitespace char is '/': buffer until newline (or limit).
        On newline, parse the command, suppress that line, and stream the
        rest live.
      - First non-whitespace char is not '/': flush buffer immediately and
        pass through every subsequent chunk untouched.
    """

    __slots__ = ("_buffer", "_decided", "_is_command", "command", "full_text",
                 "_in_heredoc", "_heredoc_delimiter", "_heredoc_buffer")

    def __init__(self) -> None:
        self._buffer = ""
        self._decided = False
        self._is_command = False
        self.command: dict[str, str] | None = None
        self.full_text = ""

    def feed(self, chunk: str) -> Iterator[str]:  # type: ignore[name-defined]
        if not chunk:
            return
        self.full_text += chunk

        if self._decided and not self._is_command:
            yield chunk
            return

        if self._decided and self._is_command:
            # Command was already detected in a previous chunk.
            # Any subsequent text is narration — yield it live.
            # EXCEPT: if we're in heredoc mode, keep buffering
            if getattr(self, "_in_heredoc", False):
                self._heredoc_buffer += chunk
                # Check if closing delimiter is in the buffer
                delim_line = f"\n{self._heredoc_delimiter}"
                if delim_line in self._heredoc_buffer:
                    # End of heredoc: update command args with full content
                    end_idx = self._heredoc_buffer.index(delim_line)
                    heredoc_content = self._heredoc_buffer[:end_idx]
                    if self.command:
                        self.command["args"] = f"{self.command['args']}\n{heredoc_content}"
                        self.command["full_command"] = f"/write {self.command['args']}"
                    self._in_heredoc = False
                    self._heredoc_buffer = ""
                # Don't yield heredoc content to user
                return
            yield chunk
            return

        self._buffer += chunk

        if not self._decided:
            stripped = self._buffer.lstrip()
            if stripped and not stripped.startswith("/"):
                # Definitely not a command.
                self._decided = True
                self._is_command = False
                yield self._buffer
                self._buffer = ""
                return
            if len(self._buffer) >= _COMMAND_SNIFF_LIMIT and "\n" not in self._buffer:
                # Ran out of patience: treat as plain text.
                self._decided = True
                self._is_command = False
                yield self._buffer
                self._buffer = ""
                return
            if not stripped:
                # Only whitespace so far; keep buffering.
                return
            # Starts with '/': wait for the newline (handled below).

        if "\n" in self._buffer and not self._decided:
            self._decided = True
            self._is_command = True
            first_line, _, rest = self._buffer.partition("\n")
            self.command = detect_command(first_line)
            self._buffer = ""
            # Heredoc support: if command args contain <<DELIM, keep buffering
            # until we find the closing delimiter line
            if self.command and self.command["command"] == "write":
                args = self.command.get("args", "")
                heredoc_match = re.match(r'^(\S+)\s+<<(\S+)', args)
                if heredoc_match:
                    delimiter = heredoc_match.group(2)
                    # Start heredoc capture: buffer rest + subsequent chunks
                    self._heredoc_delimiter = delimiter
                    self._heredoc_buffer = rest
                    self._in_heredoc = True
                    # Don't yield anything yet
                    return
            # No heredoc: suppress command line, yield rest if any
            if rest:
                yield rest

    def flush(self) -> Iterator[str]:  # type: ignore[name-defined]
        """Drain any held-back text. Call once after the upstream completes."""
        # Handle heredoc: if stream ended while still buffering heredoc
        if getattr(self, "_in_heredoc", False) and self.command:
            # Finalize heredoc content (no closing delimiter found)
            heredoc_content = self._heredoc_buffer.rstrip()
            if heredoc_content:
                self.command["args"] = f"{self.command['args']}\n{heredoc_content}"
                self.command["full_command"] = f"/write {self.command['args']}"
            self._in_heredoc = False
            self._heredoc_buffer = ""
            self._decided = True
            return
        if not self._decided:
            # Stream ended before we could decide. If the buffer starts with
            # a slash and never produced a newline, treat it as a command on
            # a single line.
            stripped = self._buffer.lstrip()
            if stripped.startswith("/"):
                self._is_command = True
                self.command = detect_command(self._buffer)
            else:
                yield self._buffer
            self._buffer = ""
            self._decided = True

    def get_commands(
        self, scan_mode: str = "first_line"
    ) -> dict[str, str] | list[dict[str, str]] | None:
        """Return detected command(s), with optional full-text scan.

        Args:
            scan_mode: Detection mode:
                - "first_line": Return self.command (first-line detection result)
                - "any_naked": Scan full_text, return first naked command
                - "all_naked": Scan full_text, return all naked commands (list)

        This delegates to detect_command() for full-text scanning,
        avoiding logic duplication.
        """
        if scan_mode == "first_line":
            return self.command
        # Delegate to detect_command for naked scanning
        return detect_command(self.full_text, scan_mode=scan_mode)


def execute_command(
    command_info: dict[str, str] | list[dict[str, str]],
    session_id: int | None = None,
) -> tuple[str, dict[str, Any]] | list[tuple[str, dict[str, Any]]]:
    """Resolve and execute a detected command or list of commands.

    Args:
        command_info: Single command dict or list of command dicts.
        session_id: Optional session ID for context.

    Returns:
        - Single command: (tool_name, result_dict)
        - Batch commands: list of (tool_name, result_dict) tuples

    For batch execution, commands are executed sequentially in order.
    Errors are logged but don't stop execution of remaining commands.
    """
    # Batch mode: list of commands
    if isinstance(command_info, list):
        results: list[tuple[str, dict[str, Any]]] = []
        for cmd in command_info:
            try:
                result = _execute_single_command(cmd, session_id)
                results.append(result)
            except Exception as e:
                log.error("command execution failed: /%s - %s", cmd.get("command", "?"), e)
                # Append error result so caller knows which command failed
                results.append((cmd.get("command", "?"), {"error": str(e)}))
        return results

    # Single command mode
    return _execute_single_command(command_info, session_id)


def _execute_single_command(
    command_info: dict[str, str],
    session_id: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """Execute a single command. Internal helper."""
    raw_name = command_info["command"]
    tool_name = _TOOL_ALIASES.get(raw_name, raw_name)
    args = _parse_args(raw_name, command_info["args"])
    log.info("command: /%s %s", raw_name, command_info["args"])
    result = execute_tool(tool_name, args, session_id=session_id)
    return tool_name, result


def parse_image_path(formatted_result: str) -> str | None:
    """Extract a generated-image path from a tool-contract markdown blob."""
    if not formatted_result:
        return None
    match = _GENERATED_IMAGE_SRC.search(formatted_result)
    return match.group(1) if match else None


def is_markdown_image_shortcut(response_text: str | None) -> bool:
    """True when the model emitted a raw ![](static/...) instead of /imagine."""
    if not response_text:
        return False
    # Limit input length to prevent ReDoS
    if len(response_text) > _REGEX_INPUT_LIMIT:
        response_text = response_text[:_REGEX_INPUT_LIMIT]
    return bool(_MARKDOWN_IMAGE_PATH.search(response_text))


def extract_markdown_image_path(response_text: str) -> str | None:
    """Return the first markdown image path/URL in *response_text*, if any."""
    # Limit input length to prevent ReDoS
    if len(response_text) > _REGEX_INPUT_LIMIT:
        response_text = response_text[:_REGEX_INPUT_LIMIT]
    match = _MARKDOWN_IMAGE_ANY.search(response_text)
    return match.group(1) if match else None


IMAGE_SHORTCUT_WARNING = (
    "\n\nImage output detected via incorrect method. "
    "Please use /imagine to generate images."
)