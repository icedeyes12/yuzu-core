from __future__ import annotations

import pytest

import app.prompts as prompts


async def _noop(*args, **kwargs):
    return ""


@pytest.mark.asyncio
async def test_runtime_prompt_uses_native_fc_only(monkeypatch):
    profile = {
        "partner_name": "Yuzu",
        "display_name": "Bani",
    }

    async def _retrieve_memories_async(*args, **kwargs):
        return ([], "", "")

    async def _legacy_memory_block_async(*args, **kwargs):
        return ""

    monkeypatch.setattr(prompts, "_retrieve_memories_async", _retrieve_memories_async)
    monkeypatch.setattr(prompts, "_mark_facts_pending_async", _noop)
    monkeypatch.setattr(
        prompts, "_legacy_memory_block_async", _legacy_memory_block_async
    )
    monkeypatch.setattr(
        prompts,
        "_get_relevant_tools",
        lambda message: "### Relevant tools\n- Use native function calling only.",
    )
    monkeypatch.setattr(prompts, "_location_block_async", _noop)
    monkeypatch.setattr(prompts, "_session_events_block_async", _noop)

    prompt = await prompts.build_system_message_async(
        profile=profile,
        session_id="session_1",
        interface="web",
        user_message="please help",
        user_id="user_1",
        suppress_tools=False,
        provider_supports_fc=True,
    )

    assert "native function calling" in prompt.lower()
    assert "<command>" not in prompt
    assert "</command>" not in prompt
    assert "legacy fallback" not in prompt.lower()
