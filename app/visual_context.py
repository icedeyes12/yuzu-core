# FILE: app/visual_context.py
# DESCRIPTION: Persistent visual context buffer for follow-up image references.
#              Stores the last processed image as base64 for N follow-up turns
#              so the model can compare or reference it without a new tool call.

import threading
import re

# ── Visual Context Buffer ─────────────────────────────────────────────────────

_visual_context_buffer: dict = {}  # session_id -> {"base64": str, "mime": str, "turns_left": int}
_visual_context_lock = threading.Lock()
_VISUAL_CONTEXT_TURNS = 3


def store_visual_context(session_id: int, image_base64: str, mime: str) -> None:
    """Store a visual context snapshot for follow-up turns. Thread-safe."""
    with _visual_context_lock:
        _visual_context_buffer[session_id] = {
            "base64": image_base64,
            "mime": mime,
            "turns_left": _VISUAL_CONTEXT_TURNS,
        }


def consume_visual_context(session_id: int) -> tuple[str | None, str | None]:
    """Return stored visual context if available and decrement turn counter.
    
    Returns (base64, mime) or (None, None). Thread-safe.
    """
    with _visual_context_lock:
        ctx = _visual_context_buffer.get(session_id)
        if not ctx or ctx["turns_left"] <= 0:
            _visual_context_buffer.pop(session_id, None)
            return None, None
        ctx["turns_left"] -= 1
        if ctx["turns_left"] <= 0:
            _visual_context_buffer.pop(session_id, None)
        return ctx["base64"], ctx["mime"]


# ── Visual Reference Detection ───────────────────────────────────────────────

_VISUAL_REF_PATTERNS = re.compile(
    r'(?:yang tadi|yang sebelumnya|tadi|bedanya|beda apa|compare|'
    r'bandingin|foto tadi|gambar tadi|image before|the previous|earlier image|'
    r'dari tadi|yang barusan)',
    re.IGNORECASE,
)


def has_visual_reference(text: str) -> bool:
    """Detect if the user message references a previous image."""
    return bool(_VISUAL_REF_PATTERNS.search(text))
