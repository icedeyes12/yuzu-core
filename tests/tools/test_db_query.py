from __future__ import annotations

from types import SimpleNamespace

import pytest
from psycopg import errors

from app.tools.db_query import QUERY_TIMEOUT, TOOL_DEFINITION
from app.tools.db_query import execute as sql_execute


def test_tool_definition_exists():
    assert TOOL_DEFINITION.name == "sql"


class _FakeCursor:
    """Fake psycopg cursor: rows are dicts (dict_row factory), columns are names."""

    def __init__(self, rows=None, columns=None, status="SELECT 1", error=None):
        self._rows = rows or []
        self._columns = columns
        self._status = status
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query):
        if self._error is not None:
            raise self._error

    @property
    def description(self):
        if self._columns is None:
            return None
        return [SimpleNamespace(name=c) for c in self._columns]

    @property
    def statusmessage(self):
        return self._status

    def fetchall(self):
        return self._rows


class _FakePgSession:
    """Fake PgSession with a record of executed session-level statements."""

    def __init__(self, cursor):
        self.conn = SimpleNamespace(cursor=lambda: cursor)
        self.executed: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query):
        self.executed.append(query)


@pytest.fixture
def fake_pg(monkeypatch):
    """Patch PgSession with a fake; returns a holder capturing the created session."""

    def _install(cursor) -> dict:
        holder: dict = {}

        def _factory():
            session = _FakePgSession(cursor)
            holder["session"] = session
            return session

        monkeypatch.setattr("app.tools.db_query.PgSession", _factory)
        return holder

    return _install


def test_simple_select(fake_pg):
    holder = fake_pg(_FakeCursor(rows=[{"num": 1}], columns=["num"], status="SELECT 1"))
    result = sql_execute({"query": "SELECT 1 as num"})
    assert result["ok"] is True
    assert result["data"]["row_count"] == 1
    assert result["data"]["rows"] == [{"num": "1"}]
    assert result["data"]["columns"] == ["num"]
    # statement timeout is applied on the pooled session before the query
    assert holder["session"].executed == [
        f"SET LOCAL statement_timeout = {QUERY_TIMEOUT * 1000}"
    ]


def test_select_tables(fake_pg):
    fake_pg(
        _FakeCursor(
            rows=[{"table_name": "profiles"}, {"table_name": "chat_sessions"}],
            columns=["table_name"],
            status="SELECT 2",
        )
    )
    result = sql_execute(
        {
            "query": "SELECT table_name FROM information_schema.tables WHERE table_schema='public' LIMIT 3"
        }
    )
    assert result["ok"] is True
    assert result["data"]["row_count"] <= 3
    assert result["data"]["rows"][0]["table_name"] == "profiles"


def test_invalid_sql(fake_pg):
    fake_pg(
        _FakeCursor(
            error=errors.ProgrammingError(
                'relation "nonexistent_table_xyz" does not exist'
            )
        )
    )
    result = sql_execute({"query": "SELECT * FROM nonexistent_table_xyz"})
    assert result["ok"] is False
    assert "Query failed:" in result["error"]


def test_query_timeout(fake_pg):
    fake_pg(
        _FakeCursor(
            error=errors.QueryCanceled("canceling statement due to statement timeout")
        )
    )
    result = sql_execute({"query": "SELECT pg_sleep(100)"})
    assert result["ok"] is False
    assert result["error"] == f"Query timed out after {QUERY_TIMEOUT}s"


def test_null_values_become_empty_strings(fake_pg):
    fake_pg(_FakeCursor(rows=[{"a": None, "b": 3}], columns=["a", "b"]))
    result = sql_execute({"query": "SELECT NULL as a, 3 as b"})
    assert result["ok"] is True
    assert result["data"]["rows"] == [{"a": "", "b": "3"}]


def test_write_blocked_by_default():
    result = sql_execute({"query": "CREATE TABLE test_should_fail (id int)"})
    assert result["ok"] is False


def test_write_with_flag(fake_pg):
    # --write must be a PREFIX of the query string (not a dict key).
    # The query string "--write INSERT ..." enables write_mode=True so the
    # write-keyword validation passes; the fake pool returns the command tag.
    fake_pg(_FakeCursor(status="INSERT 0 1", columns=None))
    result = sql_execute({"query": "--write INSERT INTO test_ok VALUES (1)"})
    assert result["ok"] is True
    assert result["data"]["write_mode"] is True
    assert result["data"]["rows"] == [{"result": "INSERT 0 1"}]
    assert result["data"]["columns"] == ["result"]
