# FILE: cli/app.py
# DESCRIPTION: Main Textual TUI application for Yuzu Companion.
#              Full layout: sidebar + chat + input with session switching.

from __future__ import annotations

import httpx
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.widgets import Header, Footer

from cli.client import YuzuClient
from cli.widgets import (
    ChatLog,
    InputBox,
    SessionList,
    SessionSelected,
)
from app.logging_config import get_logger

log = get_logger(__name__)


class YuzuTUI(App):
    """
    Main Textual TUI application with persistent chat interface.

    Layout:
    - Left sidebar: SessionList
    - Right: ChatLog + InputBox

    Backend communication via HTTP only (no DB imports).
    """

    CSS_PATH = "styles/app.tcss"
    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+h", "toggle_help", "Help", show=True),
        Binding("tab", "focus_next", "Next", show=False),
        Binding("shift+tab", "focus_previous", "Prev", show=False),
    ]

    def __init__(self, backend_url: str = "http://localhost:5000") -> None:
        super().__init__()
        self.backend_url = backend_url
        self.client = YuzuClient(base_url=backend_url)
        self._processing = False
        self._session_id: str = "default"
        log.info(f"YuzuTUI initialized with backend: {backend_url}")

    def compose(self) -> ComposeResult:
        """Compose the main application layout."""
        yield Header(name="Yuzu Companion")
        with Horizontal(id="main-layout"):
            yield SessionList(id="sidebar")
            with Container(id="chat-container"):
                yield ChatLog(id="chat-log")
                yield InputBox(id="input-box")
        yield Footer()

    def on_mount(self) -> None:
        """On mount: health check, load sessions, load history."""
        log.info("YuzuTUI mounted and ready")
        self.title = "Yuzu Companion"
        self.sub_title = f"Backend: {self.backend_url}"

        # Run initialization via set_timer to avoid blocking
        self.set_timer(0.1, self._run_init_app)

    def _run_init_app(self) -> None:
        """Start the init worker."""
        self._init_app()

    async def _init_app(self) -> None:
        """Perform health check, load sessions, and load initial history."""
        try:
            # Connect client
            await self.client.connect()
            
            # Health check
            log.info("Running health check...")
            is_healthy = await self.client.check_health()
            chat_log = self.query_one(ChatLog)

            if not is_healthy:
                chat_log.add_message(
                    "system", f"⚠️  Backend unreachable: {self.backend_url}"
                )
                return

            chat_log.add_message("system", f"✓ Connected to {self.backend_url}")
            log.info("Health check passed")

            # Load sessions
            session_list = self.query_one(SessionList)
            sessions = await self.client.list_sessions()
            session_list.load_sessions(sessions)

            # Set initial session_id
            if sessions:
                self._session_id = str(sessions[0].get("id", "default"))
                session_list.set_active_session(self._session_id)
            else:
                self._session_id = "default"

            log.info(f"Loaded {len(sessions)} sessions, active: {self._session_id}")

            # Load history for active session
            await self._load_history()

        except Exception as e:
            log.error(f"Init failed: {e}")
            chat_log = self.query_one(ChatLog)
            chat_log.add_message("system", f"❌ Init error: {e}")

    async def _load_history(self) -> None:
        """Load chat history for current session into ChatLog."""
        try:
            history = await self.client.get_history(self._session_id)
            chat_log = self.query_one(ChatLog)
            chat_log.clear_messages()

            if not history:
                chat_log.add_message("system", "No previous messages")
                return

            for msg in history:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if role == "user":
                    chat_log.add_message("you", content)
                elif role == "assistant":
                    chat_log.add_message("yuzuki", content)
                else:
                    chat_log.add_message(role, content)

            log.info(f"Loaded {len(history)} messages for session {self._session_id}")

        except Exception as e:
            log.error(f"Failed to load history: {e}")
            chat_log = self.query_one(ChatLog)
            chat_log.add_message("system", f"⚠️  Could not load history: {e}")

    def on_message_submitted(self, event: InputBox.MessageSubmitted) -> None:
        """Handle message submission from InputBox."""
        if self._processing:
            return

        message = event.message
        chat_log = self.query_one(ChatLog)

        # Local echo
        chat_log.add_message("you", message)
        log.info(f"Message submitted: {message[:50]}...")

        # Send to backend via set_timer
        self.set_timer(0.1, lambda: self._send_message(message))

    async def _send_message(self, message: str) -> None:
        """Send message to backend and handle streaming response."""
        self._processing = True
        chat_log = self.query_one(ChatLog)
        input_box = self.query_one(InputBox)

        # Disable input during processing
        input_box.disabled = True
        input_box.styles.opacity = 0.5

        # Placeholder for response
        chat_log.add_message("yuzuki", "")
        full_response = ""

        try:
            # Stream response
            async for chunk in self.client.stream_message(self._session_id, message):
                full_response += chunk
                chat_log.update_last_message("yuzuki", full_response)

            log.info(f"Response received: {len(full_response)} chars")

        except httpx.ConnectError:
            chat_log.update_last_message("yuzuki", "❌ Connection failed")
            log.error("Connection error")

        except httpx.TimeoutException:
            chat_log.update_last_message("yuzuki", "❌ Request timed out")
            log.error("Timeout")

        except Exception as e:
            chat_log.update_last_message("yuzuki", f"❌ Error: {e}")
            log.error(f"Send error: {e}")

        finally:
            # Re-enable input
            self._processing = False
            input_box.disabled = False
            input_box.styles.opacity = 1.0
            input_box.focus()

    def on_session_selected(self, event: SessionSelected) -> None:
        """Handle session selection: switch session, reload history."""
        session_id = event.session_id

        if session_id == self._session_id:
            return  # No change

        log.info(f"Session selected: {session_id}")
        self._session_id = session_id

        # Update UI
        session_list = self.query_one(SessionList)
        session_list.set_active_session(session_id)

        # Reload history via set_timer
        self.set_timer(0.1, self._load_history)

    def action_toggle_help(self) -> None:
        """Toggle help panel."""
        self.bell()


def run_app(backend_url: str = "http://localhost:5000") -> None:
    """Entry point for the Yuzu Companion TUI."""
    app = YuzuTUI(backend_url=backend_url)
    app.run()


if __name__ == "__main__":
    run_app()