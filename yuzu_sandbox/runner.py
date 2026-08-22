from __future__ import annotations

import asyncio
import os
import signal
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

_DEFAULT_TIMEOUT_MS = 30_000
_MAX_TIMEOUT_MS = 120_000
_DEFAULT_OUTPUT_BYTES = 16 * 1024 * 1024
_SAFE_ENV_KEYS = {"JOB_VALUE", "LANG", "LC_ALL"}


class UnsafeJob(ValueError):
    """ฅ^•ﻌ•^ฅ"""


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    owner_id: str
    argv: list[str] = Field(min_length=1, max_length=64)
    cwd: str = "."
    timeout_ms: int = Field(default=_DEFAULT_TIMEOUT_MS, ge=1, le=_MAX_TIMEOUT_MS)
    stdin: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list, max_length=64)
    output_bytes: int = Field(
        default=_DEFAULT_OUTPUT_BYTES, ge=1, le=_DEFAULT_OUTPUT_BYTES
    )


class JobResult(BaseModel):
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class SandboxRunner:
    """Controlled process runner; not a hostile-code security boundary. ฅ^•ﻌ•^ฅ"""

    def __init__(
        self,
        workspace_root: Path,
        *,
        allowed_executables: set[str],
        inherited_env: dict[str, str] | None = None,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.allowed_executables = allowed_executables
        self.inherited_env = inherited_env or {}

    async def run(self, job: JobRequest) -> JobResult:
        UUID(job.job_id)
        UUID(job.owner_id)
        executable = job.argv[0]
        if (
            Path(executable).name != executable
            or executable not in self.allowed_executables
        ):
            raise UnsafeJob("executable is not allowed")

        job_root = (self.workspace_root / job.owner_id / job.job_id).resolve()
        try:
            job_root.relative_to(self.workspace_root)
        except ValueError as error:
            raise UnsafeJob("job identity escapes workspace") from error
        cwd = self._job_path(job_root, job.cwd, "cwd")
        cwd.mkdir(parents=True, exist_ok=True)
        environment = {"PATH": self.inherited_env.get("PATH", os.defpath)}
        environment.update(
            {key: value for key, value in job.env.items() if key in _SAFE_ENV_KEYS}
        )

        with (
            tempfile.TemporaryFile() as stdout_file,
            tempfile.TemporaryFile() as stderr_file,
        ):
            process = await asyncio.create_subprocess_exec(
                *job.argv,
                cwd=cwd,
                env=environment,
                stdin=asyncio.subprocess.PIPE if job.stdin is not None else None,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=True,
            )
            timed_out = False
            try:
                await asyncio.wait_for(
                    process.communicate(
                        job.stdin.encode() if job.stdin is not None else None
                    ),
                    timeout=job.timeout_ms / 1000,
                )
            except TimeoutError:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                await process.communicate()
            except asyncio.CancelledError:
                os.killpg(process.pid, signal.SIGKILL)
                await process.communicate()
                raise
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout = stdout_file.read(job.output_bytes)
            stderr = stderr_file.read(job.output_bytes)

        return JobResult(
            exit_code=process.returncode,
            stdout=stdout[: job.output_bytes].decode(errors="replace"),
            stderr=stderr[: job.output_bytes].decode(errors="replace"),
            timed_out=timed_out,
            artifacts=self._collect_artifacts(job_root, job.artifacts),
        )

    def _job_path(self, root: Path, value: str, label: str) -> Path:
        relative = PurePosixPath(value)
        if relative.is_absolute() or ".." in relative.parts or "\\" in value:
            raise UnsafeJob(f"{label} escapes workspace")
        path = root.joinpath(*relative.parts)
        candidate = path if relative == PurePosixPath(".") else path.parent
        try:
            candidate.resolve().relative_to(root)
        except ValueError as error:
            raise UnsafeJob(f"{label} escapes workspace") from error
        return path

    def _collect_artifacts(
        self, job_root: Path, requested: list[str]
    ) -> list[dict[str, Any]]:
        artifacts = []
        for name in requested:
            try:
                path = self._job_path(job_root, name, "artifact")
            except UnsafeJob:
                continue
            if path.is_symlink() or not path.is_file():
                continue
            artifacts.append({"path": name, "size_bytes": path.stat().st_size})
        return artifacts
