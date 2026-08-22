from __future__ import annotations

import pytest

from app.tools import registry


@pytest.fixture(autouse=True)
def reset_registry():
    registry._TOOL_DEFINITIONS.clear()
    registry._TOOL_MODULES.clear()
    registry._definitions_initialized = False
    yield
    registry._TOOL_DEFINITIONS.clear()
    registry._TOOL_MODULES.clear()
    registry._definitions_initialized = False


def test_direct_execution_tools_are_hidden_without_user_context():
    names = {definition.name for definition in registry.get_tool_definitions()}

    assert names.isdisjoint(
        {"terminal", "python", "sql", "read", "write", "ls", "mkdir", "rm"}
    )


@pytest.mark.asyncio
async def test_direct_execution_dispatch_fails_without_ready_sandbox(monkeypatch):
    async def not_ready(_user_id):
        return False

    monkeypatch.setattr(registry, "_sandbox_ready", not_ready)
    result = await registry.execute_tool("terminal", {"command": "id"}, user_id="user")

    assert result == {
        "ok": False,
        "error": "My Computer sandbox is not ready",
        "data": {},
    }
