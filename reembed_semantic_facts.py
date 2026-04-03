#!/usr/bin/env python3
"""
Re-embed NULL embeddings in semantic_facts table.
Run after: ALTER TABLE semantic_facts ADD COLUMN embedding VECTOR(4096);
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db_pg import PgSession, pg_fetchall
from app.memory.embedder import embed_text


def reembed_nulls():
    """Re-embed all rows with NULL embedding."""
    # Get rows with NULL embedding
    rows = pg_fetchall(
        "SELECT id, content FROM semantic_facts WHERE embedding IS NULL"
    )
    return rows


def update_embedding(fact_id: int, embedding: list[float]):
    """Update embedding for a fact."""
    with PgSession() as s:
        cur = s.conn.cursor()
        cur.execute(
            "UPDATE semantic_facts SET embedding = %s WHERE id = %s",
            (embedding, fact_id)
        )
        s.conn.commit()


def main():
    print("=" * 60)
    print("[RE-EMBED] Fixing NULL embeddings in semantic_facts")
    print("=" * 60)

    # Find NULL embeddings
    print("\n[1] Finding rows with NULL embedding...")
    rows = reembed_nulls()
    print(f"    Found {len(rows)} rows with NULL embedding")

    if not rows:
        print("[OK] Nothing to do!")
        return

    # Re-embed each
    success = 0
    failed = 0

    for i, row in enumerate(rows):
        fact_id = row.get("id")
        content = row.get("content", "")

        if not content:
            print(f"  [{i+1}/{len(rows)}] SKIP id={fact_id} - empty content")
            failed += 1
            continue

        print(f"  [{i+1}/{len(rows)}] Embedding id={fact_id}: {content[:50]}...")

        embedding = embed_text(content)
        if embedding is None:
            print("           FAILED to embed")
            failed += 1
            continue

        update_embedding(fact_id, embedding)
        success += 1
        print(f"           OK ({len(embedding)} dims)")

        time.sleep(0.5)  # Rate limit

    print("\n" + "=" * 60)
    print(f"[DONE] Success: {success}, Failed: {failed}")
    print("=" * 60)


if __name__ == "__main__":
    main()
