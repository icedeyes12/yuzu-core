from __future__ import annotations

import pytest

import app.prompts as prompts


async def _noop(*args, **kwargs):
    return ""


@pytest.mark.asyncio
async def test_runtime_prompt_uses_native_fc_only(monkeypatch):
    profile = {
        "partner_name": "Yuzu",
        "user_name": "Bani",
    }

    async def _retrieve_memories_async(*args, **kwargs):
        return ([], "", "")

    monkeypatch.setattr(prompts, "_retrieve_memories_async", _retrieve_memories_async)
    monkeypatch.setattr(
        prompts,
        "_get_relevant_tools",
        lambda message: "### Relevant tools\n- Use native function calling only.",
    )
    monkeypatch.setattr(prompts, "_location_block_async", _noop)
    monkeypatch.setattr(prompts, "_session_events_block_async", _noop)
    monkeypatch.setattr(prompts, "_global_knowledge_block_async", _noop)

    prompt = await prompts.build_system_message_async(
        profile=profile,
        session_id="session_1",
        interface="web",
        user_message="please help",
        user_id="user_1",
        provider_supports_fc=True,
    )

    assert "native function calling" in prompt.lower()
    assert "<command>" not in prompt
    assert "</command>" not in prompt

    assert "legacy fallback" not in prompt.lower()
    assert "tool registry" in prompt.lower()


@pytest.mark.asyncio
async def test_build_messages_uses_attachments_without_role_filter(monkeypatch):
    profile = {"partner_name": "Yuzu", "user_name": "Bani"}

    async def _stub_build_system_message_async(*args, **kwargs):
        return "system"

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
        prompts, "build_system_message_async", _stub_build_system_message_async
    )
    monkeypatch.setattr(
        prompts.Database, "get_chat_history_for_ai", _stub_get_chat_history_for_ai_async
    )
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
        include_attachments=True,
    )

    assert messages[0] == {"role": "system", "content": "system"}
    assert messages[1]["role"] == "tool"
    assert isinstance(messages[1]["content"], list)
    assert messages[1]["content"][0]["type"] == "text"
    assert messages[1]["content"][1]["type"] == "image_url"
    assert messages[2] == {"role": "assistant", "content": "plain"}


@pytest.mark.asyncio
async def test_persona_injection_and_missing_data_fallback(monkeypatch):
    # Missing partner_name, user_name, persona_preset, persona_prompt
    profile = {}

    async def _retrieve_memories_async(*args, **kwargs):
        return ([], "", "")

    monkeypatch.setattr(prompts, "_retrieve_memories_async", _retrieve_memories_async)
    monkeypatch.setattr(prompts, "_location_block_async", _noop)
    monkeypatch.setattr(prompts, "_session_events_block_async", _noop)
    monkeypatch.setattr(prompts, "_global_knowledge_block_async", _noop)

    prompt = await prompts.build_system_message_async(
        profile=profile,
        session_id="session_1",
        interface="web",
        user_message="hello",
        user_id="user_1",
    )

    # Verify fallbacks
    assert "You are Yuzu." in prompt
    assert (
        "Communication Style: You are Yuzu, a helpful, friendly AI assistant." in prompt
    )
    assert "You are speaking with the user." in prompt

    # Verify custom persona logic
    profile_custom = {
        "partner_name": "TestAI",
        "user_name": "TestUser",
        "persona_preset": "helpful",
        "persona_prompt": "You are a test persona.",
    }

    prompt_custom = await prompts.build_system_message_async(
        profile=profile_custom,
        session_id="session_1",
        interface="web",
        user_message="hello",
        user_id="user_1",
    )

    assert "You are TestAI." in prompt_custom
    assert "Character Profile: You are a test persona." in prompt_custom
    assert (
        "Communication Style: You are TestAI, a helpful, friendly AI assistant."
        in prompt_custom
    )
