from __future__ import annotations

import pytest

from app.core.context import RequestKeyring, clear_request_keyring, set_request_keyrings
from app.services.session_service import SessionService


async def _history(*_args, **_kwargs):
    return [{"role": "user", "content": "Discuss memory architecture"}]


@pytest.mark.asyncio
async def test_session_title_uses_portal_yuzuki_before_active_provider(monkeypatch):
    calls = []

    class Manager:
        async def _internal_llm_call(self, *, messages, source, profile, **kwargs):
            calls.append((source, profile["providers_config"].copy()))
            return "Portal title"

    async def manager():
        return Manager()

    monkeypatch.setattr("app.providers.get_ai_manager", manager)
    monkeypatch.setattr(
        "app.services.session_service.Database.get_chat_history", _history
    )
    set_request_keyrings(
        {
            "openrouter": RequestKeyring(provider="openrouter", key="chat-key"),
            "yuzu_portal": RequestKeyring(provider="yuzu_portal", key="portal-key"),
        }
    )
    try:
        result = await SessionService._auto_name_with_llm(
            "session",
            {
                "providers_config": {
                    "preferred_provider": "openrouter",
                    "preferred_model": "chat-model",
                }
            },
            "user",
        )
    finally:
        clear_request_keyring()

    assert result == "Portal title"
    assert calls == [
        (
            "session_title",
            {"preferred_provider": "yuzu_portal", "preferred_model": "yuzuki"},
        )
    ]


@pytest.mark.asyncio
async def test_session_title_falls_back_to_active_provider_without_portal(monkeypatch):
    calls = []

    class Manager:
        async def _internal_llm_call(self, *, messages, source, profile, **kwargs):
            calls.append(profile["providers_config"].copy())
            return "Active title"

    async def manager():
        return Manager()

    monkeypatch.setattr("app.providers.get_ai_manager", manager)
    monkeypatch.setattr(
        "app.services.session_service.Database.get_chat_history", _history
    )
    set_request_keyrings(
        {"openrouter": RequestKeyring(provider="openrouter", key="chat-key")}
    )
    try:
        result = await SessionService._auto_name_with_llm(
            "session",
            {
                "providers_config": {
                    "preferred_provider": "openrouter",
                    "preferred_model": "chat-model",
                }
            },
            "user",
        )
    finally:
        clear_request_keyring()

    assert result == "Active title"
    assert calls == [
        {"preferred_provider": "openrouter", "preferred_model": "chat-model"}
    ]


@pytest.mark.asyncio
async def test_session_title_skips_without_portal_or_active_provider(monkeypatch):
    monkeypatch.setattr(
        "app.services.session_service.get_provider_key", lambda _provider: None
    )
    monkeypatch.setattr(
        "app.services.session_service.Database.get_chat_history",
        _history,
    )
    set_request_keyrings({})
    try:
        result = await SessionService._auto_name_with_llm(
            "session", {"providers_config": {}}, "user"
        )
    finally:
        clear_request_keyring()

    assert result is None
