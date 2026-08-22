from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.services.file_service import FileNotFound, FileService, QuotaExceeded


class FakeFiles:
    def __init__(self, quota_bytes: int = 16) -> None:
        self.quota_bytes = quota_bytes
        self.rows: dict[str, dict] = {}

    async def reserve(self, *, file_id, owner_id, storage_key, size_bytes, **metadata):
        used = sum(
            row["size_bytes"]
            for row in self.rows.values()
            if row["owner_id"] == owner_id and row["status"] in {"pending", "ready"}
        )
        if used + size_bytes > self.quota_bytes:
            return None
        row = {
            "id": file_id,
            "owner_id": owner_id,
            "storage_key": storage_key,
            "size_bytes": size_bytes,
            "status": "pending",
            **metadata,
        }
        self.rows[file_id] = row
        return row

    async def mark_ready(self, file_id, owner_id):
        row = self.rows[file_id]
        assert row["owner_id"] == owner_id
        row["status"] = "ready"
        return row.copy()

    async def release(self, file_id, owner_id):
        if self.rows.get(file_id, {}).get("owner_id") == owner_id:
            self.rows.pop(file_id)

    async def get(self, file_id, owner_id):
        row = self.rows.get(file_id)
        if not row or row["owner_id"] != owner_id or row["status"] != "ready":
            return None
        return row.copy()


@pytest.mark.asyncio
async def test_persist_uses_owner_namespace_and_random_object_id(tmp_path):
    owner_id = str(uuid4())
    repo = FakeFiles()
    service = FileService(tmp_path, repo)

    result = await service.persist_bytes(
        owner_id=owner_id,
        data=b"hello",
        kind="upload",
        original_name="../../avatar.png",
        mime_type="image/png",
    )

    assert result["owner_id"] == owner_id
    assert result["storage_key"].startswith(f"users/{owner_id}/uploads/")
    assert "avatar.png" not in result["storage_key"]
    UUID(result["id"])
    assert (tmp_path / result["storage_key"]).read_bytes() == b"hello"


@pytest.mark.asyncio
async def test_owner_scoped_lookup_hides_other_users_file(tmp_path):
    owner_id = str(uuid4())
    other_id = str(uuid4())
    service = FileService(tmp_path, FakeFiles())
    stored = await service.persist_bytes(
        owner_id=owner_id, data=b"x", kind="attachment", mime_type="text/plain"
    )

    with pytest.raises(FileNotFound):
        await service.open_for_owner(stored["id"], other_id)


@pytest.mark.asyncio
async def test_quota_rejects_write_without_leaving_file_or_reservation(tmp_path):
    repo = FakeFiles(quota_bytes=4)
    service = FileService(tmp_path, repo)

    with pytest.raises(QuotaExceeded):
        await service.persist_bytes(
            owner_id=str(uuid4()), data=b"12345", kind="upload", mime_type="text/plain"
        )

    assert repo.rows == {}
    assert list(tmp_path.rglob("*")) == []


@pytest.mark.asyncio
async def test_open_rejects_tampered_storage_key(tmp_path):
    owner_id = str(uuid4())
    repo = FakeFiles()
    service = FileService(tmp_path, repo)
    file_id = str(uuid4())
    repo.rows[file_id] = {
        "id": file_id,
        "owner_id": owner_id,
        "storage_key": "../secret",
        "size_bytes": 1,
        "status": "ready",
    }

    with pytest.raises(FileNotFound):
        await service.open_for_owner(file_id, owner_id)


@pytest.mark.asyncio
async def test_symlink_object_is_not_served(tmp_path):
    owner_id = str(uuid4())
    repo = FakeFiles()
    service = FileService(tmp_path, repo)
    outside = tmp_path.parent / "outside-file"
    outside.write_bytes(b"secret")
    file_id = str(uuid4())
    key = f"users/{owner_id}/uploads/{uuid4()}"
    path = tmp_path / key
    path.parent.mkdir(parents=True)
    path.symlink_to(outside)
    repo.rows[file_id] = {
        "id": file_id,
        "owner_id": owner_id,
        "storage_key": key,
        "size_bytes": 6,
        "status": "ready",
    }

    with pytest.raises(FileNotFound):
        await service.open_for_owner(file_id, owner_id)

    outside.unlink()


@pytest.mark.asyncio
async def test_failed_disk_write_releases_pending_quota(tmp_path, monkeypatch):
    owner_id = str(uuid4())
    repo = FakeFiles()
    service = FileService(tmp_path, repo)

    def fail_write(self: Path, data: bytes):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_bytes", fail_write)

    with pytest.raises(OSError, match="disk full"):
        await service.persist_bytes(
            owner_id=owner_id, data=b"x", kind="upload", mime_type="text/plain"
        )

    assert repo.rows == {}


@pytest.mark.asyncio
async def test_import_artifact_rejects_traversal_and_symlink(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"secret")
    (workspace / "link").symlink_to(outside)
    service = FileService(tmp_path / "storage", FakeFiles())

    for path in ("../outside", "/etc/passwd", "link"):
        with pytest.raises(ValueError):
            await service.import_artifact(
                owner_id=str(uuid4()),
                workspace_root=workspace,
                relative_path=path,
            )
