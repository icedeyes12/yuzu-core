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
}

# Aliases the model uses for tool routing.
_TOOL_ALIASES: dict[str, str] = {
    "imagine": "image_generate",
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


def _safe_regex_search(pattern: re.Pattern, text: str) -> re.Match | None:
    """Safely search with input length limit to prevent ReDoS."""
    if len(text) > _REGEX_INPUT_LIMIT:
        text = text[:_REGEX_INPUT_LIMIT]
    return pattern.search(text)


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

    __slots__ = ("_buffer", "_decided", "_is_command", "command", "full_text")

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
            # Suppress the command line; the rest is rarely produced by the
            # model when a /command is the first line, but pass it through
            # for correctness.
            if rest:
                yield rest

    def flush(self) -> Iterator[str]:  # type: ignore[name-defined]
        """Drain any held-back text. Call once after the upstream completes."""
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


def detect_command(response_text: str | None) -> dict[str, str] | None:
    """Return command info if response begins with a /command line, else None.

    Returned dict shape: {"command": str, "args": str, "full_command": str}.
    """
    if not response_text or not response_text.strip():
        return None
    first_line = response_text.split("\n", 1)[0].strip()
    if not first_line.startswith("/"):
        return None
    parts = first_line.split(None, 1)
    return {
        "command": parts[0][1:],
        "args": parts[1] if len(parts) > 1 else "",
        "full_command": first_line,
    }


def _parse_args(tool_name: str, args_str: str) -> dict[str, Any]:
    """Parse a /command argument string into a kwargs dict for the tool."""
    if not args_str:
        return {}
    if tool_name in _STRING_ARG_TOOLS:
        return {_STRING_ARG_TOOLS[tool_name]: args_str}
    try:
        parsed = json.loads(args_str)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return {"query": args_str}


def execute_command(
    command_info: dict[str, str],
    session_id: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """Resolve and execute a detected command.

    Returns (executed_tool_name, raw_tool_result_dict).
    """
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
