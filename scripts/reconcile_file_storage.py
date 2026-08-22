from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from app.db.connection import pg_fetchall_async

SQL_FILE_ROWS_FOR_RECONCILIATION = """
SELECT id, owner_id, storage_key, size_bytes, status, created_at, deleted_at
FROM file_objects
ORDER BY owner_id, id
"""


async def build_report(storage_root: Path) -> dict[str, list[dict[str, object]]]:
    rows = await pg_fetchall_async(SQL_FILE_ROWS_FOR_RECONCILIATION)
    referenced = {str(row["storage_key"]) for row in rows}
    missing = []
    pending = []
    deleted_present = []
    for row in rows:
        path = storage_root / str(row["storage_key"])
        item = {
            "id": str(row["id"]),
            "owner_id": str(row["owner_id"]),
            "storage_key": str(row["storage_key"]),
            "size_bytes": int(row["size_bytes"]),
        }
        if row["deleted_at"] is not None and path.is_file() and not path.is_symlink():
            deleted_present.append(item)
        elif row["deleted_at"] is None and (
            not path.is_file() or path.is_symlink()
        ):
            missing.append(item)
        if row["deleted_at"] is None and row["status"] == "pending":
            pending.append(
                {
                    **item,
                    "created_at": str(row["created_at"]),
                    "physical_exists": path.is_file() and not path.is_symlink(),
                }
            )

    orphan = []
    users_root = storage_root / "users"
    if users_root.exists():
        for path in sorted(users_root.rglob("*")):
            if path.is_file() and not path.is_symlink():
                key = path.relative_to(storage_root).as_posix()
                if key not in referenced:
                    orphan.append(
                        {"storage_key": key, "size_bytes": path.stat().st_size}
                    )
    return {
        "pending": pending,
        "missing": missing,
        "deleted_present": deleted_present,
        "orphan": orphan,
    }


async def async_main() -> None:
    parser = argparse.ArgumentParser(description="Report file metadata/storage drift")
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path(os.environ.get("YUZU_STORAGE_ROOT", "data")),
    )
    args = parser.parse_args()
    print(json.dumps(await build_report(args.storage_root.resolve()), indent=2))


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
