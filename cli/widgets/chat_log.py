# FILE: cli/widgets/chat_log.py
# DESCRIPTION: Scrollable chat history widget with Markdown rendering.

from __future__ import annotations

from rich.markdown import Markdown
from textual.containers import ScrollableContainer
from textual.widgets import Static


class ChatLog(ScrollableContainer):
    """
    Scrollable container for chat messages.
    
    Displays messages with Markdown rendering and auto-scrolls to bottom.
    """

    DEFAULT_CSS = """
    ChatLog {
        height: 1fr;
        width: 100%;
        padding: 1;
        background: $surface;
    }
    """

    def add_message(self, role: str, content: str) -> None:
        """
        Append a new message to the chat log.
        
        Args:
            role: Message role (user/assistant/system)
            content: Message content (Markdown supported)
        """
        message_widget = Static(
            Markdown(f"**{role}**: {content}"),
            classes=f"message {role}",
        )
        self.mount(message_widget)
        self.scroll_end(animate=False)

    def clear_messages(self) -> None:
        """Remove all messages from the chat log."""
        for child in list(self.children):
            child.remove()
