from __future__ import annotations

import os
import tempfile
from app.tools.fs_operations import (
    execute_read,
    execute_write,
    execute_ls,
    execute_mkdir,
    execute_rm,
    TOOL_DEFINITION,
)


def test_tool_definition_exists():
    assert TOOL_DEFINITION.name == "read"


def test_ls_tmp_dir():
    result = execute_ls({"path": "/tmp"})
    assert result["ok"] is True
    assert "listing" in result["data"]


def test_read_write_roundtrip():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("hello world")
        path = f.name
    try:
        r = execute_read({"path": path})
        assert r["ok"] is True
        assert "hello world" in r["data"]["content"]
    finally:
        os.unlink(path)


def test_write_new_file():
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        path = f.name
    os.unlink(path)
    try:
        r = execute_write({"path": path, "content": "test content"})
        assert r["ok"] is True
        assert os.path.exists(path)
        with open(path) as f:
            assert f.read() == "test content"
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_mkdir_and_rm():
    with tempfile.TemporaryDirectory() as tmp:
        new_dir = os.path.join(tmp, "newdir")
        r1 = execute_mkdir({"path": new_dir})
        assert r1["ok"] is True
        assert os.path.isdir(new_dir)

        r2 = execute_rm({"path": new_dir})
        assert r2["ok"] is True
        assert not os.path.exists(new_dir)


def test_missing_path_returns_error():
    r = execute_read({"path": "/nonexistent/path/xyz123"})
    assert r["ok"] is False


def test_write_heredoc():
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        path = f.name
    os.unlink(path)
    try:
        content = "line1\nline2\nline3"
        r = execute_write({"path": path, "content": content})
        assert r["ok"] is True
        with open(path) as f:
            assert f.read() == content
    finally:
        if os.path.exists(path):
            os.unlink(path)
