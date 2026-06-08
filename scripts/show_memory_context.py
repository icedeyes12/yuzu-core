#!/usr/bin/env python3
"""Interactive memory context viewer — see what's fed to LLM system prompt."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.memory.retrieval import retrieve_memory, format_memory


def main():
    # No default host - rely on environment or app's db_pg config
    # os.environ.setdefault("PGHOST", os.getenv("PGHOST", ""))

    print("=" * 60)
    print("MEMORY CONTEXT VIEWER")
    print("=" * 60)
    print("This shows exactly what goes into {memory_context}\n")

    session_id = int(
        os.getenv("TEST_SESSION_ID") or input("Session ID [1]: ").strip() or "1"
    )
    query = input("Query (optional, press Enter to skip): ").strip() or None

    print(f"\n[Fetching memories for session_id={session_id}...]\n")

    try:
        bundle = retrieve_memory(session_id, query=query)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    ctx = format_memory(bundle)

    print("-" * 60)
    print("RAW bundle (unformatted):")
    print("-" * 60)
    print(f"  static facts    : {len(bundle.get('static', []))} items")
    for m in bundle.get("static", []):
        print(f"    [{m.get('category', '?')}] {m.get('content', '')[:80]}")
    print(f"  dynamic facts   : {len(bundle.get('dynamic', []))} items")
    for m in bundle.get("dynamic", []):
        print(f"    {m.get('content', '')[:80]}")
    print(f"  temporal msgs   : {len(bundle.get('temporal_messages', []))} items")

    print()
    print("-" * 60)
    print("FORMATTED context (injected into system prompt):")
    print("-" * 60)
    if ctx:
        print(ctx)
    else:
        print("  (empty)")

    print()
    print("=" * 60)
    print(f"Characters: {len(ctx)}")


if __name__ == "__main__":
    main()
