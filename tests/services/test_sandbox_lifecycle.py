from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.services.sandbox_lifecycle import SandboxLifecycleEngine
from yuzu_sandbox.proot_wrapper import RestrictedPRootBuilder


class FakeRootfsInstaller:
    async def install(self, runtime_name: str, distribution: str) -> None:
        rootfs = self.builder.get_rootfs_path(runtime_name)
        (rootfs / "bin").mkdir(parents=True)
        (rootfs / "bin" / "bash").write_text("shell")

    async def remove(self, runtime_name: str) -> None:
        import shutil

        shutil.rmtree(self.builder.get_rootfs_path(runtime_name).parent, True)

    def __init__(self, builder: RestrictedPRootBuilder) -> None:
        self.builder = builder


class FakeSandboxRepo:
    def __init__(self) -> None:
        self.instances: dict[str, dict] = {}

    async def get_by_owner(self, owner_id: str):
        return self.instances.get(owner_id)

    async def create(
        self,
        *,
        owner_id: str,
        distribution: str,
        distribution_version: str,
        storage_limit_bytes: int = 10737418240,
    ):
        row = {
            "id": str(uuid4()),
            "owner_id": owner_id,
            "runtime_name": f"sbx_{owner_id[:8]}",
            "distribution": distribution,
            "distribution_version": distribution_version,
            "generation": 1,
            "state": "provisioning",
            "storage_limit_bytes": storage_limit_bytes,
            "last_error": None,
            "created_at": "2026-08-22T00:00:00Z",
        }
        self.instances[owner_id] = row
        return row

    async def update_state(self, owner_id: str, state: str, error: str | None = None):
        if owner_id in self.instances:
            self.instances[owner_id]["state"] = state
            self.instances[owner_id]["last_error"] = error
            return self.instances[owner_id]
        return None

    async def bump_generation(
        self,
        owner_id: str,
        next_state: str = "provisioning",
        distribution: str | None = None,
        distribution_version: str | None = None,
    ):
        if owner_id in self.instances:
            self.instances[owner_id]["generation"] += 1
            self.instances[owner_id]["state"] = next_state
            if distribution:
                self.instances[owner_id]["distribution"] = distribution
            return self.instances[owner_id]
        return None

    async def delete(self, owner_id: str):
        return self.instances.pop(owner_id, None)


@pytest.mark.asyncio
async def test_sandbox_lifecycle_flow(tmp_path):
    repo = FakeSandboxRepo()
    builder = RestrictedPRootBuilder(containers_root=str(tmp_path))
    engine = SandboxLifecycleEngine(
        repo, builder, installer=FakeRootfsInstaller(builder)
    )

    owner_id = str(uuid4())

    # 1. Check initial empty state
    status = await engine.get_status(owner_id)
    assert status["has_sandbox"] is False
    assert status["state"] == "none"

    # 2. Provision Debian sandbox
    res = await engine.provision_sandbox(owner_id, "debian")
    assert res["has_sandbox"] is True
    # Wait small tick for async task
    await asyncio.sleep(0.05)

    ready_status = await engine.get_status(owner_id)
    assert ready_status["state"] == "ready"
    assert ready_status["generation"] == 1
    assert (
        tmp_path
        / f"sbx_{owner_id[:8]}"
        / "rootfs"
        / "home"
        / "yuzu"
        / ".yuzu"
        / "skills"
    ).exists()

    # 3. Reset sandbox (generation increment)
    _ = await engine.reset_sandbox(owner_id, confirmation="RESET")
    await asyncio.sleep(0.05)
    bumped_status = await engine.get_status(owner_id)
    assert bumped_status["generation"] == 2
    assert bumped_status["state"] == "ready"

    # 4. Delete sandbox
    deleted = await engine.delete_sandbox(owner_id, confirmation="DELETE")
    assert deleted is True
    post_delete = await engine.get_status(owner_id)
    assert post_delete["has_sandbox"] is False
