"""Branch tests for the segmentation trigger scheduler (should_trigger_segmentation_async)."""

from __future__ import annotations

import pytest

ZERO_UUID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def trigger_fakes(monkeypatch):
    """Patch scheduler dependencies with controllable fakes."""

    from app.memory import memory

    class Fakes:
        def __init__(self):
            self.fence_active = False
            self.state: dict = {}
            self.after_id_messages: list[dict] = []
            self.after_id_raises: Exception | None = None
            self.after_id_calls: list[str] = []
            self.idle_hours: float | None = None
            self.idle_calls = 0

    fakes = Fakes()

    async def fence(session_id, user_id=None):
        return fakes.fence_active

    async def state(session_id, user_id=None):
        return fakes.state

    async def after_id(session_id, last_id, limit, user_id):
        fakes.after_id_calls.append(last_id)
        if fakes.after_id_raises is not None:
            raise fakes.after_id_raises
        return fakes.after_id_messages

    async def idle(session_id, user_id=None):
        fakes.idle_calls += 1
        return fakes.idle_hours

    monkeypatch.setattr(memory, "_is_fence_active_async", fence)
    monkeypatch.setattr(memory, "_get_cached_pipeline_state_async", state)
    monkeypatch.setattr(memory, "get_session_messages_after_id_async", after_id)
    monkeypatch.setattr(memory, "_get_session_idle_hours_async", idle)
    return fakes


def _messages(count: int) -> list[dict]:
    return [{"id": f"m{i}", "role": "user"} for i in range(count)]


@pytest.mark.asyncio
async def test_trigger_blocked_while_fence_active(trigger_fakes):
    from app.memory import memory

    trigger_fakes.fence_active = True

    result = await memory.should_trigger_segmentation_async("s", 100, user_id="u")

    assert result == (False, 0)
    assert trigger_fakes.idle_calls == 0
    assert trigger_fakes.after_id_calls == []


@pytest.mark.asyncio
async def test_trigger_delta_above_window(trigger_fakes):
    from app.memory import memory

    trigger_fakes.after_id_messages = _messages(45)

    result = await memory.should_trigger_segmentation_async("s", 45, user_id="u")

    assert result == (True, 45)
    assert trigger_fakes.idle_calls == 0


@pytest.mark.asyncio
async def test_trigger_historical_backlog_still_triggers(trigger_fakes):
    from app.memory import memory

    trigger_fakes.after_id_messages = _messages(1005)

    result = await memory.should_trigger_segmentation_async("s", 1005, user_id="u")

    assert result == (True, 1005)
    assert trigger_fakes.idle_calls == 0


@pytest.mark.asyncio
async def test_trigger_delta_below_idle_window(trigger_fakes):
    from app.memory import memory

    trigger_fakes.after_id_messages = _messages(19)

    result = await memory.should_trigger_segmentation_async("s", 19, user_id="u")

    assert result == (False, 19)
    assert trigger_fakes.idle_calls == 0


@pytest.mark.asyncio
async def test_trigger_idle_gate_pass_after_idle_hours(trigger_fakes):
    from app.memory import memory

    trigger_fakes.after_id_messages = _messages(25)
    trigger_fakes.idle_hours = 4.0

    result = await memory.should_trigger_segmentation_async("s", 25, user_id="u")

    assert result == (True, 25)
    assert trigger_fakes.idle_calls == 1


@pytest.mark.asyncio
async def test_trigger_idle_gate_fails_when_recent(trigger_fakes):
    from app.memory import memory

    trigger_fakes.after_id_messages = _messages(25)
    trigger_fakes.idle_hours = 1.0

    result = await memory.should_trigger_segmentation_async("s", 25, user_id="u")

    assert result == (False, 25)
    assert trigger_fakes.idle_calls == 1


@pytest.mark.asyncio
async def test_trigger_idle_gate_fails_when_idle_unknown(trigger_fakes):
    from app.memory import memory

    trigger_fakes.after_id_messages = _messages(25)
    trigger_fakes.idle_hours = None

    result = await memory.should_trigger_segmentation_async("s", 25, user_id="u")

    assert result == (False, 25)
    assert trigger_fakes.idle_calls == 1


@pytest.mark.asyncio
async def test_trigger_count_fallback_above_window(trigger_fakes):
    from app.memory import memory

    trigger_fakes.after_id_raises = RuntimeError("cursor query failed")
    trigger_fakes.state = {"last_segmented_count": 10}

    result = await memory.should_trigger_segmentation_async("s", 60, user_id="u")

    assert result == (True, 50)  # 60 - 10
    assert trigger_fakes.idle_calls == 0


@pytest.mark.asyncio
async def test_trigger_count_fallback_below_window(trigger_fakes):
    from app.memory import memory

    trigger_fakes.after_id_raises = RuntimeError("cursor query failed")
    trigger_fakes.state = {"last_segmented_count": 50}

    result = await memory.should_trigger_segmentation_async("s", 60, user_id="u")

    assert result == (False, 10)  # 60 - 50
    assert trigger_fakes.idle_calls == 0


@pytest.mark.asyncio
async def test_trigger_normalizes_int_cursor_to_zero_uuid(trigger_fakes):
    from app.memory import memory

    trigger_fakes.state = {"last_segmented_message_id": 7}
    trigger_fakes.after_id_messages = _messages(40)

    result = await memory.should_trigger_segmentation_async("s", 40, user_id="u")

    assert result == (True, 40)
    assert trigger_fakes.after_id_calls == [ZERO_UUID]
