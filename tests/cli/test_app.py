from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from cli.app import YuzuREPL
from cli.client import StreamEvent


@pytest.fixture
def repl(monkeypatch):
    monkeypatch.setenv("YUZU_CLI_HISTORY", "/tmp/yuzu-test-history")
    return YuzuREPL("http://testserver")


def test_repl_uses_explicit_backend_url(repl):
    assert repl.backend_url == "http://testserver"
    assert repl.session_id is None
    assert repl.running is True


@pytest.mark.asyncio
@pytest.mark.unit
async def test_quit_commands_stop_repl(repl):
    for command in ("/quit", "/exit", "/q"):
        repl.running = True
        assert await repl._handle_command(command)
        assert repl.running is False


@pytest.mark.asyncio
@pytest.mark.unit
async def test_unknown_message_is_not_command(repl):
    repl._send_message = AsyncMock()
    assert not await repl._handle_command("hello")
    repl._send_message.assert_not_awaited()


def test_tool_status_handles_tool_name_variants(repl):
    event = StreamEvent(type="tool_call", data={"tool_name": "weather"})
    assert "weather" in repl._tool_status("call", event).plain
