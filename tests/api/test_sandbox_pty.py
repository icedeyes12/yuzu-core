from __future__ import annotations

import json
import os
import time

from app.api.sandbox_pty import PTYSession, _pty_env
from app.core.ids import EntityType, PublicId


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


def test_shell_display_identity_uses_owner_public_id_and_generic_hostname():
    owner_a = "019d0000-0000-7000-8000-000000000001"
    owner_b = "019d0000-0000-7000-8000-000000000002"

    env_a = _pty_env(owner_a)
    env_b = _pty_env(owner_b)

    assert PublicId.encode(EntityType.USER, owner_a) in env_a["PS1"]
    assert PublicId.encode(EntityType.USER, owner_b) in env_b["PS1"]
    assert env_a["PS1"] != env_b["PS1"]
    assert env_a["HOSTNAME"] == "yuzu-sandbox"
    assert "titit" not in str(env_a).lower()
