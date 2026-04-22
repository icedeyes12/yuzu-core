# FILE: tests/test_database_facade.py
# DESCRIPTION: Tests for the session-id-defaulting wrappers in the Database
#              facade. Uses monkeypatching so no live PostgreSQL is required.

from __future__ import annotations

import pytest

from app import database as db_module
from app.database import Database


@pytest.fixture
def fake_active(monkeypatch):
    """Stub get_active_session() so _resolve_session_id returns a known id."""
    sentinel_id = 4242
    monkeypatch.setattr(
        db_module, "_pg_get_active_session", lambda: {"id": sentinel_id}
    )
    return sentinel_id


class TestSessionIdResolution:
    def test_uses_explicit_session_id(self, monkeypatch):
        captured = {}

        def fake_add_message(session_id, role, content, image_paths):
            captured["session_id"] = session_id
            captured["role"] = role
            captured["content"] = content
            captured["image_paths"] = image_paths
            return 99

        monkeypatch.setattr(db_module, "_pg_add_message", fake_add_message)

        result = Database.add_message("user", "hi", session_id=7, image_paths=None)
        assert result == 99
        assert captured == {
            "session_id": 7,
            "role": "user",
            "content": "hi",
            "image_paths": None,
        }

    def test_falls_back_to_active_session(self, monkeypatch, fake_active):
        captured = {}

        def fake_add_message(session_id, role, content, image_paths):
            captured["session_id"] = session_id
            return 1

        monkeypatch.setattr(db_module, "_pg_add_message", fake_add_message)

        Database.add_message("user", "hi")
        assert captured["session_id"] == fake_active

    def test_resolve_helper_passes_through_explicit_id(self):
        assert db_module._resolve_session_id(7) == 7

    def test_resolve_helper_uses_active_for_none(self, fake_active):
        assert db_module._resolve_session_id(None) == fake_active


class TestArgumentReordering:
    def test_get_messages_default_limit(self, monkeypatch, fake_active):
        captured = {}

        def fake_get(session_id, limit):
            captured["args"] = (session_id, limit)
            return []

        monkeypatch.setattr(db_module, "_pg_get_session_messages", fake_get)

        Database.get_messages()
        assert captured["args"] == (fake_active, 100)

    def test_get_chat_history_recent_flag_passes(self, monkeypatch, fake_active):
        captured = {}

        def fake_get(session_id, limit, recent):
            captured["args"] = (session_id, limit, recent)
            return []

        monkeypatch.setattr(db_module, "_pg_get_chat_history", fake_get)

        Database.get_chat_history(limit=20, recent=True)
        assert captured["args"] == (fake_active, 20, True)

    def test_clear_session_uses_active(self, monkeypatch, fake_active):
        captured = {}

        def fake_clear(session_id):
            captured["session_id"] = session_id
            return True

        monkeypatch.setattr(db_module, "_pg_clear_session_messages", fake_clear)

        assert Database.clear_session() is True
        assert captured["session_id"] == fake_active

    def test_clear_chat_history_is_alias(self, monkeypatch):
        called = {}

        def fake_clear(session_id):
            called["session_id"] = session_id
            return True

        monkeypatch.setattr(db_module, "_pg_clear_session_messages", fake_clear)
        Database.clear_chat_history(session_id=5)
        assert called == {"session_id": 5}

    def test_add_memory_note_is_alias_for_system_note(self, monkeypatch):
        captured = {}

        def fake_add(session_id, role, content, image_paths):
            captured["session_id"] = session_id
            captured["role"] = role
            captured["content"] = content
            return 1

        monkeypatch.setattr(db_module, "_pg_add_message", fake_add)

        Database.add_memory_note("hello", session_id=11)
        assert captured == {"session_id": 11, "role": "system", "content": "hello"}


class TestProxiedMethods:
    def test_get_profile_proxies_directly(self, monkeypatch):
        called = {"hits": 0}

        def fake_profile():
            called["hits"] += 1
            return {"id": 1, "display_name": "x"}

        monkeypatch.setattr(db_module, "_pg_get_profile", fake_profile)
        result = Database.get_profile()
        assert result == {"id": 1, "display_name": "x"}
        assert called["hits"] == 1

    def test_get_api_key_passes_name(self, monkeypatch):
        captured = {}

        def fake_get_key(name):
            captured["name"] = name
            return "sk-abc"

        monkeypatch.setattr(db_module, "_pg_get_api_key", fake_get_key)
        assert Database.get_api_key("chutes") == "sk-abc"
        assert captured["name"] == "chutes"
