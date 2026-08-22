from __future__ import annotations

from app.services.sandbox_skills import SandboxSkillDiscoverer
from yuzu_sandbox.proot_wrapper import RestrictedPRootBuilder


def test_discover_user_sandbox_skills(tmp_path):
    rootfs = tmp_path / "sbx_test"
    skills_dir = rootfs / "home" / "yuzu" / ".yuzu" / "skills"
    skills_dir.mkdir(parents=True)

    # 1. Add valid skill
    custom_skill = skills_dir / "my-calculator"
    custom_skill.mkdir()
    (custom_skill / "SKILL.md").write_text(
        "---\nname: my-calculator\ndescription: A test calculator skill\nentrypoint: python3 calc.py\n---\n# Docs"
    )

    # 2. Add invalid / non-skill dir
    random_dir = skills_dir / "random"
    random_dir.mkdir()

    builder = RestrictedPRootBuilder(containers_root=str(tmp_path))
    discoverer = SandboxSkillDiscoverer(builder)

    skills = discoverer.discover_skills("sbx_test")
    assert len(skills) == 1
    assert skills[0]["name"] == "my-calculator"
    assert skills[0]["entrypoint"] == "python3 calc.py"
    assert skills[0]["is_sandbox_skill"] is True
