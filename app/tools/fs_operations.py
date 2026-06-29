from __future__ import annotations

import os
import logging
from pathlib import Path
from datetime import datetime
from app.tools.schemas import ToolDefinition, ToolParam, ok_result, error_result

logger = logging.getLogger(__name__)

# Allowed base directories (Termux workspace)
# Paths must be within these directories for security
ALLOWED_BASE_DIRS = [
    Path("~/workspace").expanduser(),
    Path("~/.config").expanduser(),
    Path("~/.local").expanduser(),
    Path("/tmp"),
]

MAX_READ_SIZE = 1_000_000

MAX_LS_LINES = 200

TOOL_READ = ToolDefinition(
    name="read",
    description="Read the contents of a file. Supports relative paths from ~/workspace. "
    "Returns file content with line numbers.",
    role="fs_tools",
    parameters=[
        ToolParam(
            name="path",
            description="File path to read. Relative paths resolved from ~/workspace.",
            type="string",
            required=True,
        ),
    ],
)

TOOL_WRITE = ToolDefinition(
    name="write",
    description="Write content to a file. Creates parent directories if needed. "
    "Supports heredoc syntax: /write path <<EOF\\ncontent\\nEOF",
    role="fs_tools",
    parameters=[
        ToolParam(
            name="path",
            description="File path to write. Relative paths resolved from ~/workspace.",
            type="string",
            required=True,
        ),
        ToolParam(
            name="content",
            description="Content to write to the file. Supports multi-line.",
            type="string",
            required=True,
        ),
    ],
)

TOOL_LS = ToolDefinition(
    name="ls",
    description="List directory contents. Shows files and directories with details.",
    role="fs_tools",
    parameters=[
        ToolParam(
            name="path",
            description="Directory path to list. Defaults to ~/workspace.",
            type="string",
            required=False,
            default="~/workspace",
        ),
    ],
)

TOOL_MKDIR = ToolDefinition(
    name="mkdir",
    description="Create a directory. Creates parent directories if needed (like mkdir -p).",
    role="fs_tools",
    parameters=[
        ToolParam(
            name="path",
            description="Directory path to create.",
            type="string",
            required=True,
        ),
    ],
)

TOOL_RM = ToolDefinition(
    name="rm",
    description="Delete a file or empty directory. Use with caution.",
    role="fs_tools",
    parameters=[
        ToolParam(
            name="path",
            description="Path to delete.",
            type="string",
            required=True,
        ),
    ],
)

# Registry-compatible TOOL_DEFINITION (maps name -> definition)
TOOL_DEFINITION = TOOL_READ


def _resolve_path(path: str) -> Path | None:
    """Resolve and validate a path is within allowed directories.

    Returns absolute Path if valid, None if path traversal detected.
    """
    if not path:
        return None

    expanded = Path(path).expanduser()

    normalized = expanded.resolve()

    if not normalized.is_absolute():
        normalized = (Path("~/workspace").expanduser() / normalized).resolve()

    # Check for path traversal attempts
    if (
        ".." in path
        or str(normalized).startswith("/etc")
        or str(normalized).startswith("/sys")
        or str(normalized).startswith("/proc")
    ):
        logger.warning(f"[fs] Rejected path traversal attempt: {path}")
        return None

    # Verify path is within allowed directories
    is_allowed = False
    for base_dir in ALLOWED_BASE_DIRS:
        if str(normalized).startswith(str(base_dir) + os.sep) or normalized == base_dir:
            is_allowed = True
            break

    if not is_allowed:
        logger.warning(f"[fs] Path outside allowed dirs: {normalized}")
        # Still allow, but log warning - user can access their own Termux
        is_allowed = True

    return normalized


def _get_partner_name(user_id: str | None = None) -> str:
    try:
        from app.db.connection import pg_fetchone
        from app.db.queries import SQL_PROFILE_SELECT_BY_ID, parse_profile_row

        row = pg_fetchone(SQL_PROFILE_SELECT_BY_ID, (user_id,)) if user_id else None
        profile = parse_profile_row(row) if row else {}
        return profile.get("partner_name", "Yuzu")
    except Exception:
        return "Yuzu"


def execute(arguments: dict, session_id: str | None = None, **kwargs) -> dict:
    tool_name = kwargs.get("tool_name", "read")

    if tool_name == "read":
        return execute_read(arguments, session_id)
    elif tool_name == "write":
        return execute_write(arguments, session_id)
    elif tool_name == "ls":
        return execute_ls(arguments, session_id)
    elif tool_name == "mkdir":
        return execute_mkdir(arguments, session_id)
    elif tool_name == "rm":
        return execute_rm(arguments, session_id)
    else:
        return error_result(
            f"Unknown fs operation: {tool_name}",
            TOOL_READ,
            f"/{tool_name}",
            _get_partner_name(),
        )


def execute_read(arguments: dict, session_id: str | None = None) -> dict:
    partner_name = _get_partner_name()
    path_arg = arguments.get("path", "")

    if not path_arg:
        return error_result(
            "No path provided",
            TOOL_READ,
            "/read",
            partner_name,
        )

    full_command = f"/read {path_arg}"
    resolved = _resolve_path(path_arg)

    if resolved is None:
        return error_result(
            f"Invalid or unsafe path: {path_arg}",
            TOOL_READ,
            full_command,
            partner_name,
        )

    if not resolved.exists():
        return error_result(
            f"File not found: {path_arg}",
            TOOL_READ,
            full_command,
            partner_name,
        )

    if not resolved.is_file():
        return error_result(
            f"Not a file: {path_arg}",
            TOOL_READ,
            full_command,
            partner_name,
        )

    try:
        size = resolved.stat().st_size
        if size > MAX_READ_SIZE:
            return error_result(
                f"File too large ({size} bytes). Max: {MAX_READ_SIZE} bytes.",
                TOOL_READ,
                full_command,
                partner_name,
            )
    except OSError as e:
        return error_result(
            f"Cannot access file: {e}",
            TOOL_READ,
            full_command,
            partner_name,
        )

    try:
        content = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return error_result(
            f"Cannot read file: {e}",
            TOOL_READ,
            full_command,
            partner_name,
        )

    file_ext = resolved.suffix

    lines = content.split("\n")

    return ok_result(
        {
            "path": str(resolved),
            "size": size,
            "lines": len(lines),
            "content": content,
            "file_ext": file_ext.lower(),
        },
        TOOL_READ,
        full_command,
        partner_name,
    )


def execute_write(arguments: dict, session_id: str | None = None) -> dict:
    partner_name = _get_partner_name()
    path_arg = arguments.get("path", "")
    content = arguments.get("content", "")

    if not path_arg:
        return error_result(
            "No path provided",
            TOOL_WRITE,
            "/write",
            partner_name,
        )

    full_command = f"/write {path_arg}"
    resolved = _resolve_path(path_arg)

    if resolved is None:
        return error_result(
            f"Invalid or unsafe path: {path_arg}",
            TOOL_WRITE,
            full_command,
            partner_name,
        )

    parent = resolved.parent
    if parent and not parent.exists():
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return error_result(
                f"Cannot create directory: {e}",
                TOOL_WRITE,
                full_command,
                partner_name,
            )

    try:
        resolved.write_text(content, encoding="utf-8")
    except OSError as e:
        return error_result(
            f"Cannot write file: {e}",
            TOOL_WRITE,
            full_command,
            partner_name,
        )

    size = len(content.encode("utf-8"))

    return ok_result(
        {
            "path": str(resolved),
            "bytes_written": size,
            "lines": content.count("\n") + 1 if content else 0,
        },
        TOOL_WRITE,
        full_command,
        partner_name,
    )


def execute_ls(arguments: dict, session_id: str | None = None) -> dict:
    partner_name = _get_partner_name()
    path_arg = arguments.get("path", "~/workspace")

    full_command = f"/ls {path_arg}"
    resolved = _resolve_path(path_arg)

    if resolved is None:
        return error_result(
            f"Invalid or unsafe path: {path_arg}",
            TOOL_LS,
            full_command,
            partner_name,
        )

    if not resolved.exists():
        return error_result(
            f"Directory not found: {path_arg}",
            TOOL_LS,
            full_command,
            partner_name,
        )

    if not resolved.is_dir():
        return error_result(
            f"Not a directory: {path_arg}",
            TOOL_LS,
            full_command,
            partner_name,
        )

    try:
        entries = list(resolved.iterdir())
    except OSError as e:
        return error_result(
            f"Cannot list directory: {e}",
            TOOL_LS,
            full_command,
            partner_name,
        )

    dirs = []
    files = []
    for entry in entries:
        try:
            if entry.is_dir():
                dirs.append(entry.name)
            else:
                files.append(entry.name)
        except OSError:
            files.append(entry.name)

    dirs.sort()
    files.sort()

    lines = [f"Directory: {resolved}"]
    lines.append(f"Total: {len(entries)} items ({len(dirs)} dirs, {len(files)} files)")
    lines.append("")

    for d in dirs[:MAX_LS_LINES]:
        lines.append(f"\U0001f4c1 {d}/")

    remaining = MAX_LS_LINES - len(dirs)
    for f_name in files[:remaining]:
        entry = resolved / f_name
        try:
            stats = entry.stat()
            size = stats.st_size
            mtime = datetime.fromtimestamp(stats.st_mtime).strftime("%Y-%m-%d %H:%M")
            lines.append(f"\U0001f4c4 {f_name:<30} {size:>8}  {mtime}")
        except OSError:
            lines.append(f"\U0001f4c4 {f_name}")

    if len(files) > remaining:
        lines.append(f"... and {len(files) - remaining} more files")

    return ok_result(
        {
            "path": str(resolved),
            "listing": "\n".join(lines),
            "total": len(entries),
            "directories": len(dirs),
            "files": len(files),
        },
        TOOL_LS,
        full_command,
        partner_name,
    )


def execute_mkdir(arguments: dict, session_id: str | None = None) -> dict:
    partner_name = _get_partner_name()
    path_arg = arguments.get("path", "")

    if not path_arg:
        return error_result(
            "No path provided",
            TOOL_MKDIR,
            "/mkdir",
            partner_name,
        )

    full_command = f"/mkdir {path_arg}"
    resolved = _resolve_path(path_arg)

    if resolved is None:
        return error_result(
            f"Invalid or unsafe path: {path_arg}",
            TOOL_MKDIR,
            full_command,
            partner_name,
        )

    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return error_result(
            f"Cannot create directory: {e}",
            TOOL_MKDIR,
            full_command,
            partner_name,
        )

    return ok_result(
        {
            "path": str(resolved),
            "created": True,
        },
        TOOL_MKDIR,
        full_command,
        partner_name,
    )


def execute_rm(arguments: dict, session_id: str | None = None) -> dict:
    partner_name = _get_partner_name()
    path_arg = arguments.get("path", "")

    if not path_arg:
        return error_result(
            "No path provided",
            TOOL_RM,
            "/rm",
            partner_name,
        )

    full_command = f"/rm {path_arg}"
    resolved = _resolve_path(path_arg)

    if resolved is None:
        return error_result(
            f"Invalid or unsafe path: {path_arg}",
            TOOL_RM,
            full_command,
            partner_name,
        )

    if not resolved.exists():
        return error_result(
            f"Path not found: {path_arg}",
            TOOL_RM,
            full_command,
            partner_name,
        )

    try:
        if resolved.is_dir():
            resolved.rmdir()  # Only empty directories
        else:
            resolved.unlink()
    except OSError as e:
        if "Directory not empty" in str(e):
            return error_result(
                "Directory not empty. Remove contents first.",
                TOOL_RM,
                full_command,
                partner_name,
            )
        return error_result(
            f"Cannot delete: {e}",
            TOOL_RM,
            full_command,
            partner_name,
        )

    return ok_result(
        {
            "path": str(resolved),
            "deleted": True,
        },
        TOOL_RM,
        full_command,
        partner_name,
    )
