"""
Restricted PRoot Launcher & Invocation Builder for Yuzu Sandbox.
Ensures minimal sanitized mounts without exposing Termux home, SSH keys,
or production Yuzu code/data.
ฅ^•ﻌ•^ฅ
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_PROOT_BIN = "/data/data/com.termux/files/usr/bin/proot"
PROOT_CONTAINERS_DIR = (
    "/data/data/com.termux/files/usr/var/lib/proot-distro/installed-rootfs"
)


class RestrictedPRootBuilder:
    """Builds isolated arguments for PRoot invocation."""

    def __init__(
        self,
        proot_bin: str = DEFAULT_PROOT_BIN,
        containers_root: str = PROOT_CONTAINERS_DIR,
    ) -> None:
        self.proot_bin = proot_bin
        self.containers_root = Path(containers_root)

    def get_rootfs_path(self, runtime_name: str) -> Path:
        """Resolve the rootfs path for a specific user sandbox instance."""
        if not runtime_name or "/" in runtime_name or ".." in runtime_name:
            raise ValueError(f"Invalid runtime name: {runtime_name}")
        return self.containers_root / runtime_name

    def build_exec_args(
        self,
        runtime_name: str,
        argv: list[str],
        cwd: str = "/home/yuzu",
        uid: int = 1000,
        gid: int = 1000,
    ) -> list[str]:
        """Construct the proot command with sanitized bindings.

        Explicitly excludes:
        - /data/data/com.termux/files/home (~/.ssh, ~/supervisor.py, ~/services)
        - /storage/self/primary (Android internal shared storage)
        - Production yuzu repository mounts
        """
        rootfs = self.get_rootfs_path(runtime_name)
        if not argv:
            raise ValueError("argv cannot be empty")

        tmp_shm = rootfs / "tmp"

        args = [
            self.proot_bin,
            "--kill-on-exit",
            "--link2symlink",
            "--sysvipc",
            f"--rootfs={rootfs}",
            f"--cwd={cwd}",
            f"--change-id={uid}:{gid}",
            "--bind=/dev",
            "--bind=/dev/urandom:/dev/random",
            "--bind=/proc",
            "--bind=/sys",
        ]

        if tmp_shm.exists():
            args.append(f"--bind={tmp_shm}:/dev/shm")

        args.extend(argv)
        return args
