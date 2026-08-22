from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.db.connection import AsyncPgSession
from app.db.queries import (
    SQL_SANDBOX_JOB_INSERT,
    SQL_SANDBOX_JOB_SELECT,
    SQL_SANDBOX_JOB_TRANSITION,
    SQL_SANDBOX_JOBS_TERMINAL_BEFORE,
)


class PgSandboxJobRepository:
    def __init__(self, session_factory: Callable[[], Any] = AsyncPgSession) -> None:
        self.session_factory = session_factory

    async def create(self, *, job_id: str, owner_id: str, request: dict[str, Any]):
        async with self.session_factory() as session:
            return await session.execute_returning(
                SQL_SANDBOX_JOB_INSERT,
                (
                    job_id,
                    owner_id,
                    json.dumps(request["argv"]),
                    request["cwd"],
                    request["timeout_ms"],
                    request["workspace_bytes_limit"],
                    request["output_bytes_limit"],
                ),
            )

    async def get(self, job_id: str):
        async with self.session_factory() as session:
            return await session.fetchone(SQL_SANDBOX_JOB_SELECT, (job_id,))

    async def transition(self, job_id, from_statuses, status, error_code=None):
        async with self.session_factory() as session:
            return await session.execute_returning(
                SQL_SANDBOX_JOB_TRANSITION,
                (status, error_code, status, status, job_id, list(from_statuses)),
            )

    async def terminal_before(self, cutoff: datetime):
        async with self.session_factory() as session:
            return await session.fetchall(SQL_SANDBOX_JOBS_TERMINAL_BEFORE, (cutoff,))
