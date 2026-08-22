from __future__ import annotations

import asyncio
import os
import shutil
import signal
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

_DEFAULT_TIMEOUT_MS = 30_000
_MAX_TIMEOUT_MS = 120_000
_DEFAULT_OUTPUT_BYTES = 16 * 1024 * 1024
_DEFAULT_WORKSPACE_BYTES = 256 * 1024 * 1024
_DEFAULT_ARTIFACT_BYTES = 64 * 1024 * 1024
_DEFAULT_MAX_ARTIFACTS = 16
_SAFE_ENV_KEYS = {"JOB_VALUE", "LANG", "LC_ALL"}


class UnsafeJob(ValueError):
    """Controlled runner rejected a job."""


class LowDiskSpace(RuntimeError):
    """Sandbox filesystem reserve would be crossed."""


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    # Derived by Core from sandbox_jobs. Never an authorization authority.
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
    workspace_bytes: int = Field(default=_DEFAULT_WORKSPACE_BYTES, ge=1)
    artifact_bytes: int = Field(default=_DEFAULT_ARTIFACT_BYTES, ge=1)
    max_artifacts: int = Field(default=_DEFAULT_MAX_ARTIFACTS, ge=0, le=64)


class JobResult(BaseModel):
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    error_code: str | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class SandboxRunner:
    """Controlled process runner; not a hostile-code security boundary."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        allowed_executables: set[str],
        inherited_env: dict[str, str] | None = None,
        disk_reserve_bytes: int = 0,
        poll_seconds: float = 0.02,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.allowed_executables = allowed_executables
        self.inherited_env = inherited_env or {}
        self.disk_reserve_bytes = disk_reserve_bytes
        self.poll_seconds = poll_seconds

    def job_root(self, owner_id: str, job_id: str) -> Path:
        UUID(job_id)
        UUID(owner_id)
        root = (self.workspace_root / owner_id / job_id).resolve()
        try:
            root.relative_to(self.workspace_root)
        except ValueError as error:
            raise UnsafeJob("job identity escapes workspace") from error
        return root

    async def run(self, job: JobRequest) -> JobResult:
        executable = job.argv[0]
        if (
            Path(executable).name != executable
            or executable not in self.allowed_executables
        ):
            raise UnsafeJob("executable is not allowed")
        self._require_free_space(job.workspace_bytes)

        job_root = self.job_root(job.owner_id, job.job_id)
        cwd = self._job_path(job_root, job.cwd, "cwd")
        cwd.mkdir(parents=True, exist_ok=True)
        environment = {"PATH": self.inherited_env.get("PATH", os.defpath)}
        environment.update(
            {key: value for key, value in job.env.items() if key in _SAFE_ENV_KEYS}
        )

        process = await asyncio.create_subprocess_exec(
            *job.argv,
            cwd=cwd,
            env=environment,
            stdin=asyncio.subprocess.PIPE if job.stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        if job.stdin is not None and process.stdin is not None:
            process.stdin.write(job.stdin.encode())
            await process.stdin.drain()
            process.stdin.close()

        stdout = bytearray()
        stderr = bytearray()
        error_code: str | None = None
        timed_out = False
        started = asyncio.get_running_loop().time()

        async def read_stream(
            stream: asyncio.StreamReader | None, target: bytearray
        ) -> None:
            nonlocal error_code
            if stream is None:
                return
            while chunk := await stream.read(8192):
                if len(target) + len(chunk) > job.output_bytes:
                    target.extend(chunk[: max(0, job.output_bytes - len(target))])
                    error_code = "output_limit"
                    self._kill(process)
                    return
                target.extend(chunk)

        readers = [
            asyncio.create_task(read_stream(process.stdout, stdout)),
            asyncio.create_task(read_stream(process.stderr, stderr)),
        ]
        try:
            while process.returncode is None:
                if asyncio.get_running_loop().time() - started > job.timeout_ms / 1000:
                    timed_out = True
                    error_code = "timeout"
                    self._kill(process)
                    break
                if (
                    await asyncio.to_thread(self._directory_bytes, job_root)
                    > job.workspace_bytes
                ):
                    error_code = "workspace_limit"
                    self._kill(process)
                    break
                await asyncio.sleep(self.poll_seconds)
            await process.wait()
            await asyncio.gather(*readers)
        except asyncio.CancelledError:
            self._kill(process)
            await process.wait()
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
            raise

        artifacts: list[dict[str, Any]] = []
        if error_code is None:
            artifacts, error_code = self._collect_artifacts(job_root, job)
        return JobResult(
            exit_code=process.returncode,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
            timed_out=timed_out,
            error_code=error_code,
            artifacts=artifacts,
        )

    async def cleanup(self, owner_id: str, job_id: str) -> None:
        root = self.job_root(owner_id, job_id)
        await asyncio.to_thread(shutil.rmtree, root, True)
        with suppress(OSError):
            root.parent.rmdir()

    def _require_free_space(self, requested: int) -> None:
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        if (
            shutil.disk_usage(self.workspace_root).free - requested
            < self.disk_reserve_bytes
        ):
            raise LowDiskSpace("Sandbox storage reserve would be crossed")

    @staticmethod
    def _kill(process: asyncio.subprocess.Process) -> None:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)

    @staticmethod
    def _directory_bytes(root: Path) -> int:
        total = 0
        if not root.exists():
            return 0
        for path in root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        return total

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
        self, job_root: Path, job: JobRequest
    ) -> tuple[list[dict[str, Any]], str | None]:
        if len(job.artifacts) > job.max_artifacts:
            return [], "artifact_count_limit"
        artifacts = []
        for name in job.artifacts:
            try:
                path = self._job_path(job_root, name, "artifact")
            except UnsafeJob:
                return [], "invalid_artifact"
            if path.is_symlink() or not path.is_file():
                return [], "invalid_artifact"
            size = path.stat().st_size
            if size > job.artifact_bytes:
                return [], "artifact_size_limit"
            artifacts.append({"path": name, "size_bytes": size})
        return artifacts, None
