"""Visual context helpers — DEPRECATED.

Image embedding is now handled entirely in ``app.prompts.build_messages()``
which converts ``image_paths`` on history messages to base64 ``image_url``
blocks at build time.  This module is retained as a stub so existing imports
do not break; all functions are no-ops and will be removed in a future
release.
"""

from __future__ import annotations


def store_visual_context(session_id: str, image_base64: str, mime: str) -> None:
    """Deprecated — no-op."""


def consume_visual_context(
    session_id: str, is_tool_loop: bool = False,
) -> tuple[str | None, str | None]:
    """Deprecated — always returns (None, None)."""
    return None, None


def has_visual_reference(text: str) -> bool:
    """Deprecated — always returns False."""
    return False
