from __future__ import annotations

import asyncio
import os

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from cli.client import StreamEvent, YuzuClient

DEFAULT_BACKEND_URL = "http://localhost:5000"
console = Console()


class YuzuREPL:
    """Inline terminal REPL for the HTTP/SSE Yuzu Companion API."""

    def __init__(self, backend_url: str | None = None) -> None:
        self.backend_url = backend_url or os.getenv(
            "YUZU_BACKEND_URL", DEFAULT_BACKEND_URL
        )
        history_path = os.getenv("YUZU_CLI_HISTORY", "~/.yuzu_history")
        self.prompt = PromptSession(
            history=FileHistory(os.path.expanduser(history_path))
        )
        self.client = YuzuClient(self.backend_url)
        self.session_id: str | None = None
        self.running = True

    async def start(self) -> None:
        await self.client.connect()
        try:
            if not await self.client.check_health():
                console.print(f"[yellow]Backend tidak merespons:[/] {self.backend_url}")
                return
            console.print(
                Panel(
                    "[bold]Yuzu Companion[/bold]\n"
                    f"Connected to {self.backend_url}\n"
                    "Ketik [cyan]/help[/] untuk perintah.",
                    border_style="cyan",
                )
            )
            await self._select_initial_session()
            await self._loop()
        finally:
            await self.client.disconnect()

    async def _select_initial_session(self) -> None:
        sessions = await self.client.list_sessions()
        if not sessions:
            console.print("[dim]Belum ada session aktif.[/]")
            return
        first = sessions[0].get("id")
        if isinstance(first, (str, int)):
            self.session_id = str(first)
            console.print(f"[dim]Session aktif: {self.session_id}[/]")

    async def _loop(self) -> None:
        while self.running:
            try:
                with patch_stdout(raw=True):
                    message = await self.prompt.prompt_async("You › ")
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            message = message.strip()
            if not message:
                continue
            if await self._handle_command(message):
                continue
            await self._send_message(message)

    async def _handle_command(self, message: str) -> bool:
        command, _, argument = message.partition(" ")
        command = command.lower()
        if command in {"/quit", "/exit", "/q"}:
            self.running = False
            return True
        if command == "/help":
            console.print(
                "[cyan]/sessions[/] list sessions · "
                "[cyan]/switch <id>[/] switch session · "
                "[cyan]/quit[/] exit"
            )
            return True
        if command == "/sessions":
            await self._show_sessions()
            return True
        if command == "/switch":
            await self._switch_session(argument.strip())
            return True
        return False

    async def _show_sessions(self) -> None:
        sessions = await self.client.list_sessions()
        if not sessions:
            console.print("[dim]Tidak ada session.[/]")
            return
        for session in sessions:
            session_id = session.get("id", "?")
            name = session.get("name", session.get("title", "Untitled"))
            marker = "*" if str(session_id) == self.session_id else " "
            console.print(f"[dim]{marker}[/] {session_id}  {name}")

    async def _switch_session(self, session_id: str) -> None:
        if not session_id:
            console.print("[yellow]Usage: /switch <session-id>[/]")
            return
        await self.client.switch_session(session_id)
        self.session_id = session_id
        console.print(f"[dim]Switched to session {session_id}.[/]")

    async def _send_message(self, message: str) -> None:
        console.print("[bold green]You[/]")
        console.print(message)
        console.print("[bold magenta]Yuzuki[/]")
        response_parts: list[str] = []
        tool_lines: list[Text] = []
        live_render = Group(Markdown(""), *tool_lines)
        with Live(
            live_render, console=console, refresh_per_second=12, transient=False
        ) as live:
            try:
                async for event in self.client.stream_message(message):
                    if event.type == "token":
                        response_parts.append(event.content)
                    elif event.type == "tool_call":
                        tool_lines.append(self._tool_status("call", event))
                    elif event.type == "tool_result":
                        tool_lines.append(self._tool_status("result", event))
                    elif event.type == "error":
                        response_parts.append(
                            f"**Error:** {event.error or event.content}"
                        )
                    elif event.type == "done":
                        break
                    live.update(Group(Markdown("".join(response_parts)), *tool_lines))
            except Exception as exc:
                live.update(
                    Group(Markdown(f"**Connection error:** {exc}"), *tool_lines)
                )

    @staticmethod
    def _tool_status(kind: str, event: StreamEvent) -> Text:
        data = event.data or {}
        name = data.get("name", data.get("tool_name", "tool"))
        return Text(f"  {kind}: {name}", style="dim italic")


def run_app(backend_url: str | None = None) -> None:
    """Console entry point for the inline async REPL."""
    try:
        asyncio.run(YuzuREPL(backend_url).start())
    except KeyboardInterrupt:
        console.print("\n[dim]Bye.[/]")


if __name__ == "__main__":
    run_app()
