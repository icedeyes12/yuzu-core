#!/usr/bin/env python3
"""
Interactive memory cleanup. Shows all static facts grouped by entity,
lets you pick which IDs to delete.
Run: python3 scripts/cleanup_memories.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.db import pg_fetchall, pg_execute
from app.memory.db_memory_queries import FACT_TYPE_STATIC


def show_facts():
    rows = pg_fetchall(
        "SELECT id, content, invalid_at IS NULL as active, created_at "
        "FROM semantic_facts WHERE fact_type=%s ORDER BY id DESC",
        (FACT_TYPE_STATIC,),
    )
    print(f"\n=== Static Facts ({len(rows)} total) ===\n")
    for r in rows:
        status = "ACTIVE" if r["active"] else "DELETED"
        print(f"  [{status}] id={r['id']}: {r['content'][:80]}")
    return rows


def delete(ids):
    if not ids:
        print("No IDs to delete.")
        return
    ids = [int(x) for x in ids]
    for i in ids:
        pg_execute("UPDATE semantic_facts SET invalid_at=NOW() WHERE id=%s", (i,))
    print(f"Soft-deleted {len(ids)} facts.")


def main():
    rows = show_facts()
    active = [r for r in rows if r["active"]]

    print("\nCommands:")
    print("  delete <id>[,<id>...]  - soft-delete specific IDs")
    print("  delete all            - soft-delete ALL active facts (start fresh)")
    print("  show                  - re-show list")
    print("  quit                  - exit")

    while True:
        try:
            cmd = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not cmd:
            continue
        parts = cmd.split()
        op = parts[0]

        if op == "quit":
            break
        elif op == "show":
            rows = show_facts()
            active = [r for r in rows if r["active"]]
        elif op == "delete":
            if len(parts) < 2:
                print("Usage: delete <id>[,<id>...] or 'delete all'")
                continue
            if parts[1] == "all":
                ids = [r["id"] for r in active]
                delete(ids)
            else:
                delete(parts[1].split(","))
        else:
            print(f"Unknown command: {op}")


if __name__ == "__main__":
    main()
