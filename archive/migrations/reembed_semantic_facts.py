#!/usr/bin/env python3
"""
Re-embed semantic_facts using halvec (HNSW indexing) with Chutes API.

HNSW notes:
- halvec max_dim = 2000, so we use halvec(2560) which auto-truncates to 2000
- Alternative: use pgvector with lower dim (1536) for full HNSW support
"""
import os
import sys
import time
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.database import pg_fetchone, pg_fetchall, pg_execute
from app.memory.embedder import embed_texts

BATCH_SIZE = 32
TARGET_DIM = 2560  # halvec will truncate to 2000 for HNSW index


def get_null_count():
    row = pg_fetchone("SELECT COUNT(*) as cnt FROM semantic_facts WHERE embedding IS NULL")
    return row.get('cnt', 0) if row else 0


def get_null_embeddings_batch(last_id: int, batch_size: int = 100):
    return pg_fetchall(
        "SELECT id, content FROM semantic_facts WHERE embedding IS NULL AND id > %s ORDER BY id LIMIT %s",
        (last_id, batch_size)
    )


def update_embedding(fact_id: int, embedding: list):
    """Store embedding as JSON string for halvec."""
    pg_execute(
        "UPDATE semantic_facts SET embedding = %s WHERE id = %s",
        (json.dumps(embedding), fact_id)
    )


def main():
    print("=" * 60)
    print("[REEMBED] HNSW + halvec Re-Embedding")
    print("=" * 60)
    print(f"Target dim: {TARGET_DIM} (halvec truncates to 2000 for HNSW)")

    total = get_null_count()
    print(f"Total NULL embeddings: {total}")
    print()

    if total == 0:
        print("[DONE] No NULL embeddings found!")
        return

    last_id = 0
    total_embedded = 0
    total_failed = 0

    while True:
        rows = get_null_embeddings_batch(last_id, batch_size=100)

        if not rows:
            print("[DONE] No more rows")
            break

        print(f"[FETCH] Got {len(rows)} rows")

        batch_buffer = []
        batch_ids = []

        for row in rows:
            fact_id = row.get('id')
            content = row.get('content', '')

            if not content or len(content.strip()) < 5:
                last_id = fact_id
                continue

            batch_buffer.append(content[:500])
            batch_ids.append(fact_id)
            last_id = fact_id

        if not batch_buffer:
            print("[SKIP] All rows too short")
            continue

        print(f"[EMBED] Batch of {len(batch_buffer)}...")
        try:
            embeddings = embed_texts(batch_buffer)
            print(f"[OK] Got {len(embeddings)} embeddings")

            for fid, emb in zip(batch_ids, embeddings):
                if emb is None or len(emb) == 0:
                    total_failed += 1
                    print(f"  - ID {fid}: NULL")
                    continue

                # Truncate to TARGET_DIM (halvec will further truncate to 2000)
                truncated = emb[:TARGET_DIM] if len(emb) >= TARGET_DIM else emb
                # Pad if shorter
                while len(truncated) < TARGET_DIM:
                    truncated.append(0.0)

                try:
                    update_embedding(fid, truncated)
                    total_embedded += 1
                    print(f"  + ID {fid}: OK ({len(truncated)} dims)")
                except Exception as e:
                    total_failed += 1
                    print(f"  - ID {fid}: {e}")

        except Exception as e:
            print(f"[ERROR] Batch embed failed: {e}")
            total_failed += len(batch_buffer)

        remaining = get_null_count()
        print(f"[PROGRESS] Embedded: {total_embedded}, Failed: {total_failed}, Remaining: {remaining}")

        if remaining == 0:
            break

        time.sleep(0.5)

    print()
    print("=" * 60)
    print(f"[DONE] Embedded: {total_embedded}, Failed: {total_failed}")
    print("=" * 60)
    print()
    print("NOTE: After re-embedding, create HNSW index:")
    print("  CREATE INDEX idx_hnsw ON semantic_facts USING hnsw (embedding halvec_l2_ops)")
    print("  WITH (m = 16, ef_construction = 200);")


if __name__ == "__main__":
    main()
