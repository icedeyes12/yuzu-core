from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from shlex import quote

SSH_HOST = "2"
REMOTE_PROJECT = "/home/workspace/yuzu-companion"
EXCLUDED_PATHS = (
    ".git/",
    ".venv/",
    "__pycache__/",
    ".ruff_cache/",
    "node_modules/",
    ".pytest_cache/",
)
PACKAGE_FILES = ("package.json", "package-lock.json", "bun.lock", "bun.lockb")
Command = Sequence[str]
CommandRunner = Callable[[list[str]], "RemoteCommandResult"]
ValidationCommands = tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class RemoteCommandResult:
    command: list[str]
    stdout: str
    stderr: str
    exit_code: int


@dataclass(frozen=True)
class ValidationResult:
    stdout: str
    stderr: str
    exit_code: int


def is_termux() -> bool:
    return sys.platform == "android" or "com.termux" in os.environ.get("PREFIX", "")


def package_files_changed(source: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", *PACKAGE_FILES],
            cwd=source,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return bool(result.stdout.strip())


def get_default_validation_commands() -> tuple[ValidationCommands, ValidationCommands]:
    local_commands: ValidationCommands = (
        ("ruff", "format", "--check", "."),
        ("ruff", "check", "."),
        ("python", "-m", "compileall", "."),
    )
    frontend_commands: ValidationCommands = (
        (
            "sh",
            "-c",
            "find static -type f -name '*.js' -exec node --check {} +", 
        ),
        ("bunx", "biome", "check", "static/"),
        ("pytest",),
    )
    if is_termux():
        return local_commands, frontend_commands
    return local_commands + frontend_commands, ()


def build_rsync_command(
    source: Path, remote_project: str = REMOTE_PROJECT
) -> list[str]:
    command = ["rsync", "--archive", "--delete", "--compress", "--verbose"]
    for path in EXCLUDED_PATHS:
        command.extend(("--exclude", path))
    command.extend((f"{source.resolve()}/", f"{SSH_HOST}:{remote_project}/"))
    return command


def build_tar_fallback_command(
    source: Path, remote_project: str = REMOTE_PROJECT
) -> list[str]:
    excludes = " ".join(f"--exclude={path}" for path in EXCLUDED_PATHS)
    remote_script = f"mkdir -p {remote_project} && tar -xzf - -C {remote_project}"
    return [
        "sh",
        "-c",
        f"tar -czf - {excludes} -C {quote(str(source.resolve()))} . | "
        f"ssh {SSH_HOST} {quote(remote_script)}",
    ]


def run_command(command: list[str]) -> RemoteCommandResult:
    try:
        completed = subprocess.run(command, capture_output=True, text=True)
    except OSError as exc:
        return RemoteCommandResult(command, "", str(exc), 127)
    return RemoteCommandResult(
        command, completed.stdout, completed.stderr, completed.returncode
    )


def sync_remote(
    source: Path,
    remote_project: str = REMOTE_PROJECT,
    *,
    command_runner: CommandRunner = run_command,
) -> RemoteCommandResult:
    source = source.resolve()
    command = (
        build_rsync_command(source, remote_project)
        if shutil.which("rsync")
        else build_tar_fallback_command(source, remote_project)
    )
    return command_runner(command)


def detect_local_branch(
    source: Path, *, command_runner: CommandRunner = run_command
) -> RemoteCommandResult:
    command = ["git", "-C", str(source.resolve()), "branch", "--show-current"]
    return command_runner(command)


def build_remote_branch_command(
    branch: str, remote_project: str = REMOTE_PROJECT
) -> list[str]:
    git = f"git -c safe.directory={quote(remote_project)}"
    return [
        "ssh",
        SSH_HOST,
        f"cd {remote_project} && {git} fetch --all --prune && "
        f"{git} checkout -B {quote(branch)} origin/{quote(branch)}",
    ]


def build_remote_status_command(
    remote_project: str = REMOTE_PROJECT,
) -> list[str]:
    git = f"git -c safe.directory={quote(remote_project)}"
    return ["ssh", SSH_HOST, f"cd {remote_project} && {git} status --porcelain"]


def build_install_command(
    package_changed: bool,
    *,
    remote: bool,
    source: Path,
    remote_project: str = REMOTE_PROJECT,
) -> list[str] | None:
    if remote:
        condition = "true" if package_changed else "[ ! -d node_modules ]"
        return [
            "ssh",
            SSH_HOST,
            f"cd {remote_project} && if {condition}; then bun install --frozen-lockfile; fi",
        ]
    if not package_changed and (source / "node_modules").is_dir():
        return None
    return ["bun", "install", "--frozen-lockfile"]


def build_remote_command(
    command: Command, remote_project: str = REMOTE_PROJECT
) -> list[str]:
    return [
        "ssh",
        SSH_HOST,
        f"cd {remote_project} && {' '.join(quote(part) for part in command)}",
    ]


def run_validation_pipeline(
    source: Path,
    *,
    local_commands: Sequence[Command] | None = None,
    remote_commands: Sequence[Command] | None = None,
    remote_project: str = REMOTE_PROJECT,
    command_runner: CommandRunner = run_command,
    sync_runner: Callable[[], RemoteCommandResult] | None = None,
) -> ValidationResult:
    outputs: list[str] = []
    errors: list[str] = []
    default_local, default_remote = get_default_validation_commands()
    local_commands = local_commands if local_commands is not None else default_local
    remote_commands = remote_commands if remote_commands is not None else default_remote

    def execute(command: list[str]) -> bool:
        result = command_runner(command)
        outputs.append(result.stdout)
        errors.append(result.stderr)
        return result.exit_code == 0

    local_prefix = local_commands[:3]
    local_suffix = local_commands[3:]
    for command in local_prefix:
        if not execute(list(command)):
            return ValidationResult("".join(outputs), "".join(errors), 1)

    if not remote_commands:
        install = build_install_command(
            package_files_changed(source),
            remote=False,
            source=source,
            remote_project=remote_project,
        )
        if install is not None and not execute(install):
            return ValidationResult("".join(outputs), "".join(errors), 1)
        for command in local_suffix:
            if not execute(list(command)):
                return ValidationResult("".join(outputs), "".join(errors), 1)
        return ValidationResult("".join(outputs), "".join(errors), 0)

    remote_status = command_runner(build_remote_status_command(remote_project))
    outputs.append(remote_status.stdout)
    errors.append(remote_status.stderr)
    if remote_status.exit_code:
        return ValidationResult(
            "".join(outputs), "".join(errors), remote_status.exit_code
        )
    if remote_status.stdout.strip():
        errors.append(
            "Remote repository contains uncommitted changes.\n"
            "Please commit or stash your work before running yuzu-validate.\n"
        )
        return ValidationResult("".join(outputs), "".join(errors), 1)

    branch_result = detect_local_branch(source, command_runner=command_runner)
    outputs.append(branch_result.stdout)
    errors.append(branch_result.stderr)
    branch = branch_result.stdout.strip()
    if branch_result.exit_code or not branch:
        return ValidationResult(
            "".join(outputs), "".join(errors), branch_result.exit_code or 1
        )

    branch_sync = command_runner(build_remote_branch_command(branch, remote_project))
    outputs.append(branch_sync.stdout)
    errors.append(branch_sync.stderr)
    if branch_sync.exit_code:
        return ValidationResult(
            "".join(outputs), "".join(errors), branch_sync.exit_code
        )

    sync_result = (
        sync_runner()
        if sync_runner
        else sync_remote(source, remote_project, command_runner=command_runner)
    )
    outputs.append(sync_result.stdout)
    errors.append(sync_result.stderr)
    if sync_result.exit_code:
        return ValidationResult("".join(outputs), "".join(errors), sync_result.exit_code)

    install = build_install_command(
        package_files_changed(source),
        remote=True,
        source=source,
        remote_project=remote_project,
    )
    commands = ([install] if install is not None else []) + [
        build_remote_command(command, remote_project) for command in remote_commands
    ]
    for command in commands:
        if not execute(command):
            return ValidationResult("".join(outputs), "".join(errors), 1)

    return ValidationResult("".join(outputs), "".join(errors), 0)


__all__ = [
    "EXCLUDED_PATHS",
    "REMOTE_PROJECT",
    "SSH_HOST",
    "RemoteCommandResult",
    "ValidationResult",
    "build_install_command",
    "build_remote_branch_command",
    "build_remote_command",
    "build_remote_status_command",
    "build_rsync_command",
    "build_tar_fallback_command",
    "get_default_validation_commands",
    "detect_local_branch",
    "is_termux",
    "package_files_changed",
    "run_validation_pipeline",
    "sync_remote",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="yuzu-validate",
        description="Run local validators, sync to Zo Computer, then run remote validators.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path.cwd(),
        help="Workspace to validate and sync (default: current directory)",
    )
    args = parser.parse_args()
    result = run_validation_pipeline(args.source)
    print(result.stdout, end="")
    print(result.stderr, end="")
    raise SystemExit(result.exit_code)


if __name__ == "__main__":
    main()
