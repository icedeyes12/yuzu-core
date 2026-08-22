from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from yuzu_sandbox.runner import JobRequest, SandboxRunner, UnsafeJob


@pytest.fixture
def runner(tmp_path):
    return SandboxRunner(
        tmp_path,
        allowed_executables={Path(sys.executable).name},
        inherited_env={"PATH": os.environ["PATH"], "DATABASE_URL": "secret"},
    )


@pytest.mark.asyncio
async def test_job_receives_allowlisted_environment_only(runner):
    result = await runner.run(
        JobRequest(
            job_id=str(uuid4()),
            owner_id=str(uuid4()),
            argv=[
                Path(sys.executable).name,
                "-c",
                "import os; print(sorted(os.environ))",
            ],
            env={"JOB_VALUE": "ok", "DATABASE_URL": "evil"},
        )
    )

    assert result.exit_code == 0
    assert "JOB_VALUE" in result.stdout
    assert "DATABASE_URL" not in result.stdout


@pytest.mark.asyncio
async def test_job_cwd_cannot_escape_workspace(runner):
    with pytest.raises(UnsafeJob, match="cwd"):
        await runner.run(
            JobRequest(
                job_id=str(uuid4()),
                owner_id=str(uuid4()),
                argv=[Path(sys.executable).name, "-c", "print('x')"],
                cwd="../outside",
            )
        )


@pytest.mark.asyncio
async def test_job_rejects_unallowlisted_executable(runner):
    with pytest.raises(UnsafeJob, match="executable"):
        await runner.run(
            JobRequest(
                job_id=str(uuid4()),
                owner_id=str(uuid4()),
                argv=["sh", "-c", "id"],
            )
        )


@pytest.mark.asyncio
async def test_timeout_terminates_job(runner):
    result = await runner.run(
        JobRequest(
            job_id=str(uuid4()),
            owner_id=str(uuid4()),
            argv=[Path(sys.executable).name, "-c", "import time; time.sleep(5)"],
            timeout_ms=50,
        )
    )

    assert result.timed_out is True
    assert result.exit_code is not None


@pytest.mark.asyncio
async def test_cancellation_terminates_job(runner):
    task = asyncio.create_task(
        runner.run(
            JobRequest(
                job_id=str(uuid4()),
                owner_id=str(uuid4()),
                argv=[Path(sys.executable).name, "-c", "import time; time.sleep(5)"],
            )
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_artifact_manifest_contains_regular_files_only(runner):
    result = await runner.run(
        JobRequest(
            job_id=str(uuid4()),
            owner_id=str(uuid4()),
            argv=[
                Path(sys.executable).name,
                "-c",
                "from pathlib import Path; Path('report.txt').write_text('ok'); Path('link').symlink_to('report.txt')",
            ],
            artifacts=["report.txt", "link", "../escape"],
        )
    )

    assert result.artifacts == [{"path": "report.txt", "size_bytes": 2}]


@pytest.mark.asyncio
async def test_job_identity_and_absolute_executable_are_rejected(runner):
    with pytest.raises((ValueError, UnsafeJob)):
        await runner.run(
            JobRequest(
                job_id="../escape",
                owner_id=str(uuid4()),
                argv=[Path(sys.executable).name, "-c", "print('x')"],
            )
        )

    with pytest.raises(UnsafeJob, match="executable"):
        await runner.run(
            JobRequest(
                job_id=str(uuid4()),
                owner_id=str(uuid4()),
                argv=[sys.executable, "-c", "print('x')"],
            )
        )
