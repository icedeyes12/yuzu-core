# FILE: app/tools/shell_exec.py
# DESCRIPTION: Shell command execution for Termux environment.
#              Execute bash commands with timeout and security controls.

from __future__ import annotations

import os
import re
import subprocess
import logging
import time

from app.tools.schemas import ToolDefinition, ToolParam, ok_result, error_result

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------

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
    is_terminal=False,
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


# --------------------------------------------------------------------
# Helper Functions
# --------------------------------------------------------------------


def _is_dangerous(command: str) -> tuple[bool, str]:
    """Check if command is potentially dangerous.

    Returns (is_dangerous, reason).
    """
    # Check against patterns
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


def _get_partner_name() -> str:
    """Get partner name from profile."""
    try:
        from app.database import get_profile

        profile = get_profile() or {}
        return profile.get("partner_name", "Yuzu")
    except Exception:
        return "Yuzu"


# --------------------------------------------------------------------
# Execute Function
# --------------------------------------------------------------------


def execute(arguments: dict, session_id: int | None = None, tool_name: str = "bash") -> dict:
    """Execute a bash command.

    Args:
        arguments: {"command": "ls -la"}
        session_id: Optional session ID for context
        tool_name: Tool name for dispatch (default: "bash")

    Returns:
        {"ok": True/False, "data": {...}, "markdown": "..."}
    """
    partner_name = _get_partner_name()
    command = arguments.get("command", "").strip()

    if not command:
        return error_result(
            "No command provided",
            TOOL_BASH,
            "/bash",
            partner_name,
        )

    full_command = f"/bash {command}"

    # Security check
    is_dangerous, reason = _is_dangerous(command)
    if is_dangerous:
        logger.warning(f"[shell] Blocked dangerous command: {command} - {reason}")
        return error_result(
            f"Command blocked: {reason}",
            TOOL_BASH,
            full_command,
            partner_name,
        )

    # Execute command
    try:
        start_time = time.time()
        
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT,
            cwd=os.path.expanduser("~/workspace"),  # Run in workspace
        )

        duration_ms = int((time.time() - start_time) * 1000)

        stdout = result.stdout or ""
        stderr = result.stderr or ""
        exit_code = result.returncode

        # Truncate if needed
        stdout = _truncate_output(stdout)
        stderr = _truncate_output(stderr)

        # Build output
        output_parts = []
        if stdout:
            output_parts.append(stdout)
        if stderr:
            output_parts.append(f"[stderr]\n{stderr}")

        combined_output = "\n".join(output_parts) if output_parts else "(no output)"

        # Success result (even if exit_code != 0, we executed successfully)
        return ok_result(
            {
                "command": command,
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "output": combined_output,
                "duration_ms": duration_ms,
            },
            TOOL_BASH,
            full_command,
            partner_name,
        )

    except subprocess.TimeoutExpired:
        logger.warning(f"[shell] Command timed out: {command}")
        return error_result(
            f"Command timed out after {DEFAULT_TIMEOUT}s",
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
