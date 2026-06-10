# FILE: cli/app.py
# DESCRIPTION: Main Textual TUI application for Yuzu Companion.
#              Provides persistent chat UI connected to FastAPI backend via HTTP.

from __future__ import annotations

import httpx

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Header, Footer

from cli.client import YuzuClient
from cli.widgets import ChatLog, InputBox, MessageSubmitted


class YuzuTUI(App):
    """
    Main TUI application for Yuzu Companion.
    
    Persistent chat client that communicates with the FastAPI backend
    via HTTP. Never imports database models or internal services.
    """

    CSS_PATH = None
    BINDINGS = []
    DEFAULT_SESSION_ID = "default"

    def __init__(self, backend_url: str = "http://localhost:5000") -> None:
        super().__init__()
        self.backend_url = backend_url
        self.client = YuzuClient(backend_url)

    def compose(self) -> ComposeResult:
        """Compose the main application layout."""
        yield Header(name="Yuzu Companion")
        yield Container(
            ChatLog(id="chat-log"),
            InputBox(id="input-box"),
            id="main-container",
        )
        yield Footer()

    async def on_mount(self) -> None:
        """Initialize client, check health, and load history."""
        await self.client.connect()
        
        chat_log = self.query_one("#chat-log", ChatLog)
        input_box = self.query_one("#input-box", InputBox)
        
        # Health check
        chat_log.write("[dim]Connecting to backend...[/dim]")
        is_healthy = await self.client.check_health()
        
        if not is_healthy:
            chat_log.write("[red]❌ Backend unreachable. Start the server and restart TUI.[/red]")
            input_box.disabled = True
            return
        
        chat_log.write("[green]✓ Connected to backend[/green]")
        
        # Load chat history
        await self._load_history()

    async def on_unmount(self) -> None:
        """Cleanup on app exit."""
        await self.client.disconnect()

    async def on_message_submitted(self, event: MessageSubmitted) -> None:
        """Handle message submission from InputBox."""
        message = event.message.strip()
        if not message:
            return
        
        chat_log = self.query_one("#chat-log", ChatLog)
        input_box = self.query_one("#input-box", InputBox)
        
        # Disable input during processing to prevent spam
        input_box.disabled = True
        
        # Display user message immediately
        chat_log.write(f"[bold cyan]You:[/bold cyan] {message}")
        
        # Stream response from backend
        response_text = ""
        try:
            async for chunk in self.client.stream_message(self.DEFAULT_SESSION_ID, message):
                if chunk:
                    response_text += chunk
                    # Clear and update to show streaming progress
                    chat_log.write(f"[bold magenta]Yuzuki:[/bold magenta] {response_text}▌", overwrite_last=True)
            
            # Final response without cursor
            if response_text:
                chat_log.write(f"[bold magenta]Yuzuki:[/bold magenta] {response_text}", overwrite_last=True)
                
        except httpx.ConnectError:
            chat_log.write("[red]❌ Connection lost. Backend may have restarted.[/red]")
        except httpx.TimeoutException:
            chat_log.write("[red]⏱️ Request timed out. Try again.[/red]")
        except Exception as e:
            chat_log.write(f"[red]❌ Error: {type(e).__name__}: {e}[/red]")
        finally:
            # Re-enable input
            input_box.disabled = False
            input_box.clear()
            input_box.focus()

    async def _load_history(self) -> None:
        """Load chat history from backend."""
        chat_log = self.query_one("#chat-log", ChatLog)
        
        try:
            messages = await self.client.get_history(self.DEFAULT_SESSION_ID)
            
            if messages:
                chat_log.write("[dim]--- Previous Context ---[/dim]")
                
                for msg in messages:
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    
                    if not content:
                        continue
                    
                    # Format based on role
                    role_style = {
                        "user": "[bold cyan]You:[/bold cyan]",
                        "assistant": "[bold magenta]Yuzuki:[/bold magenta]",
                    }.get(role, f"[dim]{role}:[/dim]")
                    
                    chat_log.write(f"{role_style} {content}")
                
                chat_log.write("[dim]--- End of History ---[/dim]")
                
        except Exception as e:
            chat_log.write(f"[yellow]⚠️ Could not load history: {type(e).__name__}[/yellow]")


def run_app() -> None:
    """Entry point for the TUI application."""
    import sys
    
    backend_url = sys.argv[1] if len(sys) > 1 else "http://localhost:5000"
    app = YuzuTUI(backend_url)
    app.run()


if __name__ == "__main__":
    run_app()
