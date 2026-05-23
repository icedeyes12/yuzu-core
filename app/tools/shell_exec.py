# FILE: app/tools/shell_exec.py
# DESCRIPTION: Shell command execution for Termux environment.
#              Execute bash commands with timeout, security controls, and
#              optional persistent session support for orchestration.

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

# Default working directory - use HOME env var with Termux fallback
DEFAULT_CWD = os.environ.get("HOME", "/data/data/com.termux/files/home")


# --------------------------------------------------------------------
# Persistent Shell Session (for orchestration cycles)
# --------------------------------------------------------------------

# Module-level persistent session (reset between user turns)
_persistent_process: subprocess.Popen | None = None
_session_cwd: str = DEFAULT_CWD


def _get_persistent_session() -> subprocess.Popen:
    """Get or create a persistent bash process for the current orchestration cycle."""
    global _persistent_process

    if _persistent_process is None or _persistent_process.poll() is not None:
        # Create new persistent bash process
        _persistent_process = subprocess.Popen(
            ["bash", "--noediting", "-i"],  # interactive for session persistence
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=_session_cwd,
        )
        logger.info(
            "created persistent shell session (pid=%d)", _persistent_process.pid
        )

    return _persistent_process


def _execute_in_session(
    command: str, timeout: float = DEFAULT_TIMEOUT
) -> tuple[int, str, str]:
    """Execute a command in the persistent session.

    Returns (exit_code, stdout, stderr).
    """
    global _session_cwd

    proc = _get_persistent_session()

    try:
        # Write command with echo markers for parsing output
        marker_start = "__YUZU_OUTPUT_START__"
        marker_end = "__YUZU_OUTPUT_END__"
        exit_code_var = "__YUZU_EXIT_CODE__"

        full_command = f'echo "{marker_start}"; {command}; {exit_code_var}=$?; echo "{marker_end}"; echo "{exit_code_var}:${{{exit_code_var}}}"; cd "$PWD" > /dev/null 2>&1\n'

        proc.stdin.write(full_command)
        proc.stdin.flush()

        # Read output with timeout
        import threading

        output_buffer: list[str] = []
        error_buffer: list[str] = []

        def read_output():
            try:
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    output_buffer.append(line)
                    if marker_end in line:
                        break
            except Exception:
                pass

        def read_error():
            try:
                while True:
                    line = proc.stderr.readline()
                    if not line:
                        break
                    error_buffer.append(line)
            except Exception:
                pass

        output_thread = threading.Thread(target=read_output)
        error_thread = threading.Thread(target=read_error)
        output_thread.daemon = True
        error_thread.daemon = True

        output_thread.start()
        error_thread.start()

        output_thread.join(timeout=timeout)
        error_thread.join(timeout=0.5)

        # Parse output
        full_output = "".join(output_buffer)
        full_error = "".join(error_buffer)

        # Extract content between markers
        exit_code = 0
        stdout = full_output

        if marker_start in full_output and marker_end in full_output:
            start_idx = full_output.index(marker_start) + len(marker_start)
            end_idx = full_output.index(marker_end)
            stdout = full_output[start_idx:end_idx].strip()

            # Try to extract exit code
            exit_code_line = [
                line for line in full_output.split("\n") if f"{exit_code_var}:" in line
            ]
            if exit_code_line:
                try:
                    exit_code = int(exit_code_line[0].split(":")[-1].strip())
                except (ValueError, IndexError):
                    pass

        # Update session cwd if cd was successful
        # This is a best-effort; the shell's actual cwd is what matters
        if command.strip().startswith("cd ") and exit_code == 0:
            try:
                new_dir = command.strip()[3:].strip()
                if new_dir:
                    _session_cwd = os.path.normpath(os.path.join(_session_cwd, new_dir))
            except Exception:
                pass

        return exit_code, stdout, full_error

    except Exception as e:
        logger.error("session execution error: %s", e)
        return 1, "", str(e)


def reset_session():
    """Reset the persistent shell session.

    Should be called after each orchestration cycle completes.
    """
    global _persistent_process, _session_cwd

    if _persistent_process is not None:
        try:
            _persistent_process.terminate()
            _persistent_process.wait(timeout=2)
        except Exception:
            try:
                _persistent_process.kill()
            except Exception:
                pass
        _persistent_process = None

    _session_cwd = DEFAULT_CWD
    logger.info("shell session reset")


# --------------------------------------------------------------------
# Helper Functions
# --------------------------------------------------------------------


def _is_dangerous(command: str) -> tuple[bool, str]:
    """Check if command is potentially dangerous.

    Returns (is_dangerous, reason).
    """
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
        from app.db import get_profile

        profile = get_profile() or {}
        return profile.get("partner_name", "Yuzu")
    except Exception:
        return "Yuzu"


# --------------------------------------------------------------------
# Execute Function
# --------------------------------------------------------------------


def execute(
    arguments: dict, session_id: int | None = None, tool_name: str = "bash"
) -> dict:
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

    # Execute command (non-persistent for now, persistent session can be enabled later)
    # Persistent sessions have complexity trade-offs; keeping simple for now
    try:
        start_time = time.time()
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT,
            cwd=DEFAULT_CWD,
            executable="/data/data/com.termux/files/usr/bin/bash" # Sesuaikan path bash Termux
        )
        duration_ms = int((time.time() - start_time) * 1000)

        # Truncate if needed
        stdout = _truncate_output(result.stdout or "")
        stderr = _truncate_output(result.stderr or "")
        exit_code = result.returncode

        # Format terisolasi untuk Yuzuki
        stdout_str = stdout.strip() if stdout.strip() else "(empty)"
        stderr_str = stderr.strip() if stderr.strip() else "(empty)"

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
