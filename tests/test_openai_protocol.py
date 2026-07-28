from __future__ import annotations

import pytest

from app.prompts import _trim_history_to_token_limit
from app.providers.openai_protocol import (
    OpenAIProtocolError,
    sanitize_openai_messages,
    sanitize_openai_payload,
    validate_chat_completion_response,
    validate_openai_messages,
)


def assistant_tool_block() -> list[dict[str, object]]:
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "bash", "arguments": '{"cmd":"pwd"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
    ]


def test_assistant_tool_call_and_response_survive_atomic_trimming() -> None:
    messages = [{"role": "user", "content": "old" * 50}] + assistant_tool_block()
    trimmed = _trim_history_to_token_limit(messages, max_tokens=40)
    assert trimmed == assistant_tool_block()


def test_atomic_trimming_drops_incomplete_tool_block() -> None:
    messages = assistant_tool_block()[:1] + [{"role": "user", "content": "new"}]
    assert _trim_history_to_token_limit(messages, max_tokens=1) == [
        {"role": "user", "content": "new"}
    ]


def test_outbound_message_sanitization_removes_internal_metadata() -> None:
    messages = [
        {"role": "user", "content": "hello", "turn_id": "t1", "db_id": 5},
        {"role": "assistant", "content": "ok", "timestamp": "secret"},
    ]
    clean = sanitize_openai_messages(messages)
    assert clean == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "ok"},
    ]


def test_historical_tool_calls_are_normalized_or_dropped() -> None:
    clean = sanitize_openai_messages(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"function": {"name": "bash", "arguments": {"cmd": "pwd"}}},
                    {
                        "id": "bad",
                        "type": "function",
                        "function": {"name": "", "arguments": "{}"},
                    },
                ],
            }
        ]
    )
    calls = clean[0]["tool_calls"]
    assert len(calls) == 1
    assert calls[0]["id"].startswith("call_hist_")
    assert calls[0]["type"] == "function"
    assert calls[0]["function"] == {"name": "bash", "arguments": '{"cmd":"pwd"}'}


def test_validator_rejects_orphan_tool() -> None:
    with pytest.raises(OpenAIProtocolError, match="no matching tool call"):
        validate_openai_messages(
            [{"role": "tool", "tool_call_id": "call_1", "content": "x"}]
        )


def test_validator_rejects_missing_tool_response() -> None:
    with pytest.raises(OpenAIProtocolError, match="missing tool responses"):
        validate_openai_messages(assistant_tool_block()[:1])


def test_validator_accepts_valid_openai_messages() -> None:
    validate_openai_messages(
        [{"role": "user", "content": "hello"}, *assistant_tool_block()]
    )


def test_request_parameter_whitelist_removes_internal_and_unknown_fields() -> None:
    payload = sanitize_openai_payload(
        {"temperature": 0.2, "top_k": 40, "turn_id": "t1", "internal_id": 3},
        provider_extensions={"top_k"},
    )
    assert payload == {"temperature": 0.2, "top_k": 40}


def test_tool_calls_with_non_tool_finish_reason_are_warning_only() -> None:
    errors, warnings = validate_chat_completion_response(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": "done",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "bash", "arguments": "{}"},
                            }
                        ],
                    },
                }
            ]
        }
    )
    assert errors == []
    assert warnings


def test_validator_rejects_assistant_tool_call_after_assistant_text() -> None:
    with pytest.raises(OpenAIProtocolError, match="must immediately follow"):
        validate_openai_messages(
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "thinking"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "bash", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
            ]
        )


def test_validator_accepts_next_tool_call_after_complete_tool_turn() -> None:
    validate_openai_messages(
        [
            {"role": "user", "content": "hello"},
            *assistant_tool_block(),
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {"name": "bash", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_2", "content": "ok"},
        ]
    )
