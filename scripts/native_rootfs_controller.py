"""Native Termux rootfs lifecycle controller. ฅ^•ﻌ•^ฅ"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_RUNTIME_NAME = re.compile(r"^sbx_[0-9a-f]{24}$")
_IMAGES = {"debian": "debian", "ubuntu": "ubuntu:24.04"}
_MAX_BODY_BYTES = 1024


def validate_request(
    authorization: str, path: str, payload: dict[str, Any]
) -> tuple[str, str | None]:
    token = os.environ.get("YUZU_ROOTFS_CONTROL_TOKEN", "")
    supplied = authorization.removeprefix("Bearer ")
    if not token or not hmac.compare_digest(supplied, token):
        raise PermissionError("Unauthorized")
    if path not in {"/rootfs/install", "/rootfs/remove"}:
        raise ValueError("Unsupported operation")
    allowed = (
        {"runtime_name", "distribution"}
        if path.endswith("install")
        else {"runtime_name"}
    )
    if set(payload) != allowed:
        raise ValueError("Invalid request fields")
    runtime_name = payload.get("runtime_name")
    if not isinstance(runtime_name, str) or not _RUNTIME_NAME.fullmatch(runtime_name):
        raise ValueError("Invalid runtime name")
    distribution = payload.get("distribution")
    if path.endswith("install") and distribution not in _IMAGES:
        raise ValueError("Unsupported distribution")
    return runtime_name, distribution


def build_command(path: str, runtime_name: str, distribution: str | None) -> list[str]:
    if path.endswith("install"):
        return [
            "proot-distro",
            "install",
            "-q",
            "-n",
            runtime_name,
            _IMAGES[str(distribution)],
        ]
    return ["proot-distro", "remove", "-q", runtime_name]


def _ensure_user(runtime_name: str) -> None:
    prefix = Path(os.environ["PREFIX"])
    rootfs = prefix / "var/lib/proot-distro/containers" / runtime_name / "rootfs"
    (rootfs / "home/yuzu").mkdir(parents=True, exist_ok=True)
    passwd = rootfs / "etc/passwd"
    group = rootfs / "etc/group"
    if "yuzu:" not in passwd.read_text():
        with passwd.open("a") as handle:
            handle.write("yuzu:x:1000:1000:Yuzu:/home/yuzu:/bin/bash\n")
    if "yuzu:" not in group.read_text():
        with group.open("a") as handle:
            handle.write("yuzu:x:1000:\n")


class RootfsHandler(BaseHTTPRequestHandler):
    server_version = "yuzu-rootfs-control/1"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._reply(200, {"status": "ok", "boundary": "native-termux"})
            return
        self._reply(404, {"error": "Not found"})

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > _MAX_BODY_BYTES:
                raise ValueError("Invalid body size")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Invalid JSON object")
            runtime_name, distribution = validate_request(
                self.headers.get("Authorization", ""), self.path, payload
            )
            completed = subprocess.run(
                build_command(self.path, runtime_name, distribution),
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            if completed.returncode != 0:
                self._reply(
                    500, {"error": completed.stderr.strip() or "Operation failed"}
                )
                return
            if self.path.endswith("install"):
                _ensure_user(runtime_name)
            self._reply(200, {"status": "installed" if distribution else "removed"})
        except PermissionError as error:
            self._reply(401, {"error": str(error)})
        except (ValueError, json.JSONDecodeError) as error:
            self._reply(422, {"error": str(error)})
        except subprocess.TimeoutExpired:
            self._reply(504, {"error": "Operation timed out"})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _reply(self, status: int, payload: dict[str, str]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def server_address(port: int) -> tuple[str, int]:
    return "127.0.0.1", port


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5002)
    args = parser.parse_args()
    if not os.environ.get("YUZU_ROOTFS_CONTROL_TOKEN"):
        raise SystemExit("YUZU_ROOTFS_CONTROL_TOKEN is required")
    ThreadingHTTPServer(server_address(args.port), RootfsHandler).serve_forever()


if __name__ == "__main__":
    main()
