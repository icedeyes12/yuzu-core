from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.sandbox_tool_dispatcher import SandboxToolDispatcher


class FakeRepo:
    def __init__(self, state: str = "ready") -> None:
        self.state = state

    async def get_by_owner(self, owner_id: str):
        if self.state == "none":
            return None
        return {"owner_id": owner_id, "state": self.state, "runtime_name": "sbx_test"}


class FakeBuilder:
    def build_exec_args(
        self, runtime_name: str, argv: list[str], cwd: str = "/home/yuzu"
    ):
        return ["echo", "sandbox_mock"] + argv


@pytest.mark.asyncio
async def test_tool_dispatcher_checks_sandbox_state():
    # 1. When sandbox not ready
    dispatcher = SandboxToolDispatcher(
        repository=FakeRepo(state="none"), builder=FakeBuilder()
    )
    res = await dispatcher.execute_command(user_id=str(uuid4()), argv=["ls"])
    assert res["ok"] is False
    assert "not ready" in res["error"]

    # 2. When sandbox ready
    dispatcher = SandboxToolDispatcher(
        repository=FakeRepo(state="ready"), builder=FakeBuilder()
    )
    res = await dispatcher.execute_command(user_id=str(uuid4()), argv=["test"])
    assert res["ok"] is True
    assert "sandbox_mock" in res["stdout"]
