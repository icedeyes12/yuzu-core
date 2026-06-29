from __future__ import annotations

import asyncio

import pytest

import app.db.facade as db_module
from app.db import Database


@pytest.fixture
def fake_active(monkeypatch):
    """Stub get_active_session_async() so _resolve_session_id_async returns a known id."""
    sentinel_id = "4242"

    async def fake_get_active(user_id):
        return {"id": sentinel_id}

    monkeypatch.setattr(db_module, "_pg_get_active_session_async", fake_get_active)
    return sentinel_id


class TestSessionIdResolution:
    def test_uses_explicit_session_id(self, monkeypatch):
        captured = {}

        async def fake_add_message(
            session_id, role, content, image_paths, user_id, **kwargs
        ):
            captured["session_id"] = session_id
            captured["role"] = role
            captured["content"] = content
            captured["image_paths"] = image_paths
            return 99

        monkeypatch.setattr(db_module, "_pg_add_message_async", fake_add_message)

        result = asyncio.run(
            Database.add_message(
                "user", "hi", session_id="7", image_paths=None, user_id="uid"
            )
        )
        assert result == 99
        assert captured == {
            "session_id": "7",
            "role": "user",
            "content": "hi",
            "image_paths": None,
        }

    def test_falls_back_to_active_session(self, monkeypatch, fake_active):
        captured = {}

        async def fake_add_message(
            session_id, role, content, image_paths, user_id, **kwargs
        ):
            captured["session_id"] = session_id
            return 1

        monkeypatch.setattr(db_module, "_pg_add_message_async", fake_add_message)

        asyncio.run(Database.add_message("user", "hi", user_id="uid"))
        assert captured["session_id"] == fake_active

    def test_resolve_helper_passes_through_explicit_id(self):
        assert asyncio.run(db_module._resolve_session_id_async("7", "uid")) == "7"

    def test_resolve_helper_uses_active_for_none(self, fake_active):
        assert (
            asyncio.run(db_module._resolve_session_id_async(None, "uid")) == fake_active
        )


class TestArgumentReordering:
    def test_get_messages_default_limit(self, monkeypatch, fake_active):
        captured = {}

        async def fake_get(session_id, limit, user_id=None):
            captured["args"] = (session_id, limit)
            return []

        monkeypatch.setattr(db_module, "_pg_get_session_messages_async", fake_get)

        asyncio.run(Database.get_messages(user_id="uid"))
        assert captured["args"] == (fake_active, 100)

    def test_get_chat_history_recent_flag_passes(self, monkeypatch, fake_active):
        captured = {}

        async def fake_get(session_id, limit, recent, user_id=None):
            captured["args"] = (session_id, limit, recent)
            return []

        monkeypatch.setattr(db_module, "_pg_get_chat_history_async", fake_get)

        asyncio.run(Database.get_chat_history(limit=20, recent=True, user_id="uid"))
        assert captured["args"] == (fake_active, 20, True)

    def test_clear_session_uses_active(self, monkeypatch, fake_active):
        captured = {}

        async def fake_clear(session_id, user_id=None):
            captured["session_id"] = session_id
            return True

        monkeypatch.setattr(db_module, "_pg_clear_session_messages_async", fake_clear)

        assert asyncio.run(Database.clear_session(user_id="uid")) is True
        assert captured["session_id"] == fake_active

    def test_clear_chat_history_is_alias(self, monkeypatch):
        called = {}

        async def fake_clear(session_id):
            called["session_id"] = session_id
            return True

        monkeypatch.setattr(db_module, "_pg_clear_session_messages_async", fake_clear)
        asyncio.run(Database.clear_chat_history(session_id="5", user_id="uid"))
        assert called == {"session_id": "5"}


class TestProxiedMethods:
    def test_get_profile_proxies_directly(self, monkeypatch):
        async def fake_profile(user_id):
            return {"id": 1, "display_name": "x"}

        monkeypatch.setattr(Database, "get_profile", staticmethod(fake_profile))
        result = asyncio.run(Database.get_profile("uid"))
        assert result == {"id": 1, "display_name": "x"}

    def test_get_api_key_passes_name(self, monkeypatch):
        captured = {}

        async def fake_get_key(name):
            captured["name"] = name
            return "sk-abc"

        monkeypatch.setattr(Database, "get_api_key", staticmethod(fake_get_key))
        assert asyncio.run(Database.get_api_key("chutes")) == "sk-abc"
        assert captured["name"] == "chutes"
