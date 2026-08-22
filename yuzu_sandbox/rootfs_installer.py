"""Approved PRoot-Distro rootfs installation adapter. ฅ^•ﻌ•^ฅ"""

from __future__ import annotations

import asyncio

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
