from __future__ import annotations

import pytest

from app.tools import registry


class FakeRepo:
    def __init__(self, state: str | None):
        self.state = state

    async def get_by_owner(self, user_id: str):
        if self.state is None:
            return None
        return {"owner_id": user_id, "state": self.state}


@pytest.mark.asyncio
async def test_execution_tools_hidden_without_ready_sandbox(monkeypatch):
    monkeypatch.setattr(registry, "PgSandboxInstanceRepository", lambda: FakeRepo(None))

    names = {
        schema["function"]["name"]
        for schema in await registry.get_tool_schemas_for_user("user-1")
    }

    assert names.isdisjoint(
        {"terminal", "python", "read", "write", "ls", "mkdir", "rm"}
    )


@pytest.mark.asyncio
async def test_execution_tools_visible_for_ready_sandbox(monkeypatch):
    monkeypatch.setattr(
        registry, "PgSandboxInstanceRepository", lambda: FakeRepo("ready")
    )

    names = {
        schema["function"]["name"]
        for schema in await registry.get_tool_schemas_for_user("user-1")
    }

    assert {"terminal", "python", "read", "write", "ls", "mkdir", "rm"} <= names
    assert "sql" not in names


@pytest.mark.asyncio
async def test_terminal_dispatches_to_owned_sandbox_and_never_legacy_shell(monkeypatch):
    calls = []

    class FakeDispatcher:
        async def execute_command(
            self, user_id, argv, cwd="/home/yuzu", timeout_seconds=30
        ):
            calls.append((user_id, argv, cwd))
            return {"ok": True, "exit_code": 0, "stdout": "/home/yuzu\n", "stderr": ""}

    monkeypatch.setattr(registry, "SandboxToolDispatcher", FakeDispatcher)
    monkeypatch.setattr(
        registry, "PgSandboxInstanceRepository", lambda: FakeRepo("ready")
    )

    result = await registry.execute_tool(
        "terminal", {"command": "pwd"}, user_id="user-1"
    )

    assert result["ok"] is True
    assert calls == [("user-1", ["/bin/bash", "-lc", "pwd"], "/home/yuzu")]


@pytest.mark.asyncio
async def test_terminal_fails_closed_when_sandbox_unavailable(monkeypatch):
    monkeypatch.setattr(registry, "PgSandboxInstanceRepository", lambda: FakeRepo(None))

    result = await registry.execute_tool(
        "terminal", {"command": "pwd"}, user_id="user-1"
    )

    assert result["ok"] is False
    assert result["error"] == "My Computer sandbox is not ready"
