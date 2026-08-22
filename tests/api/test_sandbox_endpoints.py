from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.sandbox import get_lifecycle_engine
from app.api.utils import get_current_user
from main import app


class FakeEngine:
    def __init__(self, owner_id: str) -> None:
        self.owner_id = owner_id
        self.state = "none"

    async def get_status(self, user_id: str):
        assert user_id == self.owner_id
        return {"has_sandbox": self.state != "none", "state": self.state}

    async def provision_sandbox(self, owner_id: str, distribution: str):
        assert owner_id == self.owner_id
        self.state = "ready"
        return {"has_sandbox": True, "state": "ready"}

    async def reset_sandbox(self, owner_id: str, confirmation: str):
        assert owner_id == self.owner_id
        if confirmation != "RESET":
            raise ValueError("Bad confirm")
        return {"has_sandbox": True, "state": "ready"}

    async def delete_sandbox(self, owner_id: str, confirmation: str):
        assert owner_id == self.owner_id
        if confirmation != "DELETE":
            raise ValueError("Bad confirm")
        self.state = "none"
        return True


def test_sandbox_api_endpoints():
    owner_id = str(uuid4())
    fake_engine = FakeEngine(owner_id)

    app.dependency_overrides[get_current_user] = lambda: owner_id
    app.dependency_overrides[get_lifecycle_engine] = lambda: fake_engine

    try:
        client = TestClient(app)

        # 1. Initial status
        res = client.get("/api/v1/sandbox/status")
        assert res.status_code == 200
        assert res.json()["has_sandbox"] is False

        # 2. Provision
        res = client.post(
            "/api/v1/sandbox/provision",
            json={"distribution": "debian"},
        )
        assert res.status_code == 200
        assert res.json()["state"] == "ready"

        stale = client.post(
            "/api/v1/sandbox/provision",
            json={"distribution": "debian", "distribution_version": "12"},
        )
        assert stale.status_code == 422

        # 3. Reset
        res = client.post("/api/v1/sandbox/reset", json={"confirmation": "RESET"})
        assert res.status_code == 200

        # 4. Delete
        res = client.delete("/api/v1/sandbox?confirmation=DELETE")
        assert res.status_code == 200
    finally:
        app.dependency_overrides.clear()
