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


@pytest.mark.asyncio
async def test_auto_name_uses_tenant_scoped_count_and_atomic_rename(monkeypatch):
    calls = []

    async def count(session_id, *, user_id):
        calls.append(("count", session_id, user_id))
        return 10

    async def profile(_user_id):
        return {"providers_config": {}}

    async def title(*_args, **_kwargs):
        return "Stable title"

    async def rename(session_id, name, user_id):
        calls.append(("rename", session_id, name, user_id))
        return True

    monkeypatch.setattr(SessionService, "_auto_name_with_llm", title)
    monkeypatch.setattr(SessionService, "_auto_name_from_history", title)
    monkeypatch.setattr("app.services.session_service.Database.get_profile", profile)
    monkeypatch.setattr(
        "app.services.session_service.Database.get_session_messages_count", count
    )
    monkeypatch.setattr(
        "app.services.session_service.Database.rename_session_if_placeholder", rename
    )

    await SessionService.auto_name_session_if_needed_async(
        "session", {"name": "New Chat"}, user_id="user"
    )

    assert calls == [
        ("count", "session", "user"),
        ("rename", "session", "Stable title", "user"),
    ]


@pytest.mark.asyncio
async def test_auto_name_does_not_leak_session_name_to_logs(monkeypatch, caplog):
    """Test that generated session names are not logged to prevent data leakage."""
    async def count(session_id, *, user_id):
        return 10

    async def profile(_user_id):
        return {"providers_config": {}}

    sensitive_title = "My Secret Project Discussion"

    async def title(*_args, **_kwargs):
        return sensitive_title

    async def rename(session_id, name, user_id):
        return True

    monkeypatch.setattr(SessionService, "_auto_name_with_llm", title)
    monkeypatch.setattr(SessionService, "_auto_name_from_history", title)
    monkeypatch.setattr("app.services.session_service.Database.get_profile", profile)
    monkeypatch.setattr(
        "app.services.session_service.Database.get_session_messages_count", count
    )
    monkeypatch.setattr(
        "app.services.session_service.Database.rename_session_if_placeholder", rename
    )

    await SessionService.auto_name_session_if_needed_async(
        "test-session-id", {"name": "New Chat"}, user_id="test-user"
    )

    # Verify the title is NOT in any log messages
    log_output = caplog.text
    assert sensitive_title not in log_output
    # Verify the session ID IS in the log (for debugging)
    assert "test-session-id" in log_output
