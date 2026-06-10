# FILE: cli/app.py
# DESCRIPTION: Main Textual TUI application for Yuzu Companion.

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer
from textual.binding import Binding

from .widgets.chat_log import ChatLog
from .widgets.input_box import InputBox
from .client import YuzuClient


class YuzuTUI(App):
    """
    Main TUI application for Yuzu Companion.
    
    Persistent chat client communicating via HTTP with FastAPI backend.
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear", "Clear", show=True),
        Binding("f1", "toggle_help", "Help", show=True),
    ]

    def __init__(self, backend_url: str = "http://localhost:5000") -> None:
        super().__init__()
        self.backend_url = backend_url
        self.client = YuzuClient(backend_url)

    def compose(self) -> ComposeResult:
        """Compose the main application layout."""
        yield Header(name="Yuzu Companion")
        yield ChatLog(id="chat-log")
        yield InputBox(id="input-box", placeholder="Type a message...")
        yield Footer()

    def on_mount(self) -> None:
        """Initialize app after mounting."""
        self.title = "Yuzu Companion"
        self.sub_title = f"Backend: {self.backend_url}"

    def on_input_box_message_submitted(self, event: InputBox.MessageSubmitted) -> None:
        """Handle message submission from InputBox (local echo)."""
        chat_log = self.query_one(ChatLog)
        chat_log.add_message("user", event.content)

    def action_clear(self) -> None:
        """Clear all messages from the chat log."""
        chat_log = self.query_one(ChatLog)
        chat_log.clear_messages()

    def action_toggle_help(self) -> None:
        """Toggle help panel (placeholder)."""
        self.bell()


def run_app() -> None:
    """Entry point for the TUI application."""
    import os

    # Get backend URL from environment or use default
    backend_url = os.getenv("YUZU_BACKEND_URL", "http://localhost:5000")
    
    app = YuzuTUI(backend_url=backend_url)
    app.run()


if __name__ == "__main__":
    run_app()
