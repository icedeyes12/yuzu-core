"""Branch tests for the background memory worker loop (_background_worker_async)."""

from __future__ import annotations

import asyncio

import pytest

from app.core.context import RequestKeyring


@pytest.fixture
def worker_fakes(monkeypatch):
    """Patch worker dependencies with a fresh queue and controllable fakes."""

    from app.memory import memory

    class Fakes:
        def __init__(self):
            self.pipeline_results: list[dict] = []
            self.pipeline_calls = 0
            self.pipeline_error: Exception | None = None
            self.count = 100
            self.state: dict = {}
            self.remaining_messages: list[dict] = []
            self.backlog_eligible = False
            self.set_keyrings: list[dict[str, RequestKeyring]] = []
            self.cleared_keyrings = 0
            self.task_done_calls = 0
            self.state_calls = 0
            self.completed = asyncio.Event()

    fakes = Fakes()

    queue = asyncio.Queue()
    real_task_done = queue.task_done

    def task_done_wrapper():
        fakes.task_done_calls += 1
        fakes.completed.set()
        real_task_done()

    queue.task_done = task_done_wrapper
    queued_sessions = {("sess", "user")}
    fakes.queued_sessions = queued_sessions

    async def get_count(session_id, user_id):
        return fakes.count

    async def run_pipeline(session_id, message_count, user_id):
        fakes.pipeline_calls += 1
        if fakes.pipeline_error is not None:
            raise fakes.pipeline_error
        if fakes.pipeline_results:
            return fakes.pipeline_results.pop(0)
        return {"processed_messages": 0}

    async def get_state(session_id, user_id):
        fakes.state_calls += 1
        return fakes.state

    async def after_id(session_id, last_id, limit, user_id):
        return fakes.remaining_messages

    async def eligible(session_id, remaining_count, user_id):
        return fakes.backlog_eligible

    def set_keyrings(keyrings):
        fakes.set_keyrings.append(keyrings)

    def clear_keyring():
        fakes.cleared_keyrings += 1

    monkeypatch.setattr(memory, "_pending_sessions", queue)
    monkeypatch.setattr(memory, "_queued_sessions", queued_sessions)
    monkeypatch.setattr(memory, "get_message_count_async", get_count)
    monkeypatch.setattr(memory, "run_memory_pipeline_async", run_pipeline)
    monkeypatch.setattr(memory, "get_pipeline_state_async", get_state)
    monkeypatch.setattr(memory, "get_session_messages_after_id_async", after_id)
    monkeypatch.setattr(memory, "_has_eligible_backlog_async", eligible)
    monkeypatch.setattr(memory, "set_request_keyrings", set_keyrings)
    monkeypatch.setattr(memory, "clear_request_keyring", clear_keyring)
    return fakes


async def _run_worker_once(fakes, item):
    """Start the worker, feed one item, wait for it to finish, then stop it."""
    from app.memory import memory

    worker = asyncio.create_task(memory._background_worker_async())
    await memory._pending_sessions.put(item)
    await asyncio.wait_for(fakes.completed.wait(), timeout=5)
    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker


@pytest.mark.asyncio
async def test_worker_skips_invalid_item(worker_fakes):
    await _run_worker_once(worker_fakes, ("", None, {}))

    assert worker_fakes.pipeline_calls == 0
    assert worker_fakes.task_done_calls == 1
    assert worker_fakes.cleared_keyrings == 0
    # invalid items are skipped before the try/finally, so nothing is discarded
    assert ("sess", "user") in worker_fakes.queued_sessions


@pytest.mark.asyncio
async def test_worker_single_batch_stops_when_backlog_not_eligible(worker_fakes):
    worker_fakes.pipeline_results = [{"processed_messages": 10}]
    worker_fakes.state = {"last_segmented_message_id": "m10"}
    worker_fakes.remaining_messages = [{"id": "m11"}]
    worker_fakes.backlog_eligible = False

    await _run_worker_once(worker_fakes, ("sess", "user", {}))

    assert worker_fakes.pipeline_calls == 1
    assert worker_fakes.state_calls == 1
    assert worker_fakes.task_done_calls == 1
    assert worker_fakes.cleared_keyrings == 1
    assert ("sess", "user") not in worker_fakes.queued_sessions


@pytest.mark.asyncio
async def test_worker_multiple_batches_until_pipeline_empty(worker_fakes):
    worker_fakes.pipeline_results = [
        {"processed_messages": 10},
        {"processed_messages": 0},
    ]
    worker_fakes.state = {"last_segmented_message_id": "m10"}
    worker_fakes.remaining_messages = [{"id": "m11"}, {"id": "m12"}]
    worker_fakes.backlog_eligible = True

    await _run_worker_once(worker_fakes, ("sess", "user", {}))

    assert worker_fakes.pipeline_calls == 2
    assert worker_fakes.state_calls == 1  # only queried after a non-empty batch
    assert worker_fakes.task_done_calls == 1
    assert worker_fakes.cleared_keyrings == 1


@pytest.mark.asyncio
async def test_worker_stops_when_runtime_exceeded(worker_fakes, monkeypatch):
    from app.memory import memory

    worker_fakes.pipeline_results = [{"processed_messages": 10}]
    worker_fakes.backlog_eligible = True  # would continue if runtime allowed

    class _FakeTime:
        """Module-scoped time: worker clock only, event loop keeps the real one."""

        def __init__(self):
            self.calls = 0

        def monotonic(self):
            self.calls += 1
            return 0.0 if self.calls == 1 else 999.0

    # Patch the `time` name inside the memory module only, so the asyncio
    # event loop keeps its real clock and wait_for stays reliable.
    monkeypatch.setattr(memory, "time", _FakeTime())

    await _run_worker_once(worker_fakes, ("sess", "user", {}))

    assert worker_fakes.pipeline_calls == 1
    assert worker_fakes.state_calls == 0  # runtime break happens before state query
    assert worker_fakes.task_done_calls == 1


@pytest.mark.asyncio
async def test_worker_sets_and_clears_request_keyrings(worker_fakes):
    keyrings = {"groq": RequestKeyring(provider="groq", key="k")}
    worker_fakes.pipeline_results = [{"processed_messages": 0}]

    await _run_worker_once(worker_fakes, ("sess", "user", keyrings))

    assert worker_fakes.set_keyrings == [keyrings]
    assert worker_fakes.cleared_keyrings == 1
    assert ("sess", "user") not in worker_fakes.queued_sessions


@pytest.mark.asyncio
async def test_worker_exception_cleans_up(worker_fakes):
    worker_fakes.pipeline_error = RuntimeError("boom")

    await _run_worker_once(worker_fakes, ("sess", "user", {}))

    assert worker_fakes.pipeline_calls == 1
    assert worker_fakes.task_done_calls == 1
    assert worker_fakes.cleared_keyrings == 1
    # _queued_sessions entry discarded in the finally block
    assert ("sess", "user") not in worker_fakes.queued_sessions
