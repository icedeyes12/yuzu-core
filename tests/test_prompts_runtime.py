from __future__ import annotations

import pytest

import app.services.prompt_service as prompts


async def _noop(*args, **kwargs):
    return ""


@pytest.mark.asyncio
async def test_runtime_prompt_uses_native_fc_only(monkeypatch):
    profile = {
        "character_profile": "",
        "personality_preset": "helpful",
        "personality_custom": "",
    }

    async def _retrieve_memories_async(*args, **kwargs):
        return ([], "", "")

    monkeypatch.setattr(prompts, "_retrieve_memories_async", _retrieve_memories_async)
    monkeypatch.setattr(
        prompts,
        "_get_relevant_tools",
        lambda message: "### Relevant tools\n- Use native function calling only.",
    )
    monkeypatch.setattr(prompts, "_session_events_block_async", _noop)
    monkeypatch.setattr(prompts, "_global_knowledge_block_async", _noop)
    monkeypatch.setattr(prompts.Database, "get_chat_history_for_ai", _noop)

    messages = await prompts.build_messages(
        profile=profile,
        session_id="session_1",
        interface="web",
        user_message="please help",
        user_id="user_1",
    )
    prompt = messages[0]["content"]

    assert "native function calling" in prompt.lower()
    assert "<command>" not in prompt
    assert "</command>" not in prompt
    assert "legacy fallback" not in prompt.lower()
    assert "runtime dispatches tools" in prompt.lower()


@pytest.mark.asyncio
async def test_build_messages_uses_attachments_without_role_filter(monkeypatch):
    profile = {"character_profile": "", "personality_preset": "helpful"}

    async def _stub_get_chat_history_for_ai_async(*args, **kwargs):
        return [
            {
                "role": "tool",
                "content": "result",
                "attachments": ["/tmp/img-a.png"],
            },
            {
                "role": "assistant",
                "content": "plain",
                "attachments": [],
            },
        ]

    monkeypatch.setattr(
        prompts.Database, "get_chat_history_for_ai", _stub_get_chat_history_for_ai_async
    )
    monkeypatch.setattr(prompts, "_global_knowledge_block_async", _noop)
    monkeypatch.setattr(prompts, "_session_events_block_async", _noop)
    monkeypatch.setattr(prompts.os.path, "exists", lambda path: True)
    monkeypatch.setattr(
        prompts,
        "_encode_image_safe",
        lambda path: {"type": "image_url", "image_url": {"url": f"data:{path}"}},
    )

    messages = await prompts.build_messages(
        profile=profile,
        session_id="s1",
        interface="web",
        user_message="hello",
        user_id="u1",
    )

    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "assistant", "content": "plain"}


@pytest.mark.asyncio
async def test_personality_pipeline_and_verbatim_character_profile(monkeypatch):
    profile = {
        "character_profile": "Raw character profile\nwith exact spacing.",
        "personality_preset": "custom",
        "personality_custom": "RAW custom personality\nDo not rewrite.",
    }

    async def _retrieve_memories_async(*args, **kwargs):
        return ([], "", "")

    monkeypatch.setattr(prompts, "_retrieve_memories_async", _retrieve_memories_async)
    monkeypatch.setattr(prompts, "_global_knowledge_block_async", _noop)
    monkeypatch.setattr(prompts, "_session_events_block_async", _noop)
    monkeypatch.setattr(prompts.Database, "get_chat_history_for_ai", _noop)

    messages = await prompts.build_messages(
        profile=profile,
        session_id="session_1",
        interface="web",
        user_message="hello",
        user_id="user_1",
    )
    prompt = messages[0]["content"]

    assert prompt.split("\n\n")[:2] == [
        profile["character_profile"],
        profile["personality_custom"],
    ]
    assert "# TECHNICAL SYSTEM RULES" in prompt
    assert all(label not in prompt for label in ("Communication", "Style"))
    assert all(value not in prompt for value in prompts.PERSONALITIES.values())


@pytest.mark.asyncio
async def test_preset_personality_uses_exact_dictionary_value(monkeypatch):
    async def _retrieve_memories_async(*args, **kwargs):
        return ([], "", "")

    monkeypatch.setattr(prompts, "_retrieve_memories_async", _retrieve_memories_async)
    monkeypatch.setattr(prompts, "_global_knowledge_block_async", _noop)
    monkeypatch.setattr(prompts, "_session_events_block_async", _noop)
    monkeypatch.setattr(prompts.Database, "get_chat_history_for_ai", _noop)

    messages = await prompts.build_messages(
        profile={"personality_preset": "technical"},
        session_id="session_1",
        interface="web",
        user_message="hello",
        user_id="user_1",
    )

    prompt = messages[0]["content"]
    assert prompts.PERSONALITIES["technical"] in prompt
    assert all(
        key == "technical" or value not in prompt
        for key, value in prompts.PERSONALITIES.items()
    )


def test_tool_call_history_is_trimmed_as_atomic_block() -> None:
    from app.services.prompt_service import _trim_history_to_token_limit

    assistant = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "bash", "arguments": "{}"},
            }
        ],
    }
    tool = {"role": "tool", "tool_call_id": "call_1", "content": "result"}
    history = [
        {"role": "user", "content": "old context " * 20},
        assistant,
        tool,
        {"role": "user", "content": "latest"},
    ]

    trimmed = _trim_history_to_token_limit(history, max_tokens=100)
    assert trimmed[-1] == history[-1]
    assert not any(message is assistant for message in trimmed) or tool in trimmed
    assert (
        not any(message.get("role") == "tool" for message in trimmed)
        or assistant in trimmed
    )
