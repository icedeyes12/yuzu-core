from __future__ import annotations

from app.core.llm_context import LLMContext
from app.providers.custom_openai import CustomOpenAIProvider


def test_custom_openai_payload_preserves_valid_tool_turn_order() -> None:
    provider = CustomOpenAIProvider()
    _, payload = provider._prepare_payload(
        LLMContext(provider="custom_openai", model="test-model", api_key="test-key"),
        [
            {"role": "system", "content": "system", "internal_id": 1},
            {"role": "user", "content": "call a tool", "turn_id": "turn_1"},
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
                "timestamp": "internal",
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": "ok",
                "db_id": 2,
            },
        ],
        False,
        tools=[{"type": "function", "function": {"name": "bash"}}],
    )

    assert [message["role"] for message in payload["messages"]] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]
    assert "turn_id" not in payload["messages"][1]
    assert "timestamp" not in payload["messages"][2]
    assert "db_id" not in payload["messages"][3]
    assert payload["messages"][2]["tool_calls"][0]["id"] == "call_1"
    assert payload["messages"][3]["tool_call_id"] == "call_1"
