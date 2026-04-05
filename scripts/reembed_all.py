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

import sys
import os

# Add parent dir to path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.memory.embedder import embed_texts, EMBEDDING_DIM
from app.db_pg import PgSession


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
            # Vector literal is just comma-separated floats — no injection risk
            vec_literal = "[" + ",".join(str(x) for x in embedding) + "]"
            s.execute(
                f"UPDATE semantic_facts SET embedding='{vec_literal}'::vector WHERE id={row_id}",
                None,
            )
    return len(rows)


def migrate_column():
    """Migrate embedding column from 4096-dim to 1024-dim via new column rename."""

    with PgSession() as s:
        # 1. Verify current column dimension
        row = s.fetchone(
            "SELECT vector_dims(embedding) AS dims FROM semantic_facts LIMIT 1"
        )
        current_dim = row["dims"] if row else None
        print(f"[migrate] Current embedding column dimension: {current_dim}")

        if current_dim == EMBEDDING_DIM:
            print(f"[migrate] Column already at target dim {EMBEDDING_DIM}, nothing to do.")
            return

        new_col = "embedding_1024"

        # 2. Add new column with correct dimension
        print(f"[migrate] Adding new column {new_col} as VECTOR({EMBEDDING_DIM})...")
        s.execute(f"ALTER TABLE semantic_facts ADD COLUMN {new_col} vector({EMBEDDING_DIM})")

        # 3. Commit so the column exists before re-embed script uses it
        s.conn.commit()
        print("[migrate] New column added. Run reembed script, then run migrate_column(confirm=True).")

        # 4. Informational: count rows
        count_row = s.fetchone(
            "SELECT COUNT(*) AS cnt FROM semantic_facts WHERE embedding IS NOT NULL"
        )
        print(f"[migrate] {count_row['cnt']} rows still need re-embedding.")


def finalize_migration():
    """Drop old 4096 embedding column and rename new one. Run AFTER reembed completes."""

    with PgSession() as s:
        # Verify all rows have been re-embedded
        count_row = s.fetchone(
            "SELECT COUNT(*) AS cnt FROM semantic_facts WHERE embedding IS NULL AND embedding_1024 IS NOT NULL"
        )
        if count_row and count_row["cnt"] > 0:
            print(f"[migrate] ERROR: {count_row['cnt']} rows still have NULL in new column. Run reembed first.")
            return

        row = s.fetchone(
            "SELECT vector_dims(embedding_1024) AS dims FROM semantic_facts LIMIT 1"
        )
        if not row:
            print("[migrate] ERROR: new column is empty or doesn't exist.")
            return

        print(f"[migrate] New column dimension: {row['dims']} — looks good.")

        # 5. Drop old column
        print("[migrate] Dropping old embedding column...")
        s.execute("ALTER TABLE semantic_facts DROP COLUMN embedding")

        # 6. Rename new column to original name
        print("[migrate] Renaming embedding_1024 → embedding...")
        s.execute("ALTER TABLE semantic_facts RENAME COLUMN embedding_1024 TO embedding")

        s.conn.commit()
        print("[migrate] Done. Column is now VECTOR(1024).")


def reembed_into_new_column(batch_size=50):
    """Re-embed ALL memories into the new 1024-dim column (embedding_1024).
    
    Safe: fetches from original embedding column, writes to new column.
    If the new column doesn't exist yet, aborts.
    """
    new_col = "embedding_1024"
    
    # Verify new column exists via information_schema
    with PgSession() as s:
        col_check = s.fetchone(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='semantic_facts' AND column_name=%s",
            (new_col,)
        )
        if col_check is None:
            print(f"[reembed] Column {new_col} not found. Run --migrate first.")
            return

    total = get_total_count()
    print(f"[reembed] Total rows to re-embed: {total}")
    if total == 0:
        print("[reembed] Nothing to do.")
        return

    offset = 0
    updated = 0
    errors = 0

    while offset < total:
        batch = fetch_batch(offset, batch_size)
        if not batch:
            break

        texts = [row["content"] for row in batch]
        ids = [row["id"] for row in batch]

        try:
            embeddings = embed_texts(texts)
        except Exception as e:
            print(f"[reembed] Embedding API failed: {e}")
            errors += len(batch)
            offset += batch_size
            continue

        if not embeddings or len(embeddings) != len(texts):
            print(f"[reembed] Embedding count mismatch: expected {len(texts)}, got {len(embeddings) if embeddings else 0}")
            errors += len(batch)
            offset += batch_size
            continue

        pairs = []
        for i, emb in enumerate(embeddings):
            if len(emb) != EMBEDDING_DIM:
                print(f"[reembed] WARNING: row id={ids[i]} got dim={len(emb)}, expected {EMBEDDING_DIM} — skipping")
                errors += 1
                continue
            pairs.append((ids[i], emb))

        if not pairs:
            offset += batch_size
            continue

        # Write to NEW column (embedding_1024)
        count = update_embeddings_into_new_col(pairs, new_col)
        updated += count
        print(f"[reembed] Updated {count}/{len(pairs)} rows (total: {updated}/{total})")

        offset += batch_size

    print(f"\n[reembed] Done. Updated: {updated}, Errors: {errors}")

    # Spot-check new column dimensions
    print("\n[reembed] Spot-checking new column dimensions...")
    with PgSession() as s:
        sample = s.fetchall(
            f"SELECT id, vector_dims({new_col}) AS dims FROM semantic_facts "
            f"WHERE {new_col} IS NOT NULL ORDER BY id DESC LIMIT 5"
        )
        for row in sample:
            print(f"  id={row['id']}  dims={row['dims']}")


def update_embeddings_into_new_col(rows, column):
    """rows: list of (id, new_embedding_list)"""
    if not rows:
        return 0
    with PgSession() as s:
        for row_id, embedding in rows:
            vec_literal = "[" + ",".join(str(x) for x in embedding) + "]"
            s.execute(
                f"UPDATE semantic_facts SET {column}='{vec_literal}'::vector WHERE id={row_id}",
                None,
            )
    return len(rows)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 scripts/reembed_all.py --migrate          # add new 1024-dim column")
        print("  python3 scripts/reembed_all.py --reembed         # reembed into new column")
        print("  python3 scripts/reembed_all.py --finalize        # swap columns after reembed")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "--migrate":
        migrate_column()
    elif cmd == "--reembed":
        reembed_into_new_column()
    elif cmd == "--finalize":
        finalize_migration()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)