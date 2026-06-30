"""Regression tests for Native Function Calling streaming and persistence (FC4, FC5)."""

from __future__ import annotations

import json

from app.tools.schemas import StreamToolEvent


class TestStreamToolEventEnvelope:
    """SSE event envelope shapes (FC5)."""

    def test_token_event(self):
        event = StreamToolEvent(type="token", data="hello world")
        sse = event.to_sse()
        assert sse == {"type": "token", "content": "hello world"}

    def test_tool_call_event(self):
        data = {"id": "call_1", "name": "bash", "arguments": {"cmd": "ls"}}
        event = StreamToolEvent(type="tool_call", data=data)
        sse = event.to_sse()
        assert sse == {"type": "tool_call", "data": data}

    def test_tool_result_event(self):
        data = {
            "call_id": "call_1",
            "name": "bash",
            "ok": True,
            "markdown": "<details>ok</details>",
        }
        event = StreamToolEvent(type="tool_result", data=data)
        sse = event.to_sse()
        assert sse == {"type": "tool_result", "data": data}

    def test_done_event(self):
        event = StreamToolEvent(type="done")
        sse = event.to_sse()
        assert sse == {"type": "done"}

    def test_json_serializable(self):
        """All event types must be JSON-serializable for SSE."""
        events = [
            StreamToolEvent(type="token", data="text"),
            StreamToolEvent(
                type="tool_call", data={"id": "c1", "name": "bash", "arguments": {}}
            ),
            StreamToolEvent(type="tool_result", data={"call_id": "c1", "ok": True}),
            StreamToolEvent(type="done"),
        ]
        for event in events:
            raw = json.dumps(event.to_sse())
            parsed = json.loads(raw)
            assert "type" in parsed


class TestFormatAiHistoryRowsTurnId:
    """format_ai_history_rows preserves turn_id for native FC messages (FC4)."""

    def test_tool_call_message_includes_turn_id(self):
        from app.db.queries import format_ai_history_rows

        rows = [
            {
                "id": 1,
                "session_id": "s1",
                "role": "assistant",
                "content": "",
                "image_paths": "[]",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "bash", "arguments": "{}"}}
                ],
                "tool_call_id": None,
                "turn_id": "turn_abc",
                "timestamp": "2026-01-01 00:00:00",
            }
        ]
        out = format_ai_history_rows(rows)
        assert len(out) == 1
        assert out[0]["role"] == "assistant"
        assert "tool_calls" in out[0]
        assert out[0].get("turn_id") == "turn_abc"

    def test_tool_result_message_includes_turn_id(self):
        from app.db.queries import format_ai_history_rows

        rows = [
            {
                "id": 2,
                "session_id": "s1",
                "role": "tool",
                "content": "result",
                "image_paths": "[]",
                "tool_calls": None,
                "tool_call_id": "call_1",
                "turn_id": "turn_abc",
                "timestamp": "2026-01-01 00:00:01",
            }
        ]
        out = format_ai_history_rows(rows)
        assert len(out) == 1
        assert out[0]["role"] == "tool"
        assert out[0]["tool_call_id"] == "call_1"
        assert out[0].get("turn_id") == "turn_abc"

    def test_user_message_no_turn_id(self):
        from app.db.queries import format_ai_history_rows

        rows = [
            {
                "id": 3,
                "session_id": "s1",
                "role": "user",
                "content": "hello",
                "image_paths": "[]",
                "tool_calls": None,
                "tool_call_id": None,
                "turn_id": "",
                "timestamp": "2026-01-01 00:00:02",
            }
        ]
        out = format_ai_history_rows(rows)
        assert len(out) == 1
        assert out[0]["role"] == "user"
        # User messages should not have turn_id
        assert "turn_id" not in out[0]


class TestParseMessageId:
    """parse_message_row includes turn_id (FC4)."""

    def test_turn_id_in_output(self):
        from app.db.queries import parse_message_row

        row = {
            "id": 1,
            "session_id": "s1",
            "role": "assistant",
            "content": "hi",
            "image_paths": "[]",
            "tool_calls": None,
            "tool_call_id": None,
            "turn_id": "turn_xyz",
            "timestamp": "2026-01-01",
        }
        out = parse_message_row(row)
        assert out["turn_id"] == "turn_xyz"

    def test_turn_id_none_defaults_to_none(self):
        from app.db.queries import parse_message_row

        row = {
            "id": 1,
            "session_id": "s1",
            "role": "user",
            "content": "hi",
            "image_paths": "[]",
            "tool_calls": None,
            "tool_call_id": None,
            "timestamp": "2026-01-01",
        }
        out = parse_message_row(row)
        assert out["turn_id"] is None
