from __future__ import annotations

from app.tools.python_exec import execute as python_execute, TOOL_DEFINITION


def test_tool_definition_exists():
    assert TOOL_DEFINITION.name == "python"


def test_simple_expression():
    result = python_execute({"code": "print(2+2)"})
    assert result["ok"] is True
    assert "4" in result["data"]["output"]


def test_multiline_code():
    result = python_execute({"code": "import os\nprint(os.getcwd())"})
    assert result["ok"] is True
    assert "/" in result["data"]["output"]


def test_syntax_error():
    result = python_execute({"code": "def foo("})
    assert result["ok"] is False


def test_timeout():
    result = python_execute({"code": "import time; time.sleep(999)"})
    assert result["ok"] is False
