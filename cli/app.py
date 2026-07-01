from __future__ import annotations

import asyncio
import httpx
import time
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.widgets import Header, Footer, Static

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
    - Left sidebar: SessionList (toggleable)
    - Right: ChatLog + InputBox

    Backend communication via HTTP only (no DB imports).
    """

    CSS_PATH = "styles/app.tcss"
    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+s", "toggle_session_sidebar", "Sessions", show=True),
        Binding("tab", "focus_next", "Next", show=False),
        Binding("shift+tab", "focus_previous", "Prev", show=False),
    ]

    def __init__(self, backend_url: str = "http://localhost:5000") -> None:
        super().__init__()
        self.backend_url = backend_url
        self.client = YuzuClient(base_url=backend_url)
        self._processing = False
        self._session_id: int = 1
        self._sidebar_visible = False
        self._last_response_widget: Static | None
        self._response_start_time: float | None = None
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

        # Detect screen size and apply desktop classes if needed
        self._apply_responsive_layout()

        # Use call_later to run async init in background
        asyncio.create_task(self._init_app())
        log.debug("Init task scheduled")

    def _apply_responsive_layout(self) -> None:
        """Apply desktop or mobile classes based on terminal width."""
        try:
            # Get terminal width (fallback to 80 if detection fails)
            import shutil

            width = shutil.get_terminal_size().columns

            log.debug(f"Terminal width: {width} columns")

            # Desktop mode: width >= 80 columns
            if width >= 80:
                log.info("Applying desktop layout (width >= 80)")
                main_layout = self.query_one("#main-layout")
                main_layout.add_class("desktop")

                sidebar = self.query_one(SessionList)
                sidebar.add_class("desktop")
                sidebar.display = True  # Always visible on desktop
                self._sidebar_visible = True

                chat_container = self.query_one("#chat-container")
                chat_container.add_class("desktop")
            else:
                log.info("Applying mobile layout (width < 80)")
                # Mobile mode: sidebar hidden by default, toggleable
                self._sidebar_visible = False

        except Exception as e:
            log.warning(
                f"Failed to detect terminal size: {e}, defaulting to mobile layout"
            )
            self._sidebar_visible = False

    async def _init_app(self) -> None:
        """Perform health check, load sessions, and load initial history."""
        try:
            # Connect client
            await self.client.connect()

            # Health check
            log.info("Running health check...")
            is_healthy = await self.client.check_health()

            # Update UI via call_later (we're in async context)
            self.call_later(self._update_health_status, is_healthy)

            if not is_healthy:
                return

            log.info("Health check passed")

            # Load sessions
            sessions = await self.client.list_sessions()
            self.call_later(self._update_sessions, sessions)

            log.info(f"Loaded {len(sessions)} sessions, active: {self._session_id}")

            # Load history for active session
            await self._load_history()

        except Exception as e:
            log.error(f"Init failed: {e}")
            self.call_later(self._show_error, f"Init error: {e}")

    def _update_health_status(self, is_healthy: bool) -> None:
        """Update UI with health check result (called from main thread)."""
        chat_log = self.query_one(ChatLog)
        if is_healthy:
            chat_log.add_message("system", f"✓ Connected to {self.backend_url}")
        else:
            chat_log.add_message(
                "system", f"⚠️  Backend unreachable: {self.backend_url}"
            )

    def _update_sessions(self, sessions: list) -> None:
        """Update session list UI (called from main thread)."""
        session_list = self.query_one(SessionList)
        session_list.load_sessions(sessions)

        if sessions:
            self._session_id = sessions[0].get("id", 1)
            session_list.set_active_session(self._session_id)
        else:
            self._session_id = 1

    def _show_error(self, message: str) -> None:
        """Show error in chat log (called from main thread)."""
        chat_log = self.query_one(ChatLog)
        chat_log.add_message("system", f"❌ {message}")

    async def _load_history(self) -> None:
        """Load chat history for current session into ChatLog."""
        try:
            history = await self.client.get_history(self._session_id)
            self.call_later(self._display_history, history)
            log.info(f"Loaded {len(history)} messages for session {self._session_id}")

        except Exception as e:
            log.error(f"Failed to load history: {e}")
            self.call_later(self._show_error, f"Could not load history: {e}")

    def _display_history(self, history: list) -> None:
        """Display history in chat log (called from main thread)."""
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

    def on_input_box_message_submitted(self, event: InputBox.MessageSubmitted) -> None:
        """Handle message submission from InputBox."""
        if self._processing:
            log.debug("Ignoring submit - already processing")
            return

        message = event.content
        chat_log = self.query_one(ChatLog)

        # Local echo
        chat_log.add_message("you", message)
        log.info(f"Message submitted: {message[:50]}...")

        # Send to backend in background task
        asyncio.create_task(self._send_message(message))

    async def _send_message(self, message: str) -> None:
        """Send message to backend and handle streaming response."""
        self._processing = True

        # Switch to current session first
        try:
            await self.client.switch_session(self._session_id)
            log.info(f"Switched to session {self._session_id}")
        except Exception as e:
            log.error(f"Failed to switch session: {e}")
            self.call_later(self._show_error, f"Could not switch session: {e}")
            self._processing = False
            return

        # Disable input
        self.call_later(self._set_input_state, False)

        # Add placeholder message
        self.call_later(self._add_response_placeholder)

        full_response = ""

        try:
            # Stream response
            async for chunk in self.client.stream_message(message):
                full_response += chunk
                self.call_later(self._update_response, full_response)

            log.info(f"Response received: {len(full_response)} chars")

        except httpx.ConnectError:
            self.call_later(self._update_response, "❌ Connection failed")
            log.error("Connection error")

        except httpx.TimeoutException:
            self.call_later(self._update_response, "❌ Request timed out")
            log.error("Timeout")

        except Exception as e:
            self.call_later(self._update_response, f"❌ Error: {e}")
            log.error(f"Send error: {e}")

        finally:
            # Re-enable input
            self._processing = False
            self.call_later(self._set_input_state, True)

    def _set_input_state(self, enabled: bool) -> None:
        """Enable/disable input box (called from main thread)."""
        input_box = self.query_one(InputBox)
        if enabled:
            input_box.disabled = False
            input_box.styles.opacity = 1.0
            input_box.focus()
        else:
            input_box.disabled = True
            input_box.styles.opacity = 0.5

    def _add_response_placeholder(self) -> None:
        """Add typing indicator with spinner."""
        self._response_start_time = time.time()
        chat_log = self.query_one(ChatLog)
        # Typing indicator with animated dots
        self._last_response_widget = chat_log.add_message("yuzu", "⏳ Typing...")

        # Schedule spinner animation updates
        self._update_spinner(0)

    def _update_spinner(self, count: int) -> None:
        """Animate typing indicator spinner."""
        if not self._processing or count > 30:  # Max 30 updates (30s timeout)
            return

        spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        spinner = spinner_chars[count % len(spinner_chars)]
        elapsed = (
            time.time() - self._response_start_time if self._response_start_time else 0
        )

        if self._last_response_widget:
            chat_log = self.query_one(ChatLog)
            chat_log.update_message(
                self._last_response_widget,
                "yuzu",
                f"{spinner} Processing... ({elapsed:.1f}s)",
            )

        # Schedule next update (every 0.1s)
        self.call_later(self._update_spinner, count + 1)

    def _update_response(self, content: str) -> None:
        """Update response with elapsed time."""
        if self._last_response_widget:
            # Calculate elapsed time
            if self._response_start_time:
                elapsed = time.time() - self._response_start_time
                # Show elapsed time in first update
                if not content.startswith(("⏱", " <")):
                    content = f"⏱ {elapsed:.1f}s\n\n{content}"
                    self._response_start_time = None

            chat_log = self.query_one(ChatLog)
            chat_log.update_message(self._last_response_widget, "yuzu", content)

    def on_session_list_session_selected(self, event: SessionSelected) -> None:
        """Handle session selection: switch session, reload history."""
        session_id = event.session_id

        if session_id == self._session_id:
            return  # No change

        log.info(f"Session selected: {session_id}")
        self._session_id = session_id

        # Update UI
        session_list = self.query_one(SessionList)
        session_list.set_active_session(session_id)

        # Reload history in background
        asyncio.create_task(self._load_history())

    def action_toggle_session_sidebar(self) -> None:
        """Toggle session sidebar visibility (for mobile layout)."""
        try:
            import shutil

            width = shutil.get_terminal_size().columns

            # On desktop (>= 80 cols), sidebar is always visible
            if width >= 80:
                log.debug("Desktop mode: sidebar toggle ignored (always visible)")
                return

            # Mobile mode: toggle sidebar
            sidebar = self.query_one(SessionList)
            self._sidebar_visible = not self._sidebar_visible

            if self._sidebar_visible:
                sidebar.add_class("visible")
                sidebar.focus()
            else:
                sidebar.remove_class("visible")
                self.query_one(InputBox).focus()

            log.debug(f"Sidebar visible: {self._sidebar_visible}")
        except Exception as e:
            log.error(f"Failed to toggle sidebar: {e}")


def run_app(backend_url: str = "http://localhost:5000") -> None:
    """Entry point for the Yuzu Companion TUI."""
    app = YuzuTUI(backend_url=backend_url)
    app.run()


if __name__ == "__main__":
    run_app()
