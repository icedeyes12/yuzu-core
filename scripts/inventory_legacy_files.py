from __future__ import annotations

import argparse
import json
from pathlib import Path

LEGACY_DIRS = ("static/uploads", "static/generated_images")


def inventory(root: Path) -> list[dict[str, object]]:
    rows = []
    for relative in LEGACY_DIRS:
        directory = root / relative
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_symlink() or not path.is_file():
                continue
            rows.append(
                {
                    "path": str(path.relative_to(root)),
                    "size_bytes": path.stat().st_size,
                    "ownership": "unknown",
                    "action": "quarantine",
                }
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory legacy user files")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(inventory(args.root.resolve()), indent=2))


if __name__ == "__main__":
    main()
