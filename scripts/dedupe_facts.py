#!/usr/bin/env python3
"""Remove near-duplicate facts keeping the newest (highest id)."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.db_pg import pg_fetchall, pg_execute

def dedupe(fact_type):
    print(f"\n=== {fact_type} ===")
    rows = pg_fetchall(
        "SELECT id, content FROM semantic_facts WHERE fact_type=%s AND invalid_at IS NULL",
        (fact_type,)
    )
    print(f"  Total active: {len(rows)}")
    
    seen = {}  # content -> best_id
    to_delete = []
    
    for row in rows:
        c = row['content']
        if c in seen:
            # Keep the one with higher id (newer)
            if row['id'] > seen[c]:
                to_delete.append(seen[c])
                seen[c] = row['id']
            else:
                to_delete.append(row['id'])
        else:
            seen[c] = row['id']
    
    print(f"  Duplicates to remove: {len(to_delete)}")
    for did in to_delete:
        pg_execute("UPDATE semantic_facts SET invalid_at=NOW() WHERE id=%s", (did,))
    print(f"  Soft-deleted {len(to_delete)}")

dedupe('static')
dedupe('dynamic')
print("\nDone.")
