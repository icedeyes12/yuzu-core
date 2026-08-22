"""
Sandbox Lifecycle Service (My Computer Orchestration Engine).
Handles asynchronous provisioning, rootfs setup, generation rotation,
and process dispatch for user sandboxes.
ฅ^•ﻌ•^ฅ
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Protocol

from app.core.ids import EntityType, PublicId
from yuzu_sandbox.proot_wrapper import RestrictedPRootBuilder
from yuzu_sandbox.rootfs_installer import PRootDistroInstaller


class SandboxInstanceRepository(Protocol):
    async def get_by_owner(self, owner_id: str) -> dict[str, Any] | None: ...
    async def create(
        self,
        *,
        owner_id: str,
        distribution: str,
        distribution_version: str,
        storage_limit_bytes: int,
    ) -> dict[str, Any]: ...
    async def update_state(
        self, owner_id: str, state: str, error: str | None = None
    ) -> dict[str, Any] | None: ...
    async def bump_generation(
        self,
        owner_id: str,
        next_state: str = "provisioning",
        distribution: str | None = None,
        distribution_version: str | None = None,
    ) -> dict[str, Any] | None: ...
    async def delete(self, owner_id: str) -> dict[str, Any] | None: ...


class RootfsInstaller(Protocol):
    async def install(self, runtime_name: str, distribution: str) -> None: ...
    async def remove(self, runtime_name: str) -> None: ...


class SandboxLifecycleEngine:
    """Manages the full lifecycle of persistent per-user sandbox instances."""

    def __init__(
        self,
        repository: SandboxInstanceRepository,
        proot_builder: RestrictedPRootBuilder,
        containers_root: Path | None = None,
        installer: RootfsInstaller | None = None,
    ) -> None:
        self.repository = repository
        self.proot_builder = proot_builder
        self.containers_root = containers_root or proot_builder.containers_root
        self.installer = installer or PRootDistroInstaller(proot_builder)

    async def get_status(self, owner_id: str) -> dict[str, Any]:
        """Fetch current sandbox instance metadata and logical state."""
        instance = await self.repository.get_by_owner(owner_id)
        if not instance:
            return {"has_sandbox": False, "state": "none"}

        # Calculate actual disk usage on filesystem if ready
        rootfs_path = self.proot_builder.get_rootfs_path(instance["runtime_name"])
        used_bytes = 0
        if rootfs_path.exists():
            used_bytes = await asyncio.to_thread(self._get_dir_size, rootfs_path)

        return {
            "has_sandbox": True,
            "id": PublicId.encode(EntityType.SANDBOX, instance["id"]),
            "distribution": instance["distribution"],
            "distribution_version": instance["distribution_version"],
            "generation": instance["generation"],
            "state": instance["state"],
            "storage_used_bytes": used_bytes,
            "storage_limit_bytes": instance["storage_limit_bytes"],
            "last_error": instance.get("last_error"),
            "created_at": instance["created_at"].isoformat()
            if hasattr(instance["created_at"], "isoformat")
            else str(instance["created_at"]),
        }

    async def provision_sandbox(
        self,
        owner_id: str,
        distribution: str = "debian",
        distribution_version: str = "12",
    ) -> dict[str, Any]:
        """Create and asynchronously bootstrap a new persistent sandbox."""
        if distribution not in ("debian", "ubuntu"):
            raise ValueError(f"Unsupported distribution: {distribution}")

        existing = await self.repository.get_by_owner(owner_id)
        if existing and existing["state"] not in ("failed", "none"):
            raise ValueError("Sandbox instance already exists for this user")

        instance = await self.repository.create(
            owner_id=owner_id,
            distribution=distribution,
            distribution_version=distribution_version,
        )

        # Trigger background provisioning task
        asyncio.create_task(
            self._bootstrap_rootfs(owner_id, instance["runtime_name"], distribution)
        )
        return await self.get_status(owner_id)

    async def delete_sandbox(self, owner_id: str, confirmation: str) -> bool:
        """Permanently delete user sandbox rootfs and release resources."""
        if confirmation != "DELETE":
            raise ValueError("Explicit 'DELETE' confirmation required")

        instance = await self.repository.get_by_owner(owner_id)
        if not instance:
            return False

        await self.repository.update_state(owner_id, "deleting")
        await self.installer.remove(instance["runtime_name"])

        await self.repository.delete(owner_id)
        return True

    async def reset_sandbox(self, owner_id: str, confirmation: str) -> dict[str, Any]:
        """Wipe and re-provision user sandbox with a new generation ID."""
        if confirmation != "RESET":
            raise ValueError("Explicit 'RESET' confirmation required")

        instance = await self.repository.get_by_owner(owner_id)
        if not instance:
            raise ValueError("No sandbox found to reset")

        # Increment generation to invalidate all existing PTY tokens/sessions
        bumped = await self.repository.bump_generation(owner_id, next_state="resetting")
        await self.installer.remove(instance["runtime_name"])

        asyncio.create_task(
            self._bootstrap_rootfs(
                owner_id, instance["runtime_name"], bumped["distribution"]
            )
        )
        return await self.get_status(owner_id)

    async def _bootstrap_rootfs(
        self, owner_id: str, runtime_name: str, distribution: str
    ) -> None:
        """Mock/Real async rootfs extraction & initial user setup."""
        try:
            await self.installer.install(runtime_name, distribution)
            rootfs_path = self.proot_builder.get_rootfs_path(runtime_name)
            # Create user workspace scaffold
            user_home = rootfs_path / "home" / "yuzu"
            await asyncio.to_thread(
                (user_home / ".yuzu" / "skills").mkdir, parents=True, exist_ok=True
            )
            await self.repository.update_state(owner_id, "ready")
        except Exception as e:
            await self.repository.update_state(owner_id, "failed", error=str(e))

    @staticmethod
    def _get_dir_size(path: Path) -> int:
        total = 0
        if not path.exists():
            return 0
        for entry in path.rglob("*"):
            if entry.is_file() and not entry.is_symlink():
                total += entry.stat().st_size
        return total
