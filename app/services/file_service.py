from __future__ import annotations

import asyncio
import os
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from uuid import UUID, uuid4

PERSISTENT_QUOTA_BYTES = 512 * 1024 * 1024
_KIND_DIRS = {
    "upload": "uploads",
    "attachment": "attachments",
    "generated_image": "generated",
    "generated_file": "generated",
    "sandbox_artifact": "artifacts",
    "export": "exports",
}


class FileNotFound(Exception):
    """ฅ^•ﻌ•^ฅ"""


class QuotaExceeded(Exception):
    """ฅ^•ﻌ•^ฅ"""


class FileRepository(Protocol):
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
    ) -> dict[str, Any] | None: ...

    async def mark_ready(self, file_id: str, owner_id: str) -> dict[str, Any]: ...

    async def release(self, file_id: str, owner_id: str) -> None: ...

    async def get(self, file_id: str, owner_id: str) -> dict[str, Any] | None: ...


class FileService:
    """ฅ^•ﻌ•^ฅ"""

    def __init__(self, storage_root: Path, repository: FileRepository) -> None:
        self.storage_root = storage_root.resolve()
        self.repository = repository

    async def persist_bytes(
        self,
        *,
        owner_id: str,
        data: bytes,
        kind: str,
        mime_type: str,
        original_name: str | None = None,
        source: str = "user",
    ) -> dict[str, Any]:
        UUID(owner_id)
        directory = _KIND_DIRS.get(kind)
        if directory is None:
            raise ValueError(f"Unsupported file kind: {kind}")

        file_id = str(uuid4())
        object_id = str(uuid4())
        storage_key = f"users/{owner_id}/{directory}/{object_id}"
        row = await self.repository.reserve(
            file_id=file_id,
            owner_id=owner_id,
            storage_key=storage_key,
            original_name=Path(original_name).name if original_name else None,
            mime_type=mime_type,
            size_bytes=len(data),
            kind=kind,
            source=source,
        )
        if row is None:
            raise QuotaExceeded

        path = self._resolve_storage_key(storage_key)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(temporary.write_bytes, data)
            await asyncio.to_thread(os.replace, temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            await self.repository.release(file_id, owner_id)
            raise
        try:
            return await self.repository.mark_ready(file_id, owner_id)
        except BaseException:
            # Leave pending metadata + bytes for deterministic reconciliation.
            raise

    async def open_for_owner(
        self, file_id: str, owner_id: str
    ) -> tuple[dict[str, Any], Path]:
        row = await self.repository.get(file_id, owner_id)
        if row is None:
            raise FileNotFound
        try:
            path = self._resolve_storage_key(str(row["storage_key"]))
        except ValueError as error:
            raise FileNotFound from error
        if path.is_symlink() or not path.is_file():
            raise FileNotFound
        return row, path

    async def import_artifact(
        self,
        *,
        owner_id: str,
        workspace_root: Path,
        relative_path: str,
        mime_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        source = self._regular_workspace_file(workspace_root, relative_path)
        data = await asyncio.to_thread(source.read_bytes)
        return await self.persist_bytes(
            owner_id=owner_id,
            data=data,
            kind="sandbox_artifact",
            mime_type=mime_type,
            original_name=source.name,
            source="sandbox",
        )

    @staticmethod
    def _regular_workspace_file(workspace_root: Path, relative_path: str) -> Path:
        root = workspace_root.resolve()
        key = PurePosixPath(relative_path)
        if key.is_absolute() or ".." in key.parts or "\\" in relative_path:
            raise ValueError("Artifact escapes workspace")
        path = root.joinpath(*key.parts)
        if path.is_symlink() or not path.is_file():
            raise ValueError("Artifact must be a regular file")
        try:
            path.resolve().relative_to(root)
        except ValueError as error:
            raise ValueError("Artifact escapes workspace") from error
        return path

    def _resolve_storage_key(self, storage_key: str) -> Path:
        key = PurePosixPath(storage_key)
        if key.is_absolute() or ".." in key.parts or "\\" in storage_key:
            raise ValueError("Invalid storage key")
        path = self.storage_root.joinpath(*key.parts)
        try:
            path.parent.resolve().relative_to(self.storage_root)
        except ValueError as error:
            raise ValueError("Storage key escapes root") from error
        return path
