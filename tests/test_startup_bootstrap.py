from __future__ import annotations

import types

import pytest

import main


class _DummyConn:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def execute(self, query: str) -> None:
        self.queries.append(query)


class _DummyConnContext:
    def __init__(self, conn: _DummyConn) -> None:
        self.conn = conn

    async def __aenter__(self) -> _DummyConn:
        return self.conn

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _DummyAsyncPool:
    def __init__(self, conn: _DummyConn) -> None:
        self.conn = conn

    def connection(self) -> _DummyConnContext:
        return _DummyConnContext(self.conn)


@pytest.mark.asyncio
async def test_lifespan_bootstraps_schema_before_serving(monkeypatch):
    calls: list[str] = []
    conn = _DummyConn()
    app = types.SimpleNamespace(state=types.SimpleNamespace())

    monkeypatch.setattr(main, "get_sync_pool", lambda: object())

    async def _get_async_pool():
        return _DummyAsyncPool(conn)

    async def _bootstrap() -> None:
        calls.append("bootstrap")

    async def _close() -> None:
        calls.append("close")

    monkeypatch.setattr(main, "get_async_pool", _get_async_pool)
    monkeypatch.setattr(main, "init_pg_tables_async", _bootstrap)
    monkeypatch.setattr(main, "close_async_pool", _close)

    async with main.lifespan(app):
        pass

    assert calls == ["bootstrap", "close"]
    assert conn.queries == ["SELECT 1"]
    assert hasattr(app.state, "sync_pool")
    assert hasattr(app.state, "async_pool")
