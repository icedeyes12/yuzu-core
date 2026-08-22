from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.files import get_current_user, get_file_service
from app.core.ids import EntityType, PublicId
from main import app


class FakeFileService:
    def __init__(self, owner_id: str, path: Path) -> None:
        self.owner_id = owner_id
        self.path = path

    async def open_for_owner(self, file_id: str, owner_id: str):
        from app.services.file_service import FileNotFound

        if owner_id != self.owner_id:
            raise FileNotFound
        return (
            {
                "id": file_id,
                "mime_type": "text/plain",
                "original_name": "note.txt",
            },
            self.path,
        )


def test_private_file_route_uses_authenticated_owner(tmp_path):
    owner_id = str(uuid4())
    file_id = str(uuid4())
    path = tmp_path / "object"
    path.write_text("private")
    service = FakeFileService(owner_id, path)
    app.dependency_overrides[get_current_user] = lambda: owner_id
    app.dependency_overrides[get_file_service] = lambda: service
    try:
        response = TestClient(app).get(
            f"/v1/files/{PublicId.encode(EntityType.FILE, file_id)}"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.text == "private"
    assert response.headers["content-type"].startswith("text/plain")
    assert 'filename="note.txt"' in response.headers["content-disposition"]


def test_private_file_route_hides_cross_owner_file(tmp_path):
    owner_id = str(uuid4())
    path = tmp_path / "object"
    path.write_text("private")
    service = FakeFileService(owner_id, path)
    app.dependency_overrides[get_current_user] = lambda: str(uuid4())
    app.dependency_overrides[get_file_service] = lambda: service
    try:
        response = TestClient(app).get(
            f"/v1/files/{PublicId.encode(EntityType.FILE, uuid4())}"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


def test_private_file_route_rejects_raw_uuid(tmp_path):
    owner_id = str(uuid4())
    file_id = str(uuid4())
    path = tmp_path / "object"
    path.write_text("private")
    app.dependency_overrides[get_current_user] = lambda: owner_id
    app.dependency_overrides[get_file_service] = lambda: FakeFileService(owner_id, path)
    try:
        response = TestClient(app).get(f"/v1/files/{file_id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
