from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from app.core.ids import EntityType, PublicId
from yuzu_sandbox.runner import JobRequest, JobResult, SandboxRunner

_TERMINAL = {"succeeded", "failed", "cancelled", "timed_out"}


class JobRepository(Protocol):
    async def create(
        self, *, owner_id: str, request: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def get(self, job_id: str) -> dict[str, Any] | None: ...

    async def transition(
        self,
        job_id: str,
        from_statuses: set[str],
        status: str,
        error_code: str | None = None,
    ) -> dict[str, Any] | None: ...

    async def terminal_before(self, cutoff: datetime) -> list[dict[str, Any]]: ...


class SandboxManager:
    """Single-node job orchestration. No scheduling or node registry."""

    def __init__(self, jobs: JobRepository, runner: SandboxRunner, files: Any) -> None:
        self.jobs = jobs
        self.runner = runner
        self.files = files

    async def execute(
        self,
        *,
        authenticated_owner_id: str,
        argv: list[str],
        claimed_owner_id: str | None = None,
        cwd: str = ".",
        timeout_ms: int = 30_000,
        workspace_bytes: int = 256 * 1024 * 1024,
        output_bytes: int = 16 * 1024 * 1024,
        artifact_bytes: int = 64 * 1024 * 1024,
        max_artifacts: int = 16,
        artifacts: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        del claimed_owner_id
        UUID(authenticated_owner_id)
        contract = {
            "argv": argv,
            "cwd": cwd,
            "timeout_ms": timeout_ms,
            "workspace_bytes_limit": workspace_bytes,
            "output_bytes_limit": output_bytes,
        }
        created = await self.jobs.create(
            owner_id=authenticated_owner_id, request=contract
        )
        job_id = str(created["id"])
        authoritative = await self._require_job(job_id)
        owner_id = str(authoritative["owner_id"])
        request = JobRequest(
            job_id=job_id,
            owner_id=owner_id,
            argv=argv,
            cwd=cwd,
            timeout_ms=timeout_ms,
            workspace_bytes=workspace_bytes,
            output_bytes=output_bytes,
            artifact_bytes=artifact_bytes,
            max_artifacts=max_artifacts,
            artifacts=artifacts or [],
            env=env or {},
        )
        await self.jobs.transition(job_id, {"pending"}, "running")
        result: JobResult | None = None
        try:
            result = await self.runner.run(request)
            status = self._result_status(result)
            await self.jobs.transition(job_id, {"running"}, status, result.error_code)
            imported = []
            if status == "succeeded":
                for artifact in result.artifacts:
                    current = await self._require_job(job_id)
                    row = await self.files.import_artifact(
                        owner_id=str(current["owner_id"]),
                        workspace_root=self.runner.job_root(owner_id, job_id),
                        relative_path=str(artifact["path"]),
                        job_id=job_id,
                        mime_type="application/octet-stream",
                    )
                    imported.append(self._public_file(row))
            return {"job_id": job_id, "status": status, "artifacts": imported}
        except BaseException:
            await self.jobs.transition(
                job_id, {"pending", "running"}, "failed", "dispatch_error"
            )
            raise
        finally:
            await self.runner.cleanup(owner_id, job_id)

    async def get_for_owner(self, job_id: str, owner_id: str) -> dict[str, Any]:
        row = await self._require_job(job_id)
        if str(row["owner_id"]) != owner_id:
            raise LookupError("Job not found")
        return row

    async def cancel(self, job_id: str, owner_id: str) -> dict[str, Any]:
        await self.get_for_owner(job_id, owner_id)
        row = await self.jobs.transition(job_id, {"pending", "running"}, "cancelled")
        if row is None:
            raise LookupError("Job is not cancellable")
        return row

    async def reap(self, retention_seconds: int) -> int:
        rows = await self.jobs.terminal_before(
            datetime.now(UTC) - timedelta(seconds=retention_seconds)
        )
        for row in rows:
            await self.runner.cleanup(str(row["owner_id"]), str(row["id"]))
        return len(rows)

    async def _require_job(self, job_id: str) -> dict[str, Any]:
        row = await self.jobs.get(job_id)
        if row is None:
            raise LookupError("Job not found")
        return row

    @staticmethod
    def _result_status(result: JobResult) -> str:
        if result.timed_out or result.error_code == "timeout":
            return "timed_out"
        if result.error_code or result.exit_code != 0:
            return "failed"
        return "succeeded"

    @staticmethod
    def _public_file(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "file_id": PublicId.encode(EntityType.FILE, row["id"]),
            "mime_type": row["mime_type"],
            "size_bytes": row["size_bytes"],
            "name": row.get("original_name"),
        }
