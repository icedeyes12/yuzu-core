"""
Database Schema & Queries for Sandbox Instances (Persistent Personal Computer).
Single Source of Truth for Sandbox Instance Tenancy.
ฅ^•ﻌ•^ฅ
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from app.db.connection import AsyncPgSession

SQL_SANDBOX_INSTANCES_DDL = """
CREATE TABLE IF NOT EXISTS sandbox_instances (
    id UUID PRIMARY KEY,
    owner_id UUID NOT NULL UNIQUE REFERENCES profiles(id) ON DELETE CASCADE,
    runtime_name TEXT NOT NULL UNIQUE,
    distribution TEXT NOT NULL CHECK (distribution IN ('debian', 'ubuntu')),
    distribution_version TEXT NOT NULL,
    generation INTEGER NOT NULL DEFAULT 1,
    state TEXT NOT NULL CHECK (state IN (
        'none', 'provisioning', 'ready', 'busy', 'resetting', 'rebuilding', 'deleting', 'failed'
    )),
    storage_limit_bytes BIGINT NOT NULL DEFAULT 10737418240,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_started_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_sandbox_instances_owner ON sandbox_instances(owner_id, state);
"""

SQL_SANDBOX_INSTANCE_INSERT = """
INSERT INTO sandbox_instances
    (id, owner_id, runtime_name, distribution, distribution_version, generation, state, storage_limit_bytes)
VALUES (%s, %s, %s, %s, %s, 1, 'provisioning', %s)
RETURNING *
"""

SQL_SANDBOX_INSTANCE_SELECT_BY_OWNER = """
SELECT * FROM sandbox_instances WHERE owner_id = %s
"""

SQL_SANDBOX_INSTANCE_UPDATE_STATE = """
UPDATE sandbox_instances
SET state = %s,
    last_error = %s,
    updated_at = NOW(),
    last_started_at = CASE WHEN %s = 'ready' THEN NOW() ELSE last_started_at END
WHERE owner_id = %s
RETURNING *
"""

SQL_SANDBOX_INSTANCE_INCREMENT_GENERATION = """
UPDATE sandbox_instances
SET generation = generation + 1,
    state = %s,
    distribution = COALESCE(%s, distribution),
    distribution_version = COALESCE(%s, distribution_version),
    last_error = NULL,
    updated_at = NOW()
WHERE owner_id = %s
RETURNING *
"""

SQL_SANDBOX_INSTANCE_DELETE = """
DELETE FROM sandbox_instances WHERE owner_id = %s RETURNING *
"""


class PgSandboxInstanceRepository:
    """PostgreSQL Repository for User Sandbox Instances."""

    def __init__(self, session_factory: Callable[[], Any] = AsyncPgSession) -> None:
        self.session_factory = session_factory

    async def get_by_owner(self, owner_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            return await session.fetchone(
                SQL_SANDBOX_INSTANCE_SELECT_BY_OWNER, (owner_id,)
            )

    async def create(
        self,
        *,
        owner_id: str,
        distribution: str = "debian",
        distribution_version: str = "12",
        storage_limit_bytes: int = 10 * 1024 * 1024 * 1024,
    ) -> dict[str, Any]:
        instance_id = str(uuid4())
        # Generate safe, opaque runtime directory name
        runtime_name = (
            f"sbx_{owner_id.replace('-', '')[:16]}_{instance_id.replace('-', '')[:8]}"
        )
        async with self.session_factory() as session:
            return await session.execute_returning(
                SQL_SANDBOX_INSTANCE_INSERT,
                (
                    instance_id,
                    owner_id,
                    runtime_name,
                    distribution,
                    distribution_version,
                    storage_limit_bytes,
                ),
            )

    async def update_state(
        self, owner_id: str, state: str, error: str | None = None
    ) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            return await session.execute_returning(
                SQL_SANDBOX_INSTANCE_UPDATE_STATE,
                (state, error, state, owner_id),
            )

    async def bump_generation(
        self,
        owner_id: str,
        next_state: str = "provisioning",
        distribution: str | None = None,
        distribution_version: str | None = None,
    ) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            return await session.execute_returning(
                SQL_SANDBOX_INSTANCE_INCREMENT_GENERATION,
                (next_state, distribution, distribution_version, owner_id),
            )

    async def delete(self, owner_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            return await session.execute_returning(
                SQL_SANDBOX_INSTANCE_DELETE, (owner_id,)
            )
