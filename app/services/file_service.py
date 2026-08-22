from __future__ import annotations

import asyncio
import os
import shutil
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
    pass


class QuotaExceeded(Exception):
    pass


class StorageUnavailable(Exception):
    pass


class LowDiskSpace(StorageUnavailable):
    pass


class FileTooLarge(StorageUnavailable):
    pass


class FileRepository(Protocol):
    async def reserve(self, **values: Any) -> dict[str, Any] | None: ...
    async def mark_ready(self, file_id: str, owner_id: str) -> dict[str, Any]: ...
    async def release(self, file_id: str, owner_id: str) -> None: ...
    async def get(self, file_id: str, owner_id: str) -> dict[str, Any] | None: ...
    async def mark_deleted(
        self, file_id: str, owner_id: str
    ) -> dict[str, Any] | None: ...


class FileService:
    def __init__(
        self,
        storage_root: Path,
        repository: FileRepository,
        *,
        reserve_bytes: int = 0,
        max_file_bytes: int = PERSISTENT_QUOTA_BYTES,
    ) -> None:
        self.storage_root = storage_root.resolve()
        self.repository = repository
        self.reserve_bytes = reserve_bytes
        self.max_file_bytes = max_file_bytes

    async def persist_bytes(
        self,
        *,
        owner_id: str,
        data: bytes,
        kind: str,
        mime_type: str,
        original_name: str | None = None,
        source: str = "user",
        job_id: str | None = None,
    ) -> dict[str, Any]:
        UUID(owner_id)
        if len(data) > self.max_file_bytes:
            raise FileTooLarge
        self._require_free_space(len(data))
        directory = _KIND_DIRS.get(kind)
        if directory is None:
            raise ValueError(f"Unsupported file kind: {kind}")
        file_id = str(uuid4())
        storage_key = f"users/{owner_id}/{directory}/{uuid4()}"
        row = await self.repository.reserve(
            file_id=file_id,
            owner_id=owner_id,
            storage_key=storage_key,
            original_name=Path(original_name).name if original_name else None,
            mime_type=mime_type,
            size_bytes=len(data),
            kind=kind,
            source=source,
            job_id=job_id,
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
        return await self.repository.mark_ready(file_id, owner_id)

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
        job_id: str | None = None,
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
            job_id=job_id,
        )

    async def delete_for_owner(self, file_id: str, owner_id: str) -> None:
        row = await self.repository.mark_deleted(file_id, owner_id)
        if row is None:
            raise FileNotFound
        await asyncio.to_thread(
            self._resolve_storage_key(str(row["storage_key"])).unlink,
            missing_ok=True,
        )

    def _require_free_space(self, requested: int) -> None:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(self.storage_root).free - requested < self.reserve_bytes:
            raise LowDiskSpace

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
