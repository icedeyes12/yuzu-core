from __future__ import annotations

import pytest

from app.tools.python_exec import TOOL_DEFINITION
from app.tools.python_exec import execute as python_execute


def test_tool_definition_exists():
    assert TOOL_DEFINITION.name == "python"


@pytest.mark.asyncio
async def test_simple_expression():
    result = await python_execute({"code": "print(2+2)"})
    assert result["ok"] is True
    assert "4" in result["data"]["output"]


@pytest.mark.asyncio
async def test_multiline_code():
    result = await python_execute({"code": "import os\nprint(os.getcwd())"})
    assert result["ok"] is True
    assert "/" in result["data"]["output"]


@pytest.mark.asyncio
async def test_syntax_error():
    result = await python_execute({"code": "def foo("})
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_timeout():
    result = await python_execute(
        {"code": "import time; time.sleep(999)", "timeout": 0.5}
    )
    assert result["ok"] is False
