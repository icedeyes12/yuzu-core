# FILE: cli/widgets/session_list.py
# DESCRIPTION: Session sidebar widget for switching between chat sessions.

from __future__ import annotations

from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option


class SessionSelected(Message):
    """Message emitted when a session is selected from the list."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__()


class SessionList(OptionList):
    """
    Sidebar widget displaying available chat sessions.
    
    Emits SessionSelected when user clicks or presses Enter on a session.
    """

    DEFAULT_CSS = """
    SessionList {
        width: 25;
        dock: left;
        height: 100%;
        background: $surface;
        border-right: solid $primary;
    }
    SessionList:focus {
        border-right: double $accent;
    }
    """

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        self._active_session_id: str | None = None
        super().__init__(
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
        )

    def load_sessions(self, sessions: list[dict]) -> None:
        """
        Populate the session list from backend data.
        
        Args:
            sessions: List of session dictionaries with 'id' and 'name' keys
        """
        self.clear_options()
        
        if not sessions:
            # Create default session if none exist
            self.add_option(Option("default", id="default"))
            self._active_session_id = "default"
            return
        
        for session in sessions:
            session_id = session.get("id", "unknown")
            session_name = session.get("name") or session_id
            self.add_option(Option(str(session_name), id=str(session_id)))
        
        # Set first session as active
        if sessions:
            self._active_session_id = str(sessions[0].get("id", "default"))

    def set_active_session(self, session_id: str) -> None:
        """Mark the specified session as active."""
        self._active_session_id = session_id
        # Highlight selection
        for i, option in enumerate(self._options):
            if option.id == session_id:
                self.highlighted = i
                break

    @property
    def active_session_id(self) -> str:
        """Return the current session_id, defaulting to 'default'."""
        return self._active_session_id or "default"

    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle session selection and emit SessionSelected message."""
        session_id = str(event.option.id) if event.option.id else "default"
        self._active_session_id = session_id
        self.post_message(SessionSelected(session_id))
