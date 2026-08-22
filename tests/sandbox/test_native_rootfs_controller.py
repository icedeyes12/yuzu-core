from __future__ import annotations

import httpx
import pytest

from scripts.native_rootfs_controller import (
    build_command,
    server_address,
    validate_request,
)
from yuzu_sandbox.rootfs_installer import NativeRootfsInstaller


def test_native_controller_validates_auth_and_payload(monkeypatch):
    monkeypatch.setenv("YUZU_ROOTFS_CONTROL_TOKEN", "test-token")

    assert validate_request(
        "Bearer test-token",
        "/rootfs/install",
        {
            "runtime_name": "sbx_01a02aaa8ea07f999f52a483",
            "distribution": "debian",
        },
    ) == ("sbx_01a02aaa8ea07f999f52a483", "debian")

    with pytest.raises(PermissionError):
        validate_request(
            "Bearer wrong",
            "/rootfs/remove",
            {"runtime_name": "sbx_01a02aaa8ea07f999f52a483"},
        )
    with pytest.raises(ValueError):
        validate_request(
            "Bearer test-token", "/rootfs/remove", {"runtime_name": "../escape"}
        )


def test_native_controller_binds_loopback_only():
    assert server_address(5002) == ("127.0.0.1", 5002)


def test_native_controller_builds_argv_without_shell():
    assert build_command(
        "/rootfs/install", "sbx_01a02aaa8ea07f999f52a483", "debian"
    ) == [
        "proot-distro",
        "install",
        "-q",
        "-n",
        "sbx_01a02aaa8ea07f999f52a483",
        "debian",
    ]
    assert build_command("/rootfs/remove", "sbx_01a02aaa8ea07f999f52a483", None) == [
        "proot-distro",
        "remove",
        "-q",
        "sbx_01a02aaa8ea07f999f52a483",
    ]


@pytest.mark.asyncio
async def test_core_adapter_calls_native_controller(monkeypatch):
    requests: list[httpx.Request] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "installed"})

    monkeypatch.setenv("YUZU_ROOTFS_CONTROL_TOKEN", "test-token")
    installer = NativeRootfsInstaller(transport=httpx.MockTransport(handle))

    await installer.install("sbx_01a02aaa8ea07f999f52a483", "debian")

    assert requests[0].url == "http://127.0.0.1:5002/rootfs/install"
    assert requests[0].headers["authorization"] == "Bearer test-token"


@pytest.mark.asyncio
async def test_core_adapter_fails_closed_without_token(monkeypatch):
    monkeypatch.delenv("YUZU_ROOTFS_CONTROL_TOKEN", raising=False)
    installer = NativeRootfsInstaller()

    with pytest.raises(RuntimeError, match="YUZU_ROOTFS_CONTROL_TOKEN"):
        await installer.remove("sbx_01a02aaa8ea07f999f52a483")
