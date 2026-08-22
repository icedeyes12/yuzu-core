from __future__ import annotations

from uuid import uuid4

import pytest

from app.db.file_repository import PgFileRepository
from app.services.file_service import PERSISTENT_QUOTA_BYTES


class FakeSession:
    def __init__(self, used_bytes: int) -> None:
        self.used_bytes = used_bytes
        self.executed: list[tuple[str, tuple]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, query, params=None):
        self.executed.append((query, params))

    async def execute_scalar(self, query, params=None):
        assert "status IN ('pending', 'ready')" in query
        return self.used_bytes

    async def execute_returning(self, query, params=None):
        self.executed.append((query, params))
        return {"id": params[0], "owner_id": params[1], "status": "pending"}


@pytest.mark.asyncio
async def test_reserve_locks_owner_before_counting_and_inserting():
    session = FakeSession(used_bytes=0)
    repo = PgFileRepository(session_factory=lambda: session)
    owner_id = str(uuid4())

    result = await repo.reserve(
        file_id=str(uuid4()),
        owner_id=owner_id,
        storage_key="users/x/uploads/y",
        original_name="a.txt",
        mime_type="text/plain",
        size_bytes=3,
        kind="upload",
        source="user",
    )

    assert result is not None
    assert "FOR UPDATE" in session.executed[0][0]
    assert "INSERT INTO file_objects" in session.executed[1][0]


@pytest.mark.asyncio
async def test_reserve_rejects_quota_crossing_without_insert():
    session = FakeSession(used_bytes=PERSISTENT_QUOTA_BYTES - 2)
    repo = PgFileRepository(session_factory=lambda: session)

    result = await repo.reserve(
        file_id=str(uuid4()),
        owner_id=str(uuid4()),
        storage_key="users/x/uploads/y",
        original_name=None,
        mime_type="text/plain",
        size_bytes=3,
        kind="upload",
        source="user",
    )

    assert result is None
    assert len(session.executed) == 1
