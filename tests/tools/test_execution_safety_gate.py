from __future__ import annotations

import pytest

from app.tools import registry


@pytest.fixture(autouse=True)
def reset_registry(monkeypatch):
    monkeypatch.delenv("YUZU_USER_EXECUTION_ENABLED", raising=False)
    registry._TOOL_DEFINITIONS.clear()
    registry._TOOL_MODULES.clear()
    registry._definitions_initialized = False
    yield
    registry._TOOL_DEFINITIONS.clear()
    registry._TOOL_MODULES.clear()
    registry._definitions_initialized = False


def test_direct_execution_tools_are_hidden_by_default():
    names = {definition.name for definition in registry.get_tool_definitions()}

    assert names.isdisjoint(
        {"terminal", "python", "sql", "read", "write", "ls", "mkdir", "rm"}
    )


@pytest.mark.asyncio
async def test_direct_execution_dispatch_is_blocked_by_default():
    result = await registry.execute_tool("terminal", {"command": "id"}, user_id="user")

    assert result == {
        "ok": False,
        "error": "User execution is disabled",
        "data": {},
    }


def test_direct_execution_can_only_be_enabled_explicitly(monkeypatch):
    monkeypatch.setenv("YUZU_USER_EXECUTION_ENABLED", "true")

    names = {definition.name for definition in registry.get_tool_definitions()}

    assert {"terminal", "python", "sql", "read", "write", "ls", "mkdir", "rm"} <= names
