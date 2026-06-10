# FILE: cli/app.py
# DESCRIPTION: Main Textual TUI application for Yuzu Companion.

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static


class YuzuTUI(App):
    """
    Main Textual TUI application for Yuzu Companion.
    
    Thin-client that communicates with the FastAPI backend via HTTP.
    """

    CSS_PATH = None
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+h", "check_health", "Check Health"),
    ]

    def __init__(self, backend_url: str = "http://localhost:5000") -> None:
        super().__init__()
        self.backend_url = backend_url

    def compose(self) -> ComposeResult:
        """Compose the main application layout."""
        yield Header()
        yield Static(
            "Checking backend connection...",
            id="status",
        )
        yield Footer()

    async def on_mount(self) -> None:
        """Called when the app is mounted. Perform health check."""
        from cli.client import YuzuClient

        status_widget = self.query_one("#status", Static)

        async with YuzuClient(self.backend_url) as client:
            healthy = await client.check_health()

        if healthy:
            status_widget.update(
                f"✓ Connected to backend: {self.backend_url}\n\n"
                "Press Ctrl+H to recheck, Ctrl+C to quit."
            )
        else:
            status_widget.update(
                f"✗ Backend offline: {self.backend_url}\n\n"
                "Start the server with: uvicorn main:app --host 0.0.0.0 --port 5000\n\n"
                "Press Ctrl+H to retry, Ctrl+C to quit."
            )

    def action_check_health(self) -> None:
        """Re-check backend health."""
        self.call_after_refresh(self._recheck_health)

    async def _recheck_health(self) -> None:
        """Perform health check and update status."""
        from cli.client import YuzuClient

        status_widget = self.query_one("#status", Static)
        status_widget.update("Rechecking backend connection...")

        async with YuzuClient(self.backend_url) as client:
            healthy = await client.check_health()

        if healthy:
            status_widget.update(
                f"✓ Connected to backend: {self.backend_url}\n\n"
                "Press Ctrl+H to recheck, Ctrl+C to quit."
            )
        else:
            status_widget.update(
                f"✗ Backend offline: {self.backend_url}\n\n"
                "Start the server with: uvicorn main:app --host 0.0.0.0 --port 5000\n\n"
                "Press Ctrl+H to retry, Ctrl+C to quit."
            )


def run_app() -> None:
    """Entry point for the Yuzu TUI application."""
    import os
    
    backend_url = os.getenv("YUZU_BACKEND_URL", "http://localhost:5000")
    app = YuzuTUI(backend_url=backend_url)
    app.run()


if __name__ == "__main__":
    run_app()
