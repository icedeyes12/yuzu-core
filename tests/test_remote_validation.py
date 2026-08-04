from __future__ import annotations

from pathlib import Path

from scripts.remote_validation import (
    EXCLUDED_PATHS,
    RemoteCommandResult,
    build_install_command,
    build_remote_branch_command,
    build_remote_status_command,
    build_rsync_command,
    get_default_validation_commands,
    run_validation_pipeline,
)


def test_build_rsync_command_uses_ssh_alias_and_excludes_generated_paths() -> None:
    command = build_rsync_command(Path("/repo"), "/home/workspace/yuzu-companion")

    assert command[:5] == ["rsync", "--archive", "--delete", "--compress", "--verbose"]
    assert command[-2:] == ["/repo/", "2:/home/workspace/yuzu-companion/"]
    for index, path in enumerate(EXCLUDED_PATHS):
        assert command[5 + index * 2 : 7 + index * 2] == ["--exclude", path]


def test_linux_pipeline_runs_format_lint_install_biome_then_pytest(monkeypatch) -> None:
    monkeypatch.setattr("scripts.remote_validation.is_termux", lambda: False)
    monkeypatch.setattr("scripts.remote_validation.package_files_changed", lambda _: True)
    calls: list[str] = []

    result = run_validation_pipeline(
        Path("/repo"),
        command_runner=lambda command: (
            calls.append(" ".join(command))
            or RemoteCommandResult(command, "ok", "", 0)
        ),
    )

    assert result.exit_code == 0
    assert calls == [
        "ruff format --check .",
        "ruff check .",
        "python -m compileall .",
        "bun install --frozen-lockfile",
        "sh -c find static -type f -name '*.js' -exec node --check {} +",
        "bunx biome check static/",
        "pytest",
    ]


def test_termux_pipeline_syncs_then_runs_all_remaining_validation_remotely(monkeypatch) -> None:
    monkeypatch.setattr("scripts.remote_validation.is_termux", lambda: True)
    monkeypatch.setattr(
        "scripts.remote_validation.package_files_changed", lambda _: True
    )
    calls: list[str] = []

    def runner(command: list[str]) -> RemoteCommandResult:
        calls.append(" ".join(command))
        if command[:4] == ["git", "-C", "/repo", "branch"]:
            stdout = "dev\n"
        elif command[-1].endswith("status --porcelain"):
            stdout = ""
        else:
            stdout = "ok"
        return RemoteCommandResult(command, stdout, "", 0)

    result = run_validation_pipeline(
        Path("/repo"),
        command_runner=runner,
        sync_runner=lambda: (
            calls.append("sync") or RemoteCommandResult(["sync"], "", "", 0)
        ),
    )

    assert result.exit_code == 0
    assert calls[:8] == [
        "ruff format --check .",
        "ruff check .",
        "python -m compileall .",
        "ssh 2 cd /home/workspace/yuzu-companion && git -c safe.directory=/home/workspace/yuzu-companion status --porcelain",
        "git -C /repo branch --show-current",
        "ssh 2 cd /home/workspace/yuzu-companion && git -c safe.directory=/home/workspace/yuzu-companion fetch --all --prune && git -c safe.directory=/home/workspace/yuzu-companion checkout -B dev origin/dev",
        "sync",
        "ssh 2 cd /home/workspace/yuzu-companion && if true; then bun install --frozen-lockfile; fi",
    ]
    assert "ssh 2 cd /home/workspace/yuzu-companion && sh -c" in calls[8]
    assert "-exec node --check {} +" in calls[8]
    assert calls[9:] == [
        "ssh 2 cd /home/workspace/yuzu-companion && bunx biome check static/",
        "ssh 2 cd /home/workspace/yuzu-companion && pytest",
    ]


def test_fail_fast_stops_before_expensive_steps(monkeypatch) -> None:
    monkeypatch.setattr("scripts.remote_validation.is_termux", lambda: False)
    calls: list[str] = []

    def runner(command: list[str]) -> RemoteCommandResult:
        calls.append(" ".join(command))
        failed = command == ["ruff", "check", "."]
        return RemoteCommandResult(command, "", "failed", int(failed))

    result = run_validation_pipeline(Path("/repo"), command_runner=runner)

    assert result.exit_code == 1
    assert calls == [
        "ruff format --check .",
        "ruff check .",
    ]


def test_install_is_skipped_when_local_dependencies_are_ready(tmp_path) -> None:
    (tmp_path / "node_modules").mkdir()

    assert build_install_command(
        False, remote=False, source=tmp_path
    ) is None


def test_remote_branch_command_fetches_then_checks_out_requested_branch() -> None:
    assert build_remote_branch_command("feature/test") == [
        "ssh",
        "2",
        "cd /home/workspace/yuzu-companion && git -c safe.directory=/home/workspace/yuzu-companion fetch --all --prune && git -c safe.directory=/home/workspace/yuzu-companion checkout -B feature/test origin/feature/test",
    ]


def test_remote_status_command_checks_porcelain_without_mutation() -> None:
    assert build_remote_status_command() == [
        "ssh",
        "2",
        "cd /home/workspace/yuzu-companion && git -c safe.directory=/home/workspace/yuzu-companion status --porcelain",
    ]


def test_dirty_remote_stops_before_branch_fetch_or_sync(monkeypatch) -> None:
    monkeypatch.setattr("scripts.remote_validation.is_termux", lambda: True)
    calls: list[str] = []

    def runner(command: list[str]) -> RemoteCommandResult:
        calls.append(" ".join(command))
        if command[-1].endswith("status --porcelain"):
            return RemoteCommandResult(command, " M remote-work.py\n", "", 0)
        return RemoteCommandResult(command, "", "", 0)

    result = run_validation_pipeline(Path("/repo"), command_runner=runner)

    assert result.exit_code == 1
    assert "Remote repository contains uncommitted changes." in result.stderr
    assert "Please commit or stash your work before running yuzu-validate." in result.stderr
    assert len(calls) == 4
    assert all("fetch" not in call and "rsync" not in call for call in calls)


def test_default_commands_use_remote_bunx_on_termux(monkeypatch) -> None:
    monkeypatch.setattr("scripts.remote_validation.is_termux", lambda: True)

    local, remote = get_default_validation_commands()

    assert local == (
        ("ruff", "format", "--check", "."),
        ("ruff", "check", "."),
        ("python", "-m", "compileall", "."),
    )
    assert remote[-2:] == (("bunx", "biome", "check", "static/"), ("pytest",))
    assert remote[0][0:2] == ("sh", "-c")


def test_default_commands_use_local_bunx_on_linux(monkeypatch) -> None:
    monkeypatch.setattr("scripts.remote_validation.is_termux", lambda: False)

    local, remote = get_default_validation_commands()

    assert remote == ()
    assert local[-2:] == (("bunx", "biome", "check", "static/"), ("pytest",))
    assert local[3][0:2] == ("sh", "-c")
