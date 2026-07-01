"""Legacy tool-markup cleanup helpers for historical model output.

This module strips old `<command>...</command>` and `<tool>...</tool>`
blocks from archived assistant text. Native function calling is the
production tool architecture; this file only keeps compatibility cleanup
helpers for stale markup that may still appear in stored content.
"""

from __future__ import annotations

import re

from app.logging_config import get_logger

log = get_logger(__name__)

_REGEX_INPUT_LIMIT = 100000
_MAX_TOOL_BLOCKS = 3
_TOOL_OPEN_TOOLS = ("<command>", "<tool>")
_TOOL_CLOSE_TOOLS = ("</command>", "</tool>")

TOOL_ALIASES: dict[str, str] = {
    "imagine": "image_generate",
    "image_generate": "image_generate",
    "http_request": "http_request",
    "request": "http_request",
    "ask-rei": "ask_rei",
}

_GENERATED_IMAGE_SRC = re.compile(r'src="(static/generated_images/[^"]+)"')
_MARKDOWN_IMAGE_PATH = re.compile(
    r"!\[[^\]]{0,200}\]\((static/|uploads/|generated_images/)[^)]{1,200}\)"
)
_MARKDOWN_IMAGE_ANY = re.compile(r"!\[[^\]]{0,200}\]\(([^)]{1,200})\)")

IMAGE_SHORTCUT_WARNING = (
    "\n\nImage output detected via incorrect method. "
    "Please use native function calling or the image tool contract instead."
)


def _match_open_tag(stripped: str) -> tuple[int, int, int] | None:
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
    for close_tag in _TOOL_CLOSE_TOOLS:
        idx = line.find(close_tag)
        if idx != -1:
            return idx, len(close_tag)
    return None


def strip_legacy_tool_blocks(text: str) -> tuple[list[str], str]:
    """Strip legacy tool blocks from assistant text.

    Returns legacy command strings plus the cleaned text.
    This is a compatibility cleanup utility only; it is not the
    production tool protocol.
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
            after_open = stripped[open_len:]
            before_close = after_open[:close_idx].strip()
            after_close = after_open[close_idx + close_len :].strip()
            if not after_close and before_close:
                matches.append(before_close)
            lines[i] = ""
        else:
            after_open = stripped[open_len:].strip()
            if after_open:
                content_lines.append(after_open)
            j = i + 1
            while j < len(lines):
                inner_line = lines[j]
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
                content_lines.append(inner_line.strip())
                j += 1

            if found_close and content_lines:
                content = "\n".join(content_lines).strip()
                if content:
                    matches.append(content)

        i += 1

    matches = matches[:_MAX_TOOL_BLOCKS]

    cleaned_lines: list[str] = []
    prev_empty = False
    for line in "\n".join(lines).split("\n"):
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

    return matches, "\n".join(cleaned_lines)


def has_legacy_tool_markup(text: str) -> bool:
    """Check if text contains any legacy tool blocks."""
    if not text:
        return False
    if len(text) > _REGEX_INPUT_LIMIT:
        text = text[:_REGEX_INPUT_LIMIT]

    for open_tag, close_tag in zip(_TOOL_OPEN_TOOLS, _TOOL_CLOSE_TOOLS):
        if open_tag in text and close_tag in text:
            return True

    for line in text.split("\n"):
        if _match_open_tag(line.strip()) is not None:
            return True

    return False


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
