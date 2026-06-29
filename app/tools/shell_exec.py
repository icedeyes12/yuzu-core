from __future__ import annotations

import os
import re
import shutil
import logging
import time
import asyncio
from pathlib import Path

from app.tools.schemas import ToolDefinition, ToolParam, ok_result, error_result

logger = logging.getLogger(__name__)

TOOL_NAME = "bash"
TOOL_BASH: ToolDefinition = ToolDefinition(
    name=TOOL_NAME,
    description="Execute a bash shell command in Termux. Use for file operations, system commands, and scripts.",
    role="shell_tools",
    parameters=[
        ToolParam(
            name="command",
            description="Bash command to execute. Can be single-line or multi-line script.",
            type="string",
            required=True,
        ),
    ],
    needs_session=False,
)

TOOL_DEFINITION = {"bash": TOOL_BASH}

# Security limits
MAX_OUTPUT_SIZE = 10 * 1024  # 10KB
DEFAULT_TIMEOUT = 30  # seconds

# Dangerous commands blocklist (patterns)
DANGEROUS_PATTERNS = [
    r"\brm\s+-rf\s+/(?!\w)",  # rm -rf / (but allow rm -rf /path/to/something)
    r"\brm\s+-rf\s+~",  # rm -rf ~
    r"\bmkfs\b",  # mkfs (format disk)
    r"\bdd\s+if=/dev/zero",  # dd if=/dev/zero (disk wipe)
    r"\bdd\s+if=/dev/urandom",  # dd if=/dev/urandom
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;:",  # fork bomb
    r">\s*/dev/sd[a-z]",  # write directly to disk
    r">\s*/dev/hd[a-z]",  # write directly to disk (old)
    r"\bshutdown\b",
    r"\breboot\b",
    r"\binit\s+[06]",  # init 0/6 (shutdown/reboot)
    r"\bhalt\b",
    r"\bpoweroff\b",
]

DANGEROUS_REGEX = re.compile("|".join(DANGEROUS_PATTERNS), re.IGNORECASE)

# Cross-platform bash resolution. Termux users can still set TERMUX_BASH to pin
# /data/data/com.termux/files/usr/bin/bash; on other platforms we fall back to
# the system bash on PATH, then /bin/bash.
TERMUX_BASH = "/data/data/com.termux/files/usr/bin/bash"
BASH_EXECUTABLE = os.environ.get("TERMUX_BASH") or TERMUX_BASH
if not Path(BASH_EXECUTABLE).exists():
    resolved = shutil.which("bash")
    BASH_EXECUTABLE = resolved or "/bin/bash"

# Default working directory - use HOME env var with Termux fallback
DEFAULT_CWD = Path(os.environ.get("HOME", "")) or Path.cwd()


def _is_dangerous(command: str) -> tuple[bool, str]:
    if DANGEROUS_REGEX.search(command):
        return True, "Command matches dangerous pattern blocklist"

    return False, ""


def _truncate_output(output: str, max_size: int = MAX_OUTPUT_SIZE) -> str:
    """Truncate output if too large."""
    if len(output) <= max_size:
        return output

    truncated = output[:max_size]
    remaining = len(output) - max_size
    return f"{truncated}\n\n... ({remaining} more bytes truncated)"


async def _get_partner_name_async(user_id: str | None = None) -> str:
    try:
        from app.db import Database

        profile = await Database.get_profile(user_id) or {}
        return profile.get("partner_name", "Yuzu")
    except Exception:
        return "Yuzu"


async def execute(
    arguments: dict,
    session_id: str | None = None,
    tool_name: str = "bash",
    user_id: str | None = None,
) -> dict:
    """Execute a bash command (async).

    Args:
        arguments: {"command": "ls -la"}
        session_id: Optional session ID for context
        tool_name: Tool name for dispatch (default: "bash")

    Returns:
        {"ok": True/False, "data": {...}, "markdown": "..."}
    """
    partner_name = await _get_partner_name_async()
    command = arguments.get("command", "").strip()

    if not command:
        return error_result(
            "No command provided",
            TOOL_BASH,
            "/bash",
            partner_name,
        )

    full_command = f"/bash {command}"

    is_dangerous, reason = _is_dangerous(command)
    if is_dangerous:
        logger.warning(f"[shell] Blocked dangerous command: {command} - {reason}")
        return error_result(
            f"Command blocked: {reason}",
            TOOL_BASH,
            full_command,
            partner_name,
        )

    try:
        start_time = time.time()

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(DEFAULT_CWD),
            executable=BASH_EXECUTABLE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=DEFAULT_TIMEOUT
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            logger.warning(f"[shell] Command timed out: {command}")
            return error_result(
                f"Command timed out after {DEFAULT_TIMEOUT}s",
                TOOL_BASH,
                full_command,
                partner_name,
            )

        duration_ms = int((time.time() - start_time) * 1000)

        stdout_str = _truncate_output(stdout.decode().strip() or "(empty)")
        stderr_str = _truncate_output(stderr.decode().strip() or "(empty)")
        exit_code = process.returncode

        formatted_output = (
            f"Exit Code: {exit_code}\n"
            f"Duration: {duration_ms}ms\n\n"
            f"[STDOUT]\n{stdout_str}\n\n"
            f"[STDERR]\n{stderr_str}"
        )

        return ok_result(
            {
                "command": command,
                "exit_code": exit_code,
                "output": formatted_output,
                "duration_ms": duration_ms,
            },
            TOOL_BASH,
            full_command,
            partner_name,
        )

    except Exception as e:
        logger.error(f"[shell] Execution error: {e}")
        return error_result(
            f"Execution failed: {e}",
            TOOL_BASH,
            full_command,
            partner_name,
        )
