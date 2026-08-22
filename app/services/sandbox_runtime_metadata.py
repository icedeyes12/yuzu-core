"""Canonical runtime metadata from a provisioned rootfs."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

_REQUIRED = ("ID", "VERSION_ID", "PRETTY_NAME")


def parse_os_release(content: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        parsed = shlex.split(raw_value, posix=True)
        values[key] = parsed[0] if parsed else ""

    missing = [key for key in _REQUIRED if not values.get(key)]
    if missing:
        raise ValueError(f"Missing os-release fields: {', '.join(missing)}")

    return {
        "distribution": values["ID"].lower(),
        "version_id": values["VERSION_ID"],
        "codename": values.get("VERSION_CODENAME", ""),
        "pretty_name": values["PRETTY_NAME"],
    }


def inspect_rootfs(rootfs: Path) -> dict[str, str]:
    return parse_os_release(rootfs.joinpath("etc/os-release").read_text())


def public_runtime_metadata(instance: dict[str, Any]) -> dict[str, str]:
    return {
        "distribution": str(instance["distribution"]),
        "version_id": str(instance["distribution_version"]),
        "codename": str(instance.get("distribution_codename") or ""),
        "pretty_name": str(instance.get("distribution_pretty_name") or ""),
    }
