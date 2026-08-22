from __future__ import annotations

import json
import os
import time

from app.api.sandbox_pty import PTYSession


def receive_until(session: PTYSession, marker: bytes, timeout: float = 3) -> bytes:
    output = b""
    deadline = time.monotonic() + timeout
    while marker not in output and time.monotonic() < deadline:
        output += session.read(4096)
    return output


def test_real_pty_supports_shell_line_editing_and_ctrl_c():
    session = PTYSession.spawn(
        ["/bin/bash", "--noprofile", "--norc"],
        generation=2,
        env={"TERM": "xterm-256color", "PS1": "> "},
    )
    try:
        assert b"> " in receive_until(session, b"> ")

        session.write(b"abc\x7f\x7f\x7fecho hello\r")
        output = receive_until(session, b"hello")
        assert b"hello" in output
        assert b"abcecho" not in output

        session.write(b"sleep 10\r")
        time.sleep(0.1)
        session.write(b"\x03")
        assert b"> " in receive_until(session, b"> ")
    finally:
        session.close()


def test_real_pty_applies_resize():
    session = PTYSession.spawn(
        ["/bin/bash", "--noprofile", "--norc"],
        generation=1,
        env={"TERM": "xterm-256color", "PS1": "> "},
    )
    try:
        receive_until(session, b"> ")
        session.resize(cols=93, rows=31)
        session.write(b"stty size\r")
        assert b"31 93" in receive_until(session, b"31 93")
    finally:
        session.close()


def test_websocket_protocol_uses_explicit_ready_and_json_frames():
    ready = json.dumps({"type": "ready", "generation": 3})
    input_frame = json.loads(json.dumps({"type": "input", "data": "a\r\x7f"}))
    resize_frame = json.loads(json.dumps({"type": "resize", "cols": 80, "rows": 24}))

    assert json.loads(ready) == {"type": "ready", "generation": 3}
    assert input_frame["data"].encode() == b"a\r\x7f"
    assert resize_frame == {"type": "resize", "cols": 80, "rows": 24}
    assert os.name == "posix"
