#!/usr/bin/env python3
"""
Re-embed semantic_facts with NULL embeddings using Chutes batch API.
Simple, robust, no checkpoint complexity.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db_pg import PgSession, pg_fetchall
from app.memory.embedder import embed_texts

BATCH_SIZE = 32


def get_null_count():
    result = pg_fetchall(
        "SELECT COUNT(*) as cnt FROM semantic_facts WHERE embedding IS NULL"
    )
    return result[0]['cnt'] if result else 0


def get_null_embeddings(limit=100):
    return pg_fetchall(
        "SELECT id, content FROM semantic_facts WHERE embedding IS NULL ORDER BY id LIMIT %s",
        (limit,)
    )


def update_embedding(fact_id: int, embedding: list[float]):
    with PgSession() as s:
        cur = s.conn.cursor()
        cur.execute(
            "UPDATE semantic_facts SET embedding = %s WHERE id = %s",
            (embedding, fact_id)
        )
        s.conn.commit()


def main():
    print("=" * 60)
    print("[REEMBED] Batch Re-Embedding via Chutes API")
    print("=" * 60)
    print("Model: Qwen/Qwen3-Embedding-8B (4096 dims)")
    print(f"Batch size: {BATCH_SIZE}")
    print()

    total_null = get_null_count()
    print(f"Total NULL embeddings to fix: {total_null}")
    print()

    if total_null == 0:
        print("[DONE] No NULL embeddings!")
        return

    total_embedded = 0
    total_failed = 0

    while True:
        rows = get_null_embeddings(limit=100)
        if not rows:
            break

        print(f"[FETCH] Got {len(rows)} rows")

        batch_texts = []
        batch_ids = []

        for row in rows:
            content = row.get('content', '')
            if content and len(content.strip()) >= 5:
                batch_texts.append(content[:500])
                batch_ids.append(row['id'])

        if not batch_texts:
            print("[SKIP] All rows too short")
            continue

        # Embed in batches
        for i in range(0, len(batch_texts), BATCH_SIZE):
            texts = batch_texts[i:i + BATCH_SIZE]
            ids = batch_ids[i:i + BATCH_SIZE]

            print(f"[EMBED] Batch of {len(texts)} texts...")
            try:
                embeddings = embed_texts(texts)
                print(f"[OK] Got {len(embeddings)} embeddings")

                for fid, emb in zip(ids, embeddings):
                    if emb is None or len(emb) == 0:
                        total_failed += 1
                        print(f"  - ID {fid}: NULL embedding")
                        continue

                    try:
                        update_embedding(fid, emb)
                        total_embedded += 1
                        print(f"  + ID {fid}: OK ({len(emb)} dims)")
                    except Exception as e:
                        total_failed += 1
                        print(f"  - ID {fid}: UPDATE FAILED - {e}")

            except Exception as e:
                print(f"[ERROR] Batch embed failed: {e}")
                total_failed += len(ids)

            time.sleep(0.5)

        remaining = get_null_count()
        print(f"[PROGRESS] Embedded: {total_embedded}, Failed: {total_failed}, Remaining: {remaining}")
        print()

        if remaining == 0:
            break

    print("=" * 60)
    print("[DONE]")
    print(f"  Embedded: {total_embedded}")
    print(f"  Failed: {total_failed}")
    print("=" * 60)


if __name__ == "__main__":
    main()
