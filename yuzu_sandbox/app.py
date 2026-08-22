from __future__ import annotations

import hmac
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException

from yuzu_sandbox.runner import JobRequest, JobResult, SandboxRunner

app = FastAPI(title="yuzu-sandbox", docs_url=None, redoc_url=None)


def _authorize(authorization: str = Header(default="")) -> None:
    token = os.environ.get("YUZU_SANDBOX_TOKEN", "")
    supplied = authorization.removeprefix("Bearer ")
    if not token or not hmac.compare_digest(supplied, token):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _runner() -> SandboxRunner:
    root = Path(os.environ.get("YUZU_SANDBOX_ROOT", "/tmp/yuzu-sandbox"))
    allowed = {
        item.strip()
        for item in os.environ.get("YUZU_SANDBOX_EXECUTABLES", "python3").split(",")
        if item.strip()
    }
    return SandboxRunner(root, allowed_executables=allowed)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "boundary": "controlled-process-only"}


@app.post("/jobs", dependencies=[Depends(_authorize)])
async def run_job(job: JobRequest) -> JobResult:
    return await _runner().run(job)
