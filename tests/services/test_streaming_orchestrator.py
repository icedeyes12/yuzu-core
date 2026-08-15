"""Branch tests for the streaming orchestrator path (handle_user_message_streaming)."""

from __future__ import annotations

import json

import pytest

from app.services import orchestrator
from app.tools.schemas import StreamToolEvent, ToolResultEvent

_FALLBACK = orchestrator._EMPTY_RESPONSE_FALLBACK


@pytest.fixture
def stream_fakes(monkeypatch):
    """Patch all handle_user_message_streaming dependencies with controllable fakes."""

    class Fakes:
        def __init__(self):
            self.profile = {"id": "u1"}
            self.active_session = {"id": "sess-1"}
            self.user_msg_id = 42
            self.stream_passes: list[list[str | StreamToolEvent]] = []
            self.generation_error: Exception | None = None
            self.finalize_calls: list[tuple[str, str]] = []  # (fence_id, response)
            self.assistant_persisted: list[tuple[str, list | None]] = []
            self.executed_calls: list[list[dict]] = []
            self.tool_result_events: list[ToolResultEvent] = []
            self.persist_results_calls = 0
            self.persist_user_calls = 0
            self.acquire_calls: list[tuple[str, int]] = []
            self.abort_after: int | None = None

    fakes = Fakes()

    async def get_profile(user_id):
        return fakes.profile

    async def get_active_session(user_id):
        return fakes.active_session

    async def persist_user(message, session_id, attachments, *, user_id, turn_id=""):
        fakes.persist_user_calls += 1
        return fakes.user_msg_id

    async def fake_acquire(session_id, user_msg_id):
        fakes.acquire_calls.append((session_id, user_msg_id))
        return "fence-1"

    async def fake_complete(session_id, fence_id):
        return True

    async def fake_generate(
        profile, user_message, interface, session_id, *, user_id, client_context=None
    ):
        if fakes.generation_error is not None:
            yield "hello"
            raise fakes.generation_error
        if fakes.stream_passes:
            for chunk in fakes.stream_passes.pop(0):
                yield chunk

    async def finalize(
        session_id,
        fence_id,
        profile,
        user_message,
        final_response,
        active_session,
        *,
        user_id,
        turn_id="",
    ):
        fakes.finalize_calls.append((fence_id, final_response))

    async def persist_assistant(
        content,
        session_id,
        attachments=None,
        *,
        user_id,
        tool_calls=None,
        turn_id="",
    ):
        fakes.assistant_persisted.append((content, tool_calls))

    async def execute_tools(tool_calls, session_id, user_id=None, turn_id=""):
        fakes.executed_calls.append(tool_calls)
        return fakes.tool_result_events

    async def persist_results(
        tool_results, tool_calls, session_id, *, user_id, turn_id=""
    ):
        fakes.persist_results_calls += 1
        return [], []

    monkeypatch.setattr(orchestrator.Database, "get_profile", get_profile)
    monkeypatch.setattr(orchestrator.Database, "get_active_session", get_active_session)
    monkeypatch.setattr(orchestrator, "_cache_images_from_message", lambda msg: [])
    monkeypatch.setattr(orchestrator, "_persist_user_async", persist_user)
    monkeypatch.setattr(orchestrator.StreamFence, "acquire", fake_acquire)
    monkeypatch.setattr(orchestrator.StreamFence, "complete", fake_complete)
    monkeypatch.setattr(orchestrator, "generate_ai_response_streaming", fake_generate)
    monkeypatch.setattr(orchestrator, "_finalize_and_persist_async", finalize)
    monkeypatch.setattr(orchestrator, "_persist_assistant_async", persist_assistant)
    monkeypatch.setattr(orchestrator, "_execute_tool_calls_async", execute_tools)
    monkeypatch.setattr(
        orchestrator, "_persist_streaming_tool_results_async", persist_results
    )
    return fakes


async def _consume(fakes, user_message="hello", **kwargs):
    checks = [0]

    def abort_check():
        checks[0] += 1
        return fakes.abort_after is not None and checks[0] > fakes.abort_after

    return [
        chunk
        async for chunk in orchestrator.handle_user_message_streaming(
            user_message,
            session_id="sess-1",
            abort_check=abort_check,
            user_id="user",
            **kwargs,
        )
    ]


@pytest.mark.asyncio
async def test_stream_empty_message_returns_prompt(stream_fakes):
    chunks = await _consume(stream_fakes, user_message="   ")

    assert chunks == ["Please enter a message!"]
    assert stream_fakes.persist_user_calls == 0
    assert stream_fakes.acquire_calls == []
    assert stream_fakes.finalize_calls == []


@pytest.mark.asyncio
async def test_stream_aborts_before_start(stream_fakes):
    stream_fakes.abort_after = 0

    chunks = await _consume(stream_fakes)

    assert chunks == []
    assert stream_fakes.persist_user_calls == 0
    assert stream_fakes.acquire_calls == []
    assert stream_fakes.finalize_calls == []


@pytest.mark.asyncio
async def test_stream_aborts_mid_stream_without_finalize(stream_fakes):
    stream_fakes.stream_passes = [["hello", " world"]]
    stream_fakes.abort_after = 2  # 1 pre-loop check + 1 chunk, abort on 2nd chunk

    chunks = await _consume(stream_fakes)

    assert chunks == ["hello"]
    assert stream_fakes.finalize_calls == []  # fence left incomplete


@pytest.mark.asyncio
async def test_stream_empty_response_falls_back(stream_fakes):
    stream_fakes.stream_passes = []

    chunks = await _consume(stream_fakes)

    assert chunks == [_FALLBACK]
    assert stream_fakes.finalize_calls == [("fence-1", _FALLBACK)]


@pytest.mark.asyncio
async def test_stream_text_only_finalizes_with_response(stream_fakes):
    stream_fakes.stream_passes = [["Hello ", "world"]]

    chunks = await _consume(stream_fakes)

    assert chunks == ["Hello ", "world"]
    assert stream_fakes.finalize_calls == [("fence-1", "Hello world")]
    assert stream_fakes.executed_calls == []


@pytest.mark.asyncio
async def test_stream_tool_call_round_trip_loops_then_finalizes(stream_fakes):
    tool_call = StreamToolEvent(
        type="tool_call",
        data={"id": "call_1", "name": "bash", "arguments": {"cmd": "ls"}},
    )
    result = ToolResultEvent(call_id="call_1", name="bash", ok=True, data={"out": "ok"})
    stream_fakes.stream_passes = [[tool_call], ["done"]]
    stream_fakes.tool_result_events = [result]

    chunks = await _consume(stream_fakes)

    assert isinstance(chunks[0], StreamToolEvent)
    assert chunks[0].type == "tool_call"
    assert chunks[0].data["id"] == "call_1"
    assert chunks[0].data["turn_id"]
    assert isinstance(chunks[1], StreamToolEvent)
    assert chunks[1].type == "tool_result"
    assert chunks[1].data["call_id"] == "call_1"
    assert chunks[1].data["turn_id"]
    assert chunks[2:] == ["done"]

    assert stream_fakes.executed_calls == [
        [{"id": "call_1", "name": "bash", "arguments": {"cmd": "ls"}}]
    ]
    assert stream_fakes.persist_results_calls == 1
    # assistant turn with tool_calls persisted before execution; final text via finalize
    assert stream_fakes.assistant_persisted == [
        (
            "",
            [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "bash",
                        "arguments": json.dumps({"cmd": "ls"}),
                    },
                }
            ],
        )
    ]
    assert stream_fakes.finalize_calls == [("fence-1", "done")]


@pytest.mark.asyncio
async def test_stream_invalid_tool_call_is_dropped(stream_fakes):
    invalid = StreamToolEvent(
        type="tool_call", data={"id": "", "name": "", "arguments": {}}
    )
    stream_fakes.stream_passes = [[invalid]]

    chunks = await _consume(stream_fakes)

    assert chunks == [_FALLBACK]  # no valid tool calls -> empty-response branch
    assert stream_fakes.executed_calls == []
    assert stream_fakes.finalize_calls == [("fence-1", _FALLBACK)]


@pytest.mark.asyncio
async def test_stream_max_loops_exhausted_finalizes_empty(stream_fakes):
    tool_call = StreamToolEvent(
        type="tool_call",
        data={"id": "call_1", "name": "bash", "arguments": {"cmd": "ls"}},
    )
    result = ToolResultEvent(call_id="call_1", name="bash", ok=True)
    stream_fakes.stream_passes = [[tool_call], [tool_call], [tool_call], [tool_call]]
    stream_fakes.tool_result_events = [result]

    chunks = await _consume(stream_fakes)

    tool_calls = [
        c for c in chunks if isinstance(c, StreamToolEvent) and c.type == "tool_call"
    ]
    tool_results = [
        c for c in chunks if isinstance(c, StreamToolEvent) and c.type == "tool_result"
    ]
    assert len(tool_calls) == 4
    assert len(tool_results) == 4
    assert len(stream_fakes.executed_calls) == 4
    assert stream_fakes.persist_results_calls == 4
    assert stream_fakes.finalize_calls == [("fence-1", "")]


@pytest.mark.asyncio
async def test_stream_generation_exception_reraises_without_finalize(stream_fakes):
    stream_fakes.generation_error = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await _consume(stream_fakes)

    assert stream_fakes.finalize_calls == []
    assert stream_fakes.acquire_calls == [("sess-1", 42)]
