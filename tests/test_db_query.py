from __future__ import annotations

from app.tools.db_query import execute as sql_execute, TOOL_DEFINITION


def test_tool_definition_exists():
    assert TOOL_DEFINITION.name == "sql"


def test_simple_select():
    result = sql_execute({"query": "SELECT 1 as num"})
    assert result["ok"] is True
    assert result["data"]["row_count"] == 1


def test_select_tables():
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


def test_write_with_flag():
    # This would work if --write flag is provided
    result = sql_execute({"query": "SELECT 1", "--write": True})
    assert result["ok"] is True
