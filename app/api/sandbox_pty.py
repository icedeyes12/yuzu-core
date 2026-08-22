"""Authenticated WebSocket bridge between xterm.js and a sandbox PTY. ฅ^•ﻌ•^ฅ"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import pty
import select
import signal
import struct
import termios
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth.session import SESSION_COOKIE_NAME, validate_session
from app.db.sandbox_instance_repository import PgSandboxInstanceRepository
from yuzu_sandbox.proot_wrapper import RestrictedPRootBuilder

router = APIRouter(prefix="/sandbox/terminal", tags=["sandbox-pty"])


class PTYSession:
    def __init__(self, master_fd: int, pid: int, generation: int) -> None:
        self.master_fd = master_fd
        self.pid = pid
        self.generation = generation
        self.alive = True

    @classmethod
    def spawn(
        cls,
        argv: list[str],
        *,
        generation: int,
        env: dict[str, str] | None = None,
    ) -> PTYSession:
        pid, master_fd = pty.fork()
        if pid == 0:
            child_env = os.environ.copy()
            child_env.update(env or {})
            os.execvpe(argv[0], argv, child_env)
        return cls(master_fd, pid, generation)

    def resize(self, cols: int, rows: int) -> None:
        if not self.alive or not 2 <= cols <= 1000 or not 1 <= rows <= 500:
            raise ValueError("Invalid terminal dimensions")
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)

    def read(self, size: int = 8192) -> bytes:
        if not self.alive:
            return b""
        readable, _, _ = select.select([self.master_fd], [], [], 0.1)
        return os.read(self.master_fd, size) if readable else b""

    def write(self, data: bytes) -> None:
        if self.alive:
            os.write(self.master_fd, data)

    def close(self) -> None:
        if not self.alive:
            return
        self.alive = False
        with suppress(OSError):
            os.killpg(self.pid, signal.SIGTERM)
        with suppress(OSError):
            os.close(self.master_fd)
        with suppress(ChildProcessError):
            os.waitpid(self.pid, os.WNOHANG)


async def _authenticate(websocket: WebSocket) -> str | None:
    token = websocket.cookies.get(SESSION_COOKIE_NAME)
    return await validate_session(token) if token else None


def _instance_command(instance: dict[str, Any]) -> list[str]:
    builder = RestrictedPRootBuilder()
    return builder.build_exec_args(
        runtime_name=instance["runtime_name"],
        argv=["/bin/bash", "--login"],
    )


async def _send_output(websocket: WebSocket, session: PTYSession) -> None:
    while session.alive:
        try:
            data = await asyncio.to_thread(session.read)
        except OSError:
            break
        if data:
            await websocket.send_text(
                json.dumps({"type": "output", "data": data.decode(errors="replace")})
            )
        else:
            await asyncio.sleep(0.01)


async def _receive_input(websocket: WebSocket, session: PTYSession) -> None:
    while session.alive:
        message = json.loads(await websocket.receive_text())
        message_type = message.get("type")
        if message_type == "input":
            data = message.get("data")
            if not isinstance(data, str):
                raise ValueError("Invalid terminal input")
            session.write(data.encode())
        elif message_type == "resize":
            session.resize(message.get("cols"), message.get("rows"))
        else:
            raise ValueError("Unknown terminal message type")


@router.websocket("/ws")
async def websocket_pty_endpoint(websocket: WebSocket) -> None:
    user_id = await _authenticate(websocket)
    if not user_id:
        await websocket.close(code=4401, reason="Not authenticated")
        return

    instance = await PgSandboxInstanceRepository().get_by_owner(user_id)
    if not instance or instance["state"] != "ready":
        await websocket.close(code=4409, reason="Sandbox is not ready")
        return

    try:
        session = PTYSession.spawn(
            _instance_command(instance),
            generation=instance["generation"],
            env={
                "TERM": "xterm-256color",
                "HOME": "/home/yuzu",
                "USER": "yuzu",
                "LOGNAME": "yuzu",
                "SHELL": "/bin/bash",
            },
        )
    except (OSError, ValueError) as error:
        await websocket.accept()
        await websocket.send_text(json.dumps({"type": "error", "message": str(error)}))
        await websocket.close(code=1011)
        return

    await websocket.accept()
    await websocket.send_text(
        json.dumps({"type": "ready", "generation": session.generation})
    )
    output_task = asyncio.create_task(_send_output(websocket, session))
    input_task = asyncio.create_task(_receive_input(websocket, session))
    try:
        done, pending = await asyncio.wait(
            {output_task, input_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*done, *pending, return_exceptions=True)
    except (WebSocketDisconnect, json.JSONDecodeError, ValueError):
        pass
    finally:
        session.close()
