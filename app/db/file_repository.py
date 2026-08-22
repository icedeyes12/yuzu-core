from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.db.connection import AsyncPgSession
from app.db.queries import (
    SQL_FILE_DELETE_PENDING,
    SQL_FILE_INSERT_PENDING,
    SQL_FILE_MARK_DELETED,
    SQL_FILE_MARK_READY,
    SQL_FILE_SELECT_OWNER,
    SQL_FILE_USAGE,
    SQL_PROFILE_LOCK,
)
from app.services.file_service import PERSISTENT_QUOTA_BYTES


class PgFileRepository:
    def __init__(self, session_factory: Callable[[], Any] = AsyncPgSession) -> None:
        self.session_factory = session_factory

    async def reserve(
        self,
        *,
        file_id: str,
        owner_id: str,
        storage_key: str,
        original_name: str | None,
        mime_type: str,
        size_bytes: int,
        kind: str,
        source: str,
        job_id: str | None = None,
    ) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            await session.execute(SQL_PROFILE_LOCK, (owner_id,))
            used = int(await session.execute_scalar(SQL_FILE_USAGE, (owner_id,)) or 0)
            if used + size_bytes > PERSISTENT_QUOTA_BYTES:
                return None
            return await session.execute_returning(
                SQL_FILE_INSERT_PENDING,
                (
                    file_id,
                    owner_id,
                    storage_key,
                    original_name,
                    mime_type,
                    size_bytes,
                    kind,
                    source,
                    job_id,
                ),
            )

    async def mark_ready(self, file_id: str, owner_id: str) -> dict[str, Any]:
        async with self.session_factory() as session:
            row = await session.execute_returning(
                SQL_FILE_MARK_READY, (file_id, owner_id)
            )
        if row is None:
            raise RuntimeError("File reservation disappeared")
        return dict(row)

    async def release(self, file_id: str, owner_id: str) -> None:
        async with self.session_factory() as session:
            await session.execute(SQL_FILE_DELETE_PENDING, (file_id, owner_id))

    async def get(self, file_id: str, owner_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            row = await session.fetchone(SQL_FILE_SELECT_OWNER, (file_id, owner_id))
        return dict(row) if row else None

    async def mark_deleted(self, file_id: str, owner_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            row = await session.execute_returning(
                SQL_FILE_MARK_DELETED, (file_id, owner_id)
            )
        return dict(row) if row else None
