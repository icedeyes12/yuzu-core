#!/usr/bin/env python3
"""
Re-embed semantic_facts with NULL embeddings using Chutes batch API.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db_pg import pg_fetchone, pg_execute
from app.memory.embedder import embed_texts

BATCH_SIZE = 32


def get_null_count():
    row = pg_fetchone("SELECT COUNT(*) as cnt FROM semantic_facts WHERE embedding IS NULL")
    return row.get('cnt', 0) if row else 0


def get_null_embeddings_batch(last_id: int, batch_size: int = 100):
    return pg_fetchone(
        "SELECT id, content FROM semantic_facts WHERE embedding IS NULL AND id > %s ORDER BY id LIMIT %s",
        (last_id, batch_size)
    )


def update_embedding(fact_id: int, embedding: list):
    pg_execute(
        "UPDATE semantic_facts SET embedding = %s WHERE id = %s",
        (embedding, fact_id)
    )


def main():
    print("=" * 60)
    print("[REEMBED] Batch Re-Embedding via Chutes API")
    print("=" * 60)

    total = get_null_count()
    print(f"Total NULL embeddings: {total}")
    print()

    if total == 0:
        print("[DONE] No NULL embeddings found!")
        return

    last_id = 0
    total_embedded = 0
    total_failed = 0
    batch_buffer = []
    batch_ids = []

    while True:
        row = get_null_embeddings_batch(last_id, batch_size=100)

        if not row:
            break

        fact_id = row.get('id')
        content = row.get('content', '')

        if not content or len(content.strip()) < 5:
            last_id = fact_id
            continue

        batch_buffer.append(content[:500])
        batch_ids.append(fact_id)

        if len(batch_buffer) >= BATCH_SIZE:
            print(f"[EMBED] Batch of {len(batch_buffer)}...")
            try:
                embeddings = embed_texts(batch_buffer)
                print(f"[OK] Got {len(embeddings)} embeddings")

                for fid, emb in zip(batch_ids, embeddings):
                    if emb is None or len(emb) == 0:
                        total_failed += 1
                        continue
                    try:
                        update_embedding(fid, emb)
                        total_embedded += 1
                        last_id = fid
                    except Exception as e:
                        total_failed += 1
                        print(f"  - ID {fid}: FAILED - {e}")

                remaining = get_null_count()
                print(f"[PROGRESS] Embedded: {total_embedded}, Failed: {total_failed}, Remaining: {remaining}")

            except Exception as e:
                print(f"[ERROR] Batch embed failed: {e}")
                total_failed += len(batch_ids)

            batch_buffer = []
            batch_ids = []
            time.sleep(0.5)

    if batch_buffer:
        print(f"[EMBED] Final batch of {len(batch_buffer)}...")
        try:
            embeddings = embed_texts(batch_buffer)
            for fid, emb in zip(batch_ids, embeddings):
                if emb is None or len(emb) == 0:
                    total_failed += 1
                    continue
                try:
                    update_embedding(fid, emb)
                    total_embedded += 1
                except Exception:
                    total_failed += 1
        except Exception as e:
            print(f"[ERROR] Final batch failed: {e}")
            total_failed += len(batch_buffer)

    print()
    print("=" * 60)
    print(f"[DONE] Embedded: {total_embedded}, Failed: {total_failed}, Remaining: {get_null_count()}")
    print("=" * 60)


if __name__ == "__main__":
    main()
