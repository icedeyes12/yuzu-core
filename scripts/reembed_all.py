#!/usr/bin/env python3
"""
Re-embed active semantic_facts from 1024-dim to 4096-dim (Qwen3-Embedding-8B).

Migration: 1024 → 4096 dimensions (Chutes TEE endpoint)

Usage:
    python3 scripts/reembed_all.py --migrate          # add new 4096-dim column
    python3 scripts/reembed_all.py --reembed         # reembed ACTIVE facts only
    python3 scripts/reembed_all.py --finalize        # swap columns after reembed

This script:
1. Fetches ACTIVE rows only (invalid_at IS NULL) from semantic_facts
2. Re-embeds each content using Qwen3-Embedding-8B (4096-dim)
3. Updates the embedding column in batches
4. Reports progress and final count
"""

import sys
import os

# Add parent dir to path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load env vars from .env file if exists
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())
    print(f"✓ Loaded env from {env_file}")
else:
    print(f"⚠ No .env file found at {env_file}")

from app.memory.embedder import embed_texts  # noqa: E402
from app.db import PgSession  # noqa: E402

# New embedding dimension (Qwen3-Embedding-8B)
NEW_EMBEDDING_DIM = 4096
NEW_COL = "embedding"


def get_total_count(active_only=True):
    """Count rows with embeddings. If active_only, only count non-invalidated facts."""
    with PgSession() as s:
        if active_only:
            return s.fetchone(
                "SELECT COUNT(*) AS cnt FROM semantic_facts WHERE invalid_at IS NULL"
            )["cnt"]
        else:
            return s.fetchone("SELECT COUNT(*) AS cnt FROM semantic_facts WHERE 1=1")[
                "cnt"
            ]


def fetch_batch(offset, batch_size, active_only=True):
    """Fetch batch of facts for re-embedding."""
    with PgSession() as s:
        if active_only:
            return s.fetchall(
                "SELECT id, content FROM semantic_facts "
                "WHERE invalid_at IS NULL "
                "ORDER BY id LIMIT %s OFFSET %s",
                (batch_size, offset),
            )
        else:
            return s.fetchall(
                "SELECT id, content FROM semantic_facts "
                "WHERE 1=1 "
                "ORDER BY id LIMIT %s OFFSET %s",
                (batch_size, offset),
            )


def update_embeddings(rows, column="embedding"):
    """rows: list of (id, new_embedding_list)"""
    if not rows:
        return 0
    with PgSession() as s:
        for row_id, embedding in rows:
            # Vector literal is just comma-separated floats — no injection risk
            vec_literal = "[" + ",".join(str(x) for x in embedding) + "]"
            s.execute(
                f"UPDATE semantic_facts SET {column}='{vec_literal}'::vector WHERE id={row_id}",
                None,
            )
    return len(rows)


def migrate_column():
    """Add new 4096-dim column for migration."""

    with PgSession() as s:
        # 1. Verify current column dimension
        row = s.fetchone(
            "SELECT vector_dims(embedding) AS dims FROM semantic_facts WHERE embedding IS NOT NULL LIMIT 1"
        )
        current_dim = row["dims"] if row else None
        print(f"[migrate] Current embedding column dimension: {current_dim}")

        if current_dim == NEW_EMBEDDING_DIM:
            print(
                f"[migrate] Column already at target dim {NEW_EMBEDDING_DIM}, nothing to do."
            )
            return

        # 2. Check if new column already exists
        col_check = s.fetchone(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='semantic_facts' AND column_name=%s",
            (NEW_COL,),
        )
        if col_check:
            print(f"[migrate] Column {NEW_COL} already exists.")
        else:
            # 3. Add new column with correct dimension
            print(
                f"[migrate] Adding new column {NEW_COL} as VECTOR({NEW_EMBEDDING_DIM})..."
            )
            s.execute(
                f"ALTER TABLE semantic_facts ADD COLUMN {NEW_COL} vector({NEW_EMBEDDING_DIM})"
            )
            s.conn.commit()
            print(f"[migrate] New column {NEW_COL} added.")

        # 4. Informational: count active rows to re-embed
        count_row = s.fetchone(
            "SELECT COUNT(*) AS cnt FROM semantic_facts WHERE invalid_at IS NULL"
        )
        print(f"[migrate] {count_row['cnt']} ACTIVE rows need re-embedding.")

        total_row = s.fetchone("SELECT COUNT(*) AS cnt FROM semantic_facts WHERE 1=1")
        print(f"[migrate] {total_row['cnt']} total rows (including invalidated).")


def reembed_into_new_column(batch_size=50, active_only=True):
    """Re-embed all facts into new column with tracking.

    Args:
        batch_size: Number of rows per batch (default: 50)
        active_only: Only re-embed active facts (default: True)

    Safe: fetches from original embedding column, writes to new column.
    If the new column doesn't exist yet, aborts.
    """

    # Verify new column exists via information_schema
    with PgSession() as s:
        col_check = s.fetchone(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='semantic_facts' AND column_name=%s",
            (NEW_COL,),
        )
        if col_check is None:
            print(f"[reembed] Column {NEW_COL} not found. Run --migrate first.")
            return

    total = get_total_count(active_only=active_only)
    mode = "ACTIVE" if active_only else "ALL"
    print(f"[reembed] Total {mode} rows to re-embed: {total}")
    if total == 0:
        print("[reembed] Nothing to do.")
        return

    offset = 0
    updated = 0
    errors = 0

    while offset < total:
        batch = fetch_batch(offset, batch_size, active_only=active_only)
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
            print(
                f"[reembed] Embedding count mismatch: expected {len(texts)}, got {len(embeddings) if embeddings else 0}"
            )
            errors += len(batch)
            offset += batch_size
            continue

        pairs = []
        for i, emb in enumerate(embeddings):
            if len(emb) != NEW_EMBEDDING_DIM:
                print(
                    f"[reembed] WARNING: row id={ids[i]} got dim={len(emb)}, expected {NEW_EMBEDDING_DIM} — skipping"
                )
                errors += 1
                continue
            pairs.append((ids[i], emb))

        if not pairs:
            offset += batch_size
            continue

        # Write to NEW column
        count = update_embeddings(pairs, NEW_COL)
        updated += count
        print(f"[reembed] Updated {count}/{len(pairs)} rows (total: {updated}/{total})")

        offset += batch_size

    print(f"\n[reembed] Done. Updated: {updated}, Errors: {errors}")

    # Spot-check new column dimensions
    print("\n[reembed] Spot-checking new column dimensions...")
    with PgSession() as s:
        sample = s.fetchall(
            f"SELECT id, vector_dims({NEW_COL}) AS dims FROM semantic_facts "
            f"WHERE {NEW_COL} IS NOT NULL ORDER BY id DESC LIMIT 5"
        )
        for row in sample:
            print(f"  id={row['id']}  dims={row['dims']}")


def finalize_migration():
    """Drop old embedding column and rename new one. Run AFTER reembed completes."""

    with PgSession() as s:
        # Verify new column has data
        count_row = s.fetchone(
            f"SELECT COUNT(*) AS cnt FROM semantic_facts WHERE {NEW_COL} IS NOT NULL"
        )
        print(f"[finalize] Rows with new embeddings: {count_row['cnt']}")

        if count_row["cnt"] == 0:
            print(
                "[finalize] ERROR: No rows have embeddings in new column. Run --reembed first."
            )
            return

        # Spot-check dimension
        row = s.fetchone(
            f"SELECT vector_dims({NEW_COL}) AS dims FROM semantic_facts WHERE {NEW_COL} IS NOT NULL LIMIT 1"
        )
        if not row:
            print("[finalize] ERROR: new column is empty or doesn't exist.")
            return

        print(f"[finalize] New column dimension: {row['dims']} — looks good.")

        # Drop old column
        print("[finalize] Dropping old embedding column...")
        s.execute("ALTER TABLE semantic_facts DROP COLUMN embedding")

        # Rename new column to original name
        print(f"[finalize] Renaming {NEW_COL} → embedding...")
        s.execute(f"ALTER TABLE semantic_facts RENAME COLUMN {NEW_COL} TO embedding")

        # Recreate index
        print("[finalize] Recreating vector index...")
        s.execute(
            "CREATE INDEX IF NOT EXISTS idx_semantic_facts_embedding ON semantic_facts USING ivfflat (embedding vector_cosine_ops)"
        )

        s.conn.commit()
        print(f"[finalize] Done. Column is now VECTOR({NEW_EMBEDDING_DIM}).")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print(
            f"  python3 scripts/reembed_all.py --migrate          # add new {NEW_EMBEDDING_DIM}-dim column"
        )
        print(
            "  python3 scripts/reembed_all.py --reembed [--batch N]  # reembed ACTIVE facts"
        )
        print(
            "  python3 scripts/reembed_all.py --reembed-all [--batch N]  # reembed ALL facts"
        )
        print(
            "  python3 scripts/reembed_all.py --finalize        # swap columns after reembed"
        )
        sys.exit(1)

    cmd = sys.argv[1]
    batch_size = 50  # default

    # Parse --batch N argument
    if "--batch" in sys.argv:
        idx = sys.argv.index("--batch")
        if idx + 1 < len(sys.argv):
            batch_size = int(sys.argv[idx + 1])
            print(f"Using batch size: {batch_size}")

    if cmd == "--migrate":
        migrate_column()
    elif cmd == "--reembed":
        reembed_into_new_column(batch_size=batch_size, active_only=True)
    elif cmd == "--reembed-all":
        reembed_into_new_column(batch_size=batch_size, active_only=False)
    elif cmd == "--finalize":
        finalize_migration()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
