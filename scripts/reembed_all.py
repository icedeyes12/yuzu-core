#!/usr/bin/env python3
"""
Re-embed all existing memories from 4096-dim (Qwen3-Embedding-8B) 
to 1024-dim (Qwen3-Embedding-0.6B).

Usage:
    python3 scripts/reembed_all.py [--batch-size 50]

This script:
1. Fetches all rows from semantic_facts where embedding IS NOT NULL
2. Re-embeds each content using the new 1024-dim model
3. Updates the embedding column in batches
4. Reports progress and final count
"""

import argparse
import sys
import os

# Add parent dir to path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.memory.embedder import embed_texts, EMBEDDING_DIM
from app.db_pg import PgSession, vector_sql
from psycopg2.extras import Json


def get_total_count():
    with PgSession() as s:
        return s.fetchone(
            "SELECT COUNT(*) AS cnt FROM semantic_facts WHERE embedding IS NOT NULL"
        )["cnt"]


def fetch_batch(offset, batch_size):
    with PgSession() as s:
        return s.fetchall(
            "SELECT id, content FROM semantic_facts "
            "WHERE embedding IS NOT NULL "
            "ORDER BY id LIMIT %s OFFSET %s",
            (batch_size, offset),
        )


def update_embeddings(rows):
    """rows: list of (id, new_embedding_list)"""
    if not rows:
        return 0
    with PgSession() as s:
        for row_id, embedding in rows:
            s.execute(
                "UPDATE semantic_facts SET embedding=%s WHERE id=%s",
                (vector_sql(embedding), row_id),
            )
    return len(rows)


def get_embedding_dimensions(row_id):
    with PgSession() as s:
        row = s.fetchone(
            "SELECT vector_dims(embedding) AS dims FROM semantic_facts WHERE id=%s",
            (row_id,),
        )
        return row["dims"] if row else None


def main():
    parser = argparse.ArgumentParser(description="Re-embed all memories to 1024-dim")
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()

    print(f"[reembed] Target dimension: {EMBEDDING_DIM}")
    total = get_total_count()
    print(f"[reembed] Total rows to re-embed: {total}")

    if total == 0:
        print("[reembed] Nothing to do.")
        return

    offset = 0
    updated = 0
    errors = 0

    while offset < total:
        batch = fetch_batch(offset, args.batch_size)
        if not batch:
            break

        texts = [row["content"] for row in batch]
        ids = [row["id"] for row in batch]

        try:
            embeddings = embed_texts(texts)
        except Exception as e:
            print(f"[reembed] Embedding API failed: {e}")
            errors += len(batch)
            offset += args.batch_size
            continue

        if not embeddings or len(embeddings) != len(texts):
            print(f"[reembed] Embedding count mismatch: expected {len(texts)}, got {len(embeddings) if embeddings else 0}")
            errors += len(batch)
            offset += args.batch_size
            continue

        # Validate dimensions
        for i, emb in enumerate(embeddings):
            if len(emb) != EMBEDDING_DIM:
                print(f"[reembed] WARNING: row id={ids[i]} got dim={len(emb)}, expected {EMBEDDING_DIM} — skipping")
                errors += 1
                continue

        # Pair and update
        pairs = list(zip(ids, embeddings))
        count = update_embeddings(pairs)
        updated += count
        print(f"[reembed] Updated {count}/{len(batch)} rows (total: {updated}/{total})")

        offset += args.batch_size

    print(f"\n[reembed] Done. Updated: {updated}, Errors: {errors}")

    # Spot-check: verify a few rows
    print("\n[reembed] Spot-checking dimensions...")
    with PgSession() as s:
        sample = s.fetchall(
            "SELECT id, vector_dims(embedding) AS dims FROM semantic_facts "
            "WHERE embedding IS NOT NULL ORDER BY id DESC LIMIT 5"
        )
        for row in sample:
            print(f"  id={row['id']}  dims={row['dims']}")


if __name__ == "__main__":
    main()
