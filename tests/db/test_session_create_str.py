from __future__ import annotations

import uuid

import pytest

import app.db.models_async as models_async


class _FakeAsyncSession:
    """Minimal AsyncPgSession stand-in returning a fixed row from execute_returning."""

    def __init__(self, row):
        self._row = row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute_returning(self, query, params):
        return self._row


@pytest.mark.asyncio
async def test_create_session_async_normalizes_uuid_to_str(monkeypatch) -> None:
    raw_id = uuid.uuid4()

    monkeypatch.setattr(
        models_async,
        "AsyncPgSession",
        lambda: _FakeAsyncSession({"id": raw_id}),
    )

    result = await models_async.create_session_async("New Chat", user_id="uid")
    assert result == str(raw_id)
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_create_session_async_none_row_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(
        models_async,
        "AsyncPgSession",
        lambda: _FakeAsyncSession(None),
    )

    result = await models_async.create_session_async("New Chat", user_id="uid")
    assert result is None
