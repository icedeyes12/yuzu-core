from __future__ import annotations

import pytest

from yuzu_sandbox.proot_wrapper import RestrictedPRootBuilder


def test_restricted_proot_builder_excludes_sensitive_mounts(tmp_path):
    rootfs_dir = tmp_path / "installed-rootfs"
    rootfs_dir.mkdir(parents=True)
    sbx_rootfs = rootfs_dir / "sbx_test_instance"
    sbx_rootfs.mkdir()
    (sbx_rootfs / "tmp").mkdir()

    builder = RestrictedPRootBuilder(
        proot_bin="/usr/bin/proot",
        containers_root=str(rootfs_dir),
    )

    args = builder.build_exec_args(
        runtime_name="sbx_test_instance",
        argv=["/bin/bash", "-c", "echo hello"],
        cwd="/home/yuzu",
        uid=1000,
        gid=1000,
    )

    args_str = " ".join(args)
    # Must contain essential binds
    assert f"--rootfs={sbx_rootfs}" in args_str
    assert "--cwd=/home/yuzu" in args_str
    assert "--change-id=1000:1000" in args_str
    assert "--bind=/dev" in args_str
    assert "--bind=/proc" in args_str

    # Must NOT contain host-exposing paths
    assert "/data/data/com.termux/files/home" not in args_str
    assert "/storage/self/primary" not in args_str
    assert "/sdcard" not in args_str
    assert "supervisor.py" not in args_str


def test_invalid_runtime_name_raises(tmp_path):
    builder = RestrictedPRootBuilder(containers_root=str(tmp_path))
    with pytest.raises(ValueError, match="Invalid runtime name"):
        builder.build_exec_args(runtime_name="../escape", argv=["/bin/sh"])
