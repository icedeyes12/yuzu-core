"""
Sandbox Execution Dispatcher for User Tools (Terminal, Python, File Operations).
Routes LLM-called tool commands into the user's isolated PRoot environment.
ฅ^•ﻌ•^ฅ
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.db.sandbox_instance_repository import PgSandboxInstanceRepository
from yuzu_sandbox.proot_wrapper import RestrictedPRootBuilder


class SandboxToolDispatcher:
    """Dispatches tool operations directly into caller's active sandbox instance."""

    def __init__(
        self,
        repository: PgSandboxInstanceRepository | None = None,
        builder: RestrictedPRootBuilder | None = None,
    ) -> None:
        self.repository = repository or PgSandboxInstanceRepository()
        self.builder = builder or RestrictedPRootBuilder()

    async def execute_command(
        self,
        user_id: str,
        argv: list[str],
        cwd: str = "/home/yuzu",
        timeout_seconds: int = 30,
    ) -> dict[str, Any]:
        """Execute an argv command inside user's active PRoot environment."""
        instance = await self.repository.get_by_owner(user_id)
        if not instance or instance["state"] != "ready":
            return {
                "ok": False,
                "error": "My Computer sandbox is not ready. Please provision it first under /computer.",
                "data": {},
            }

        cmd_args = self.builder.build_exec_args(
            runtime_name=instance["runtime_name"],
            argv=argv,
            cwd=cwd,
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
            return {
                "ok": proc.returncode == 0,
                "exit_code": proc.returncode,
                "stdout": stdout.decode(errors="replace")[:16384],
                "stderr": stderr.decode(errors="replace")[:16384],
            }
        except TimeoutError:
            if proc and proc.returncode is None:
                proc.kill()
            return {
                "ok": False,
                "error": f"Execution timed out after {timeout_seconds} seconds.",
                "data": {},
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"Failed to dispatch to sandbox: {str(e)}",
                "data": {},
            }
