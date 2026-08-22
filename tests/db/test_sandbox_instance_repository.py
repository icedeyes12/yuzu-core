from __future__ import annotations

from uuid import uuid4

import pytest

from app.db.sandbox_instance_repository import (
    SQL_SANDBOX_INSTANCE_DELETE,
    SQL_SANDBOX_INSTANCE_INCREMENT_GENERATION,
    SQL_SANDBOX_INSTANCE_INSERT,
    SQL_SANDBOX_INSTANCE_SELECT_BY_OWNER,
    SQL_SANDBOX_INSTANCE_UPDATE_STATE,
    PgSandboxInstanceRepository,
)


class FakeSession:
    def __init__(self, row: dict | None = None) -> None:
        self.row = row
        self.executed: list[tuple[str, tuple]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def fetchone(self, query, params=None):
        self.executed.append((query, params))
        return self.row

    async def execute_returning(self, query, params=None):
        self.executed.append((query, params))
        if self.row:
            return self.row
        return {"owner_id": params[1] if len(params) > 1 else params[0], "status": "ok"}


@pytest.mark.asyncio
async def test_sandbox_instance_repository_crud():
    owner_id = str(uuid4())
    session = FakeSession({"owner_id": owner_id, "state": "ready", "generation": 1})
    repo = PgSandboxInstanceRepository(session_factory=lambda: session)

    # 1. Get by owner
    res = await repo.get_by_owner(owner_id)
    assert res["owner_id"] == owner_id
    assert SQL_SANDBOX_INSTANCE_SELECT_BY_OWNER in session.executed[0][0]

    # 2. Create — PostgreSQL generates canonical UUIDv7.
    await repo.create(owner_id=owner_id, distribution="debian")
    assert SQL_SANDBOX_INSTANCE_INSERT in session.executed[1][0]
    insert_params = session.executed[1][1]
    assert len(insert_params) == 4
    assert insert_params[0] == owner_id
    assert "generate_uuidv7()" in SQL_SANDBOX_INSTANCE_INSERT
    assert owner_id.replace("-", "")[:16] not in str(insert_params)

    # 3. Update state
    await repo.update_state(owner_id=owner_id, state="ready")
    assert SQL_SANDBOX_INSTANCE_UPDATE_STATE in session.executed[2][0]

    # 4. Bump generation
    await repo.bump_generation(owner_id=owner_id, next_state="rebuilding")
    assert SQL_SANDBOX_INSTANCE_INCREMENT_GENERATION in session.executed[3][0]

    # 5. Delete
    await repo.delete(owner_id=owner_id)
    assert SQL_SANDBOX_INSTANCE_DELETE in session.executed[4][0]
