from __future__ import annotations

from types import SimpleNamespace

from app.tools.db_query import execute as sql_execute, TOOL_DEFINITION


def test_tool_definition_exists():
    assert TOOL_DEFINITION.name == "sql"


def _fake_psql_ok(stdout: str = "") -> SimpleNamespace:
    """Build a fake CompletedProcess-like object for a successful psql run."""
    return SimpleNamespace(stdout=stdout, stderr="", returncode=0)


def test_simple_select(monkeypatch):
    monkeypatch.setattr(
        "app.tools.db_query.subprocess.run",
        lambda cmd, **kw: _fake_psql_ok("1"),
    )
    result = sql_execute({"query": "SELECT 1 as num"})
    assert result["ok"] is True
    assert result["data"]["row_count"] == 1


def test_select_tables(monkeypatch):
    monkeypatch.setattr(
        "app.tools.db_query.subprocess.run",
        lambda cmd, **kw: _fake_psql_ok("profiles\nchat_sessions\nmessages"),
    )
    result = sql_execute(
        {
            "query": "SELECT table_name FROM information_schema.tables WHERE table_schema='public' LIMIT 3"
        }
    )
    assert result["ok"] is True
    assert result["data"]["row_count"] <= 3


def test_invalid_sql():
    result = sql_execute({"query": "SELECT * FROM nonexistent_table_xyz"})
    assert result["ok"] is False


def test_write_blocked_by_default():
    result = sql_execute({"query": "CREATE TABLE test_should_fail (id int)"})
    assert result["ok"] is False


def test_write_with_flag(monkeypatch):
    # --write must be a PREFIX of the query string (not a dict key).
    # The query string "--write INSERT ..." enables write_mode=True so the
    # write-keyword validation passes; mocked psql returns success.
    monkeypatch.setattr(
        "app.tools.db_query.subprocess.run",
        lambda cmd, **kw: _fake_psql_ok("INSERT 0 1"),
    )
    result = sql_execute({"query": "--write INSERT INTO test_ok VALUES (1)"})
    assert result["ok"] is True
    assert result["data"]["write_mode"] is True
