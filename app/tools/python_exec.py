
from __future__ import annotations

import subprocess
import tempfile
import os
import re
import time

from app.logging_config import get_logger
from app.tools.schemas import ToolDefinition, ToolParam, error_result, ok_result

log = get_logger(__name__)

# --------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------

TOOL_NAME = "python"
TOOL_PYTHON = "python"

# Security limits
MAX_OUTPUT_SIZE = 50000  # 50KB max output
MAX_CODE_SIZE = 100000  # 100KB max code
TIMEOUT_SECONDS = 60  # 60 second timeout

# Blocked imports (dangerous operations)
BLOCKED_IMPORTS = {
    "os.system",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.run",
    "subprocess.check_output",
    "eval",
    "exec",
    "compile",
    "__import__",
    "importlib",
    "pickle.loads",
    "marshal.loads",
    "shutil.rmtree",
}

# Default working directory - use HOME env var with Termux fallback
DEFAULT_CWD = os.environ.get("HOME", "/data/data/com.termux/files/home")

# --------------------------------------------------------------------
# Tool Definition
# --------------------------------------------------------------------

TOOL_DEFINITION = ToolDefinition(
    name=TOOL_NAME,
    description="Execute Python code in Termux environment. Use for calculations, data processing, or quick scripts. Output limited to 50KB, timeout 60 seconds.",
    role="python_tools",
    parameters=[
        ToolParam(
            name="code",
            description="Python code to execute. Can be single line or multi-line code block.",
            type="string",
            required=True,
        ),
    ],
    needs_session=False,
)


# --------------------------------------------------------------------
# Helper Functions
# --------------------------------------------------------------------


def _extract_code_block(text: str) -> str:
    """Extract code from fenced code block if present.

    Supports:
    - ```python\ncode\n```
    - ```\ncode\n```
    - plain code

    IMPORTANT: Preserves leading whitespace (indentation) for Python code.
    Only strips trailing whitespace from the final result.
    """
    fenced_match = re.match(r"```(?:python)?\s*\n(.*?)\n```", text.strip(), re.DOTALL)
    if fenced_match:
        code = fenced_match.group(1)
        lines = code.split("\n")
        lines = [line.rstrip() for line in lines]
        return "\n".join(lines).rstrip()

    # Check for single backtick
    if text.strip().startswith("`") and text.strip().endswith("`"):
        return text.strip()[1:-1].rstrip()

    return text.rstrip()


def _check_security(code: str) -> tuple[bool, str]:
    if len(code) > MAX_CODE_SIZE:
        return False, f"Code too large ({len(code)} chars). Maximum: {MAX_CODE_SIZE}"

    # Check for blocked imports/operations
    code_lower = code.lower()
    for blocked in BLOCKED_IMPORTS:
        if blocked.lower() in code_lower:
            return False, f"Blocked operation detected: {blocked}"

    if "open(" in code and ("'w'" in code or '"w"' in code):
        log.warning("[python] File write operation detected")

    return True, ""


def _execute_python(code: str) -> tuple[bool, str, str, int]:
    start_time = time.time()
    duration_ms = 0

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        temp_path = f.name

    try:
        result = subprocess.run(
            ["python3", temp_path],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            cwd=DEFAULT_CWD,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )

        duration_ms = int((time.time() - start_time) * 1000)

        stdout = result.stdout
        stderr = result.stderr

        if len(stdout) > MAX_OUTPUT_SIZE:
            stdout = (
                stdout[:MAX_OUTPUT_SIZE]
                + f"\n... [truncated, {len(result.stdout)} total chars]"
            )

        if len(stderr) > MAX_OUTPUT_SIZE:
            stderr = (
                stderr[:MAX_OUTPUT_SIZE]
                + f"\n... [truncated, {len(result.stderr)} total chars]"
            )

        success = result.returncode == 0
        return success, stdout, stderr, duration_ms

    except subprocess.TimeoutExpired:
        return (
            False,
            "",
            f"Timeout: code execution exceeded {TIMEOUT_SECONDS} seconds",
            duration_ms,
        )

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        return False, "", str(e), duration_ms

    finally:
        try:
            os.unlink(temp_path)
        except Exception:
            pass


def execute(
    arguments: dict,
    session_id: str | None = None,
    tool_name: str = TOOL_NAME,
    user_id: str | None = None,
) -> dict:
    code_raw = arguments.get("code", "").strip()
    full_command = f"/python {code_raw[:50]}{'...' if len(code_raw) > 50 else ''}"

    if not code_raw:
        return error_result(
            "No code provided",
            TOOL_DEFINITION,
            full_command,
            _get_partner_name(),
        )

    code = _extract_code_block(code_raw)

    is_safe, error_msg = _check_security(code)
    if not is_safe:
        log.info("[python] Security check failed: %s", error_msg)
        return error_result(
            error_msg,
            TOOL_DEFINITION,
            full_command,
            _get_partner_name(),
        )

    success, stdout, stderr, duration_ms = _execute_python(code)

    # Mapping success ke Exit Code standar
    exit_code = 0 if success else 1

    stdout_str = stdout.strip() if stdout and stdout.strip() else "(empty)"
    stderr_str = stderr.strip() if stderr and stderr.strip() else "(empty)"

    formatted_output = (
        f"Exit Code: {exit_code}\n"
        f"Duration: {duration_ms}ms\n\n"
        f"[STDOUT]\n{stdout_str}\n\n"
        f"[STDERR]\n{stderr_str}"
    )

    if success:
        return ok_result(
            {
                "code_snippet": code[:100] + "..." if len(code) > 100 else code,
                "output": formatted_output,
            },
            TOOL_DEFINITION,
            full_command,
            _get_partner_name(),
        )
    else:
        # Meskipun error, kita tetap kirim format yang sama agar Yuzuki bisa baca STDOUT & STDERR terpisah
        return error_result(
            formatted_output,
            TOOL_DEFINITION,
            full_command,
            _get_partner_name(),
        )


def _get_partner_name() -> str:
    return "Yuzu"
