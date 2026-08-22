"""
User Sandbox Skill Discovery & Manifest Parser.
Discovers declarative SKILL.md manifests inside user's PRoot (/home/yuzu/.yuzu/skills/).
Never imports user Python code into Yuzu Core.
ฅ^•ﻌ•^ฅ
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from yuzu_sandbox.proot_wrapper import RestrictedPRootBuilder


class SandboxSkillDiscoverer:
    """Discovers and parses user skills located inside a sandbox container."""

    def __init__(self, proot_builder: RestrictedPRootBuilder | None = None) -> None:
        self.builder = proot_builder or RestrictedPRootBuilder()

    def discover_skills(self, runtime_name: str) -> list[dict[str, Any]]:
        """List all valid skill manifests inside the user's sandbox directory."""
        rootfs = self.builder.get_rootfs_path(runtime_name)
        skills_dir = rootfs / "home" / "yuzu" / ".yuzu" / "skills"
        if not skills_dir.exists() or not skills_dir.is_dir():
            return []

        discovered = []
        for skill_path in skills_dir.iterdir():
            if not skill_path.is_dir() or skill_path.is_symlink():
                continue
            manifest_file = skill_path / "SKILL.md"
            if (
                manifest_file.exists()
                and manifest_file.is_file()
                and not manifest_file.is_symlink()
            ):
                parsed = self._parse_manifest(manifest_file)
                if parsed:
                    discovered.append(parsed)

        return discovered

    @staticmethod
    def _parse_manifest(path: Path) -> dict[str, Any] | None:
        try:
            content = path.read_text(encoding="utf-8")
            match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
            if not match:
                return None
            frontmatter = yaml.safe_load(match.group(1))
            if not isinstance(frontmatter, dict):
                return None
            name = frontmatter.get("name")
            desc = frontmatter.get("description", "")
            if not name:
                return None
            return {
                "name": str(name),
                "description": str(desc),
                "version": str(frontmatter.get("version", "1.0.0")),
                "entrypoint": str(frontmatter.get("entrypoint", "")),
                "is_sandbox_skill": True,
            }
        except Exception:
            return None
