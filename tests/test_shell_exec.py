"""Regression tests for the bash shell tool.

The tool returns a combined `data.output` field (not separate stdout/stderr)
of the form:
    Exit Code: ...
    Duration: ...ms

    [STDOUT]
    ...

    [STDERR]
    ...
"""

from __future__ import annotations

import pytest
from app.tools.shell_exec import execute as bash_execute, TOOL_DEFINITION


def test_tool_definition_exists():
    assert "bash" in TOOL_DEFINITION


@pytest.mark.asyncio
async def test_simple_command():
    result = await bash_execute({"command": "echo hello"})
    assert result["ok"] is True
    assert "hello" in result["data"]["output"]
    assert result["data"]["exit_code"] == 0


@pytest.mark.asyncio
async def test_pwd():
    result = await bash_execute({"command": "pwd"})
    assert result["ok"] is True
    assert "/" in result["data"]["output"]


@pytest.mark.asyncio
async def test_exit_code():
    result = await bash_execute({"command": "exit 42"})
    assert result["ok"] is True
    assert result["data"]["exit_code"] == 42


@pytest.mark.asyncio
async def test_stderr_capture():
    result = await bash_execute({"command": "echo error >&2"})
    assert result["ok"] is True
    assert "error" in result["data"]["output"]


@pytest.mark.asyncio
async def test_dangerous_command_blocked():
    result = await bash_execute({"command": "rm -rf /"})
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_multiline_command():
    result = await bash_execute({"command": "echo line1 && echo line2"})
    assert result["ok"] is True
    assert "line1" in result["data"]["output"]
    assert "line2" in result["data"]["output"]
