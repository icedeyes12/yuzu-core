from __future__ import annotations

from app.tools.shell_exec import execute as bash_execute, TOOL_DEFINITION


def test_tool_definition_exists():
    assert TOOL_DEFINITION.name == "bash"


def test_simple_command():
    result = bash_execute({"command": "echo hello"})
    assert result["ok"] is True
    assert "hello" in result["data"]["stdout"]


def test_pwd():
    result = bash_execute({"command": "pwd"})
    assert result["ok"] is True
    assert "/" in result["data"]["stdout"]


def test_exit_code():
    result = bash_execute({"command": "exit 42"})
    assert result["ok"] is True
    assert result["data"]["exit_code"] == 42


def test_stderr_capture():
    result = bash_execute({"command": "echo error >&2"})
    assert result["ok"] is True
    assert "error" in result["data"]["stderr"]


def test_dangerous_command_blocked():
    result = bash_execute({"command": "rm -rf /"})
    assert result["ok"] is False


def test_multiline_command():
    result = bash_execute({"command": "echo line1 && echo line2"})
    assert result["ok"] is True
    assert "line1" in result["data"]["stdout"]
    assert "line2" in result["data"]["stdout"]
