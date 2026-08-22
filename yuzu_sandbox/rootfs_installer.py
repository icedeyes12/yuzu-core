"""Approved PRoot-Distro rootfs installation adapter. ฅ^•ﻌ•^ฅ"""

from __future__ import annotations

import asyncio
import os

import httpx

from yuzu_sandbox.proot_wrapper import RestrictedPRootBuilder

_APPROVED_IMAGES = {"debian": "debian", "ubuntu": "ubuntu:24.04"}


class PRootDistroInstaller:
    def __init__(
        self,
        builder: RestrictedPRootBuilder,
        executable: str = "/data/data/com.termux/files/usr/bin/proot-distro",
    ) -> None:
        self.builder = builder
        self.executable = executable

    async def install(self, runtime_name: str, distribution: str) -> None:
        image = _APPROVED_IMAGES.get(distribution)
        if not image:
            raise ValueError("Unsupported distribution")
        await self.remove(runtime_name)
        process = await asyncio.create_subprocess_exec(
            self.executable,
            "install",
            "-q",
            "-n",
            runtime_name,
            image,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(stderr.decode(errors="replace").strip())
        if not self.builder.get_rootfs_path(runtime_name).joinpath("bin/bash").exists():
            raise RuntimeError("Installed rootfs has no /bin/bash")
        self._ensure_user(runtime_name)

    def _ensure_user(self, runtime_name: str) -> None:
        rootfs = self.builder.get_rootfs_path(runtime_name)
        (rootfs / "home" / "yuzu").mkdir(parents=True, exist_ok=True)
        passwd = rootfs / "etc" / "passwd"
        group = rootfs / "etc" / "group"
        if "yuzu:" not in passwd.read_text():
            with passwd.open("a") as handle:
                handle.write("yuzu:x:1000:1000:Yuzu:/home/yuzu:/bin/bash\n")
        if "yuzu:" not in group.read_text():
            with group.open("a") as handle:
                handle.write("yuzu:x:1000:\n")

    async def remove(self, runtime_name: str) -> None:
        rootfs = self.builder.get_rootfs_path(runtime_name)
        if not rootfs.exists():
            return
        process = await asyncio.create_subprocess_exec(
            self.executable,
            "remove",
            "-q",
            runtime_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(stderr.decode(errors="replace").strip())


class NativeRootfsInstaller:
    """Call the authenticated native Termux rootfs boundary. ฅ^•ﻌ•^ฅ"""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:5002",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    async def install(self, runtime_name: str, distribution: str) -> None:
        await self._post(
            "/rootfs/install",
            {"runtime_name": runtime_name, "distribution": distribution},
        )

    async def remove(self, runtime_name: str) -> None:
        await self._post("/rootfs/remove", {"runtime_name": runtime_name})

    async def _post(self, path: str, payload: dict[str, str]) -> None:
        token = os.environ.get("YUZU_ROOTFS_CONTROL_TOKEN", "")
        if not token:
            raise RuntimeError("YUZU_ROOTFS_CONTROL_TOKEN is required")
        async with httpx.AsyncClient(transport=self.transport, timeout=310.0) as client:
            response = await client.post(
                f"{self.base_url}{path}",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
        response.raise_for_status()
