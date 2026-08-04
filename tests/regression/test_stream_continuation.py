from __future__ import annotations

import json

from app.db.queries import format_ai_history_rows
from app.services.orchestrator import _normalise_tool_calls


def test_normalise_tool_calls_generates_id_and_parses_arguments() -> None:
    calls = _normalise_tool_calls(
        [{"name": "python", "arguments": '{"code": "print(1 + 1)"}'}]
    )

    assert calls[0]["id"].startswith("call_")
    assert calls[0]["arguments"] == {"code": "print(1 + 1)"}


def test_tool_history_keeps_matching_assistant_and_tool_call_id() -> None:
    rows = [
        {
            "role": "assistant",
            "content": "",
            "attachments": "[]",
            "tool_calls": json.dumps(
                [
                    {
                        "id": "call_exec",
                        "type": "function",
                        "function": {
                            "name": "python",
                            "arguments": '{"code":"print(1 + 1)"}',
                        },
                    }
                ]
            ),
            "tool_call_id": None,
            "turn_id": "turn_1",
            "timestamp": "2026-07-15 13:30:00",
        },
        {
            "role": "tool",
            "content": '{"ok":true,"name":"python","data":{"output":"2"}}',
            "attachments": "[]",
            "tool_calls": None,
            "tool_call_id": "call_exec",
            "turn_id": "turn_1",
            "timestamp": "2026-07-15 13:30:01",
        },
    ]

    history = format_ai_history_rows(rows)

    assert history[0]["tool_calls"][0]["id"] == history[1]["tool_call_id"]
    assert history[1]["role"] == "tool"
