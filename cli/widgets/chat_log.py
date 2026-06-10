# FILE: cli/widgets/chat_log.py
# DESCRIPTION: Scrollable chat history widget with Markdown rendering.

from __future__ import annotations

import re
from rich.markdown import Markdown
from textual.containers import ScrollableContainer
from textual.widgets import Static


class ChatLog(ScrollableContainer):
    """
    Scrollable container for chat messages.

    Displays messages with Markdown rendering and auto-scrolls to bottom.
    Supports streaming updates for assistant messages.
    """

    DEFAULT_CSS = """
    ChatLog {
        height: 1fr;
        width: 100%;
        padding: 1;
        background: transparent;
    }
    .message {
        margin-bottom: 1;
    }
    """

    def add_message(self, role: str, content: str) -> Static:
        """
        Append a new message to the chat log.

        Args:
            role: Message role (user/assistant/system)
            content: Message content (Markdown supported)

        Returns:
            The created Static widget for further updates.
        """
        display_content = self._filter_hidden_tags(content)
        message_widget = Static(
            Markdown(f"**{role}**: {display_content}"),
            classes=f"message {role}",
        )
        self.mount(message_widget)
        self.scroll_end(animate=False)
        return message_widget

    def update_message(self, widget: Static, role: str, content: str) -> None:
        """
        Update an existing message widget with new content.

        Used for streaming updates.

        Args:
            widget: The Static widget to update
            role: Message role (user/assistant/system)
            content: New message content
        """
        display_content = self._filter_hidden_tags(content)
        widget.update(Markdown(f"**{role}**: {display_content}"))
        self.scroll_end(animate=False)

    def clear_messages(self) -> None:
        """Remove all messages from the chat log."""
        for child in list(self.children):
            child.remove()

    def filter_hidden_tags(self, text: str) -> str:
        """
        Filter out hidden tags from the text.

        Args:
            text: The text to filter

        Returns:
            The filtered text
        """
        return re.sub(r"<[^>]+>", "", text)