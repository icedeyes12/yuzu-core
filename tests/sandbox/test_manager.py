from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.services.sandbox_manager import SandboxManager
from yuzu_sandbox.runner import JobRequest, JobResult


class FakeJobs:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    async def create(self, *, job_id, owner_id, request):
        row = {"id": job_id, "owner_id": owner_id, "status": "pending", **request}
        self.rows[job_id] = row
        return row.copy()

    async def get(self, job_id):
        row = self.rows.get(job_id)
        return row.copy() if row else None

    async def transition(self, job_id, from_statuses, status, error_code=None):
        row = self.rows.get(job_id)
        if not row or row["status"] not in from_statuses:
            return None
        row["status"] = status
        row["error_code"] = error_code
        return row.copy()

    async def terminal_before(self, _cutoff):
        return []


class FakeRunner:
    def __init__(self, root: Path, result: JobResult) -> None:
        self.workspace_root = root
        self.result = result
        self.seen: JobRequest | None = None
        self.cleaned: list[tuple[str, str]] = []

    async def run(self, request):
        self.seen = request
        workspace = self.workspace_root / request.owner_id / request.job_id
        workspace.mkdir(parents=True)
        (workspace / "report.txt").write_text("ok")
        return self.result

    def job_root(self, owner_id, job_id):
        return self.workspace_root / owner_id / job_id

    async def cleanup(self, owner_id, job_id):
        self.cleaned.append((owner_id, job_id))


class FakeFiles:
    def __init__(self) -> None:
        self.imports = []

    async def import_artifact(self, **kwargs):
        self.imports.append(kwargs)
        return {
            "id": str(uuid4()),
            "mime_type": kwargs["mime_type"],
            "size_bytes": 2,
            "original_name": Path(kwargs["relative_path"]).name,
        }


@pytest.mark.asyncio
async def test_authenticated_owner_is_authoritative_for_job_and_artifacts(tmp_path):
    jobs = FakeJobs()
    files = FakeFiles()
    runner = FakeRunner(
        tmp_path,
        JobResult(
            exit_code=0,
            stdout="",
            stderr="",
            artifacts=[{"path": "report.txt", "size_bytes": 2}],
        ),
    )
    manager = SandboxManager(jobs, runner, files)
    owner = str(uuid4())
    attacker_owner = str(uuid4())

    result = await manager.execute(
        authenticated_owner_id=owner,
        argv=["python3", "main.py"],
        claimed_owner_id=attacker_owner,
        artifacts=["report.txt"],
    )

    job = jobs.rows[result["job_id"]]
    assert job["owner_id"] == owner
    assert runner.seen is not None and runner.seen.owner_id == owner
    assert files.imports[0]["owner_id"] == owner
    assert files.imports[0]["job_id"] == result["job_id"]
    assert "path" not in result["artifacts"][0]
    assert runner.cleaned == [(owner, result["job_id"])]


@pytest.mark.asyncio
async def test_failed_job_is_finalized_and_cleaned(tmp_path):
    jobs = FakeJobs()
    runner = FakeRunner(
        tmp_path,
        JobResult(exit_code=2, stdout="", stderr="bad", error_code="process_failed"),
    )
    manager = SandboxManager(jobs, runner, FakeFiles())

    result = await manager.execute(
        authenticated_owner_id=str(uuid4()), argv=["python3", "main.py"]
    )

    assert result["status"] == "failed"
    assert jobs.rows[result["job_id"]]["error_code"] == "process_failed"
    assert runner.cleaned


@pytest.mark.asyncio
async def test_wrong_owner_cannot_resolve_job(tmp_path):
    jobs = FakeJobs()
    owner = str(uuid4())
    job_id = str(uuid4())
    jobs.rows[job_id] = {"id": job_id, "owner_id": owner, "status": "succeeded"}
    manager = SandboxManager(
        jobs,
        FakeRunner(tmp_path, JobResult(exit_code=0, stdout="", stderr="")),
        FakeFiles(),
    )

    with pytest.raises(LookupError):
        await manager.get_for_owner(job_id, str(uuid4()))
