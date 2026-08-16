"""Branch tests for the non-streaming orchestrator path (handle_user_message)."""

from __future__ import annotations

import json

import pytest

from app.services import orchestrator

_FALLBACK = orchestrator._EMPTY_RESPONSE_FALLBACK


def _profile() -> dict:
    return {
        "id": "u1",
        "providers_config": {
            "preferred_provider": "groq",
            "preferred_model": "llama-3.3-70b",
        },
        "model_parameters": {},
    }


@pytest.fixture
def handle_fakes(monkeypatch):
    """Patch all handle_user_message dependencies with controllable fakes."""

    class Fakes:
        def __init__(self):
            self.profile = _profile()
            self.active_session = {"id": "sess-1"}
            self.user_msg_id = 42
            self.generate_results: list[tuple[str | None, dict | None]] = []
            self.parse_results: list[list[dict]] = []
            self.assistant_persisted: list[tuple[str, list | None]] = []
            self.persist_user_calls = 0
            self.executed_calls: list[list[dict]] = []
            self.persist_results_calls = 0
            self.post_turn_calls: list[tuple[str, str]] = []  # (user_message, response)

    fakes = Fakes()

    async def get_profile(user_id):
        return fakes.profile

    async def get_active_session(user_id):
        return fakes.active_session

    async def persist_user(message, session_id, attachments, *, user_id, turn_id=""):
        fakes.persist_user_calls += 1
        return fakes.user_msg_id

    async def fake_generate(
        profile, user_message, interface, session_id, *, user_id, client_context=None
    ):
        if fakes.generate_results:
            return fakes.generate_results.pop(0)
        return "", None

    async def fake_parse(provider_name, raw_response, turn_id=""):
        if fakes.parse_results:
            return fakes.parse_results.pop(0)
        return []

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
        return []

    async def persist_results(
        tool_results, tool_calls, session_id, *, user_id, turn_id=""
    ):
        fakes.persist_results_calls += 1
        return [], []

    def post_turn(
        profile,
        user_message,
        response,
        session_id,
        active_session,
        *,
        user_id,
    ):
        # create_task schedules this; record synchronously so the assertion
        # holds before the event loop runs the background task
        fakes.post_turn_calls.append((user_message, response))

        async def _noop():
            return None

        return _noop()

    monkeypatch.setattr(orchestrator.Database, "get_profile", get_profile)
    monkeypatch.setattr(orchestrator.Database, "get_active_session", get_active_session)
    monkeypatch.setattr(orchestrator, "_cache_images_from_message", lambda msg: [])
    monkeypatch.setattr(orchestrator, "_persist_user_async", persist_user)
    monkeypatch.setattr(orchestrator, "generate_ai_response", fake_generate)
    monkeypatch.setattr(orchestrator, "_parse_raw_tool_calls_async", fake_parse)
    monkeypatch.setattr(orchestrator, "_persist_assistant_async", persist_assistant)
    monkeypatch.setattr(orchestrator, "_execute_tool_calls_async", execute_tools)
    monkeypatch.setattr(
        orchestrator, "_persist_streaming_tool_results_async", persist_results
    )
    monkeypatch.setattr(orchestrator, "_post_turn_async", post_turn)
    return fakes


@pytest.mark.asyncio
async def test_handle_message_empty_returns_prompt(handle_fakes):
    result = await orchestrator.handle_user_message("   ", user_id="user")

    assert result == "Please enter a message!"
    assert handle_fakes.persist_user_calls == 0
    assert handle_fakes.assistant_persisted == []
    assert handle_fakes.post_turn_calls == []


@pytest.mark.asyncio
async def test_handle_message_text_only_persists_and_post_turns(handle_fakes):
    handle_fakes.generate_results = [("Hello there", {"choices": [{}]})]

    result = await orchestrator.handle_user_message("hi", user_id="user")

    assert result == "Hello there"
    assert handle_fakes.assistant_persisted == [("Hello there", None)]
    assert handle_fakes.executed_calls == []
    assert handle_fakes.post_turn_calls == [("hi", "Hello there")]


@pytest.mark.asyncio
async def test_handle_message_none_text_falls_back(handle_fakes):
    handle_fakes.generate_results = [(None, None)]

    result = await orchestrator.handle_user_message("hi", user_id="user")

    assert result == _FALLBACK
    assert handle_fakes.assistant_persisted == [(_FALLBACK, None)]
    assert handle_fakes.post_turn_calls == [("hi", _FALLBACK)]


@pytest.mark.asyncio
async def test_handle_message_timestamp_only_cleaned_to_fallback(handle_fakes):
    # _clean strips the trailing timestamp suffix -> empty -> fallback
    handle_fakes.generate_results = [(" [2026-08-15 12:00:00]", None)]

    result = await orchestrator.handle_user_message("hi", user_id="user")

    assert result == _FALLBACK
    assert handle_fakes.assistant_persisted == [(_FALLBACK, None)]


@pytest.mark.asyncio
async def test_handle_message_tool_call_round_trip(handle_fakes):
    tool_call = {"id": "call_1", "name": "bash", "arguments": {"cmd": "ls"}}
    handle_fakes.generate_results = [
        ("", {"choices": [{"message": {"tool_calls": [{"id": "call_1"}]}}]}),
        ("Done", None),
    ]
    handle_fakes.parse_results = [[tool_call], []]

    result = await orchestrator.handle_user_message("run ls", user_id="user")

    assert result == "Done"
    assert handle_fakes.executed_calls == [[tool_call]]
    assert handle_fakes.persist_results_calls == 1
    # empty first-pass text cleans to the fallback, persisted with tool_calls JSON
    assert handle_fakes.assistant_persisted[0] == (
        _FALLBACK,
        [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "bash", "arguments": json.dumps({"cmd": "ls"})},
            }
        ],
    )
    assert handle_fakes.assistant_persisted[1] == ("Done", None)
    assert handle_fakes.post_turn_calls == [("run ls", "Done")]


@pytest.mark.asyncio
async def test_handle_message_max_loops_exhausted(handle_fakes):
    tool_call = {"id": "call_1", "name": "bash", "arguments": {}}
    handle_fakes.generate_results = [("", None)] * 4
    handle_fakes.parse_results = [[tool_call]] * 4

    result = await orchestrator.handle_user_message("x", user_id="user")

    assert result == _FALLBACK
    assert len(handle_fakes.executed_calls) == 4
    assert handle_fakes.persist_results_calls == 4
    assert handle_fakes.post_turn_calls == [("x", _FALLBACK)]
