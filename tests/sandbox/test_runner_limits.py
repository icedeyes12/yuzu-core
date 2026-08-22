from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from yuzu_sandbox.runner import JobRequest, SandboxRunner


@pytest.fixture
def runner(tmp_path):
    return SandboxRunner(
        tmp_path,
        allowed_executables={Path(sys.executable).name},
        inherited_env={"PATH": os.environ["PATH"]},
        disk_reserve_bytes=0,
    )


def request(**overrides):
    values = {
        "job_id": str(uuid4()),
        "owner_id": str(uuid4()),
        "argv": [Path(sys.executable).name, "-c", "print('ok')"],
        "output_bytes": 1024,
        "workspace_bytes": 1024,
        "artifact_bytes": 512,
        "max_artifacts": 2,
    }
    values.update(overrides)
    return JobRequest(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", ["stdout", "stderr"])
async def test_output_limit_terminates_process(runner, stream):
    target = "sys.stdout" if stream == "stdout" else "sys.stderr"
    result = await runner.run(
        request(
            argv=[
                Path(sys.executable).name,
                "-c",
                f"import sys,time; {target}.write('x'*5000); {target}.flush(); time.sleep(5)",
            ],
            output_bytes=128,
        )
    )

    assert result.error_code == "output_limit"
    assert result.exit_code is not None


@pytest.mark.asyncio
async def test_workspace_limit_terminates_job(runner):
    result = await runner.run(
        request(
            argv=[
                Path(sys.executable).name,
                "-c",
                "from pathlib import Path; Path('big').write_bytes(b'x'*4096); import time; time.sleep(5)",
            ],
            workspace_bytes=256,
        )
    )

    assert result.error_code == "workspace_limit"


@pytest.mark.asyncio
async def test_artifact_count_and_size_are_enforced(runner):
    count = await runner.run(
        request(
            argv=[
                Path(sys.executable).name,
                "-c",
                "from pathlib import Path; [Path(f'f{i}').write_text('x') for i in range(3)]",
            ],
            artifacts=["f0", "f1", "f2"],
            max_artifacts=2,
        )
    )
    size = await runner.run(
        request(
            argv=[
                Path(sys.executable).name,
                "-c",
                "from pathlib import Path; Path('big').write_bytes(b'x'*600)",
            ],
            artifacts=["big"],
            artifact_bytes=512,
            workspace_bytes=1024,
        )
    )

    assert count.error_code == "artifact_count_limit"
    assert size.error_code == "artifact_size_limit"


@pytest.mark.asyncio
async def test_cleanup_is_idempotent(runner):
    job = request()
    result = await runner.run(job)
    assert result.exit_code == 0
    assert runner.job_root(job.owner_id, job.job_id).exists()

    await runner.cleanup(job.owner_id, job.job_id)
    await runner.cleanup(job.owner_id, job.job_id)

    assert not runner.job_root(job.owner_id, job.job_id).exists()
