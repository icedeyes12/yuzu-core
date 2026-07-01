from __future__ import annotations

from textual.message import Message
from textual.widgets import Input


class InputBox(Input):
    """
    Input widget for user message entry.

    Emits MessageSubmitted when user presses Enter.
    Automatically clears after submission.
    """

    DEFAULT_CSS = """
    InputBox {
        dock: bottom;
        height: auto;
        margin: 1 2;
        padding: 1;
        border: solid $primary;
        background: transparent;
    }
    InputBox:focus {
        border: double $accent;
    }
    """

    class MessageSubmitted(Message):
        """Message emitted when user submits input."""

        def __init__(self, content: str) -> None:
            self.content = content
            super().__init__()

    def on_key(self, event) -> None:  # type: ignore[override]
        """Handle Enter key for message submission."""
        if event.key == "enter" and self.value.strip():
            self._submit()

    def _submit(self) -> None:
        """Emit MessageSubmitted and clear input."""
        content = self.value.strip()
        if content:
            self.post_message(self.MessageSubmitted(content))
            self.value = ""
