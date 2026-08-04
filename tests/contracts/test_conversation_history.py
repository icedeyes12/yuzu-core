from __future__ import annotations

from app.db.models_async import _trim_public_history_blocks, _trim_tool_history_blocks
from app.db.queries import format_public_history_rows


def _assistant() -> dict[str, object]:
    return {
        "id": 1,
        "role": "assistant",
        "content": None,
        "attachments": "[]",
        "tool_calls": '[{"id":"call_1","type":"function","function":{"name":"weather","arguments":"{}"}}]',
        "tool_call_id": None,
        "timestamp": "2026-07-26T00:00:00+00:00",
    }


def _tool() -> dict[str, object]:
    return {
        "id": 2,
        "role": "tool",
        "content": "result",
        "attachments": "[]",
        "tool_calls": None,
        "tool_call_id": "call_1",
        "timestamp": "2026-07-26T00:00:01+00:00",
    }


def test_public_history_is_canonical_and_hides_internal_metadata() -> None:
    messages = format_public_history_rows([_assistant(), _tool()])
    assert messages[0]["id"] == "1"
    assert messages[0]["tool_calls"][0]["function"]["name"] == "weather"
    assert "turn_id" not in messages[0]
    assert messages[1]["tool_call_id"] == "call_1"
    assert "timestamp" in messages[1]


def test_public_history_drops_incomplete_tool_block() -> None:
    messages = format_public_history_rows([_assistant()])
    assert _trim_public_history_blocks(messages) == []


def test_ai_history_drops_orphan_tool_and_incomplete_block() -> None:
    assistant = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "weather", "arguments": "{}"},
            }
        ],
    }
    tool = {"role": "tool", "tool_call_id": "call_1", "content": "result"}
    assert _trim_tool_history_blocks([assistant, tool]) == [assistant, tool]
    assert _trim_tool_history_blocks([tool]) == []
    assert _trim_tool_history_blocks([assistant]) == []
