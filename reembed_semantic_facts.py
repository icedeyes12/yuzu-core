#!/usr/bin/env python3
"""
Re-embed semantic_facts with NULL embeddings using Chutes batch API.
Optimized for 2000+ rows with rate limiting and checkpointing.
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db_pg import PgSession, pg_fetchall
from app.memory.embedder import embed_texts

BATCH_SIZE = 32  # Chutes rate limit
CHECKPOINT_FILE = os.path.join(os.path.dirname(__file__), '.reembed_checkpoint.json')
START_ID = 0  # Change to resume


def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {"last_id": START_ID, "embedded": 0, "failed": 0, "started_at": time.time()}


def save_checkpoint(cp):
    cp["last_run"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(cp, f, indent=2)


def get_null_embeddings(limit=100, offset=0):
    return pg_fetchall(
        "SELECT id, content, metadata FROM semantic_facts WHERE embedding IS NULL ORDER BY id LIMIT %s OFFSET %s",
        (limit, offset)
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
    print(f"Start from ID: {START_ID}")
    print()

    cp = load_checkpoint()
    last_id = cp["last_id"]
    total_embedded = cp["embedded"]
    total_failed = cp["failed"]

    print(f"Checkpoint: last_id={last_id}, embedded={total_embedded}, failed={total_failed}")

    offset = 0
    batch_buffer = []
    batch_ids = []

    while True:
        rows = get_null_embeddings(limit=100, offset=offset)

        if not rows:
            print("\n[DONE] No more NULL embeddings found")
            break

        print(f"\n[FETCH] Got {len(rows)} rows (offset={offset})")

        for row in rows:
            fact_id = row.get("id")
            content = row.get("content", "")

            if not content or len(content.strip()) < 5:
                continue

            batch_buffer.append(content[:500])  # Truncate long text
            batch_ids.append(fact_id)

            if len(batch_buffer) >= BATCH_SIZE:
                print(f"\n[EMBED] Batch of {len(batch_buffer)} texts...")
                try:
                    embeddings = embed_texts(batch_buffer)
                    print(f"[OK] Got {len(embeddings)} embeddings")

                    for fid, emb in zip(batch_ids, embeddings):
                        try:
                            update_embedding(fid, emb)
                            total_embedded += 1
                            print(f"  + ID {fid}: OK ({len(emb)} dims)")
                        except Exception as e:
                            total_failed += 1
                            print(f"  - ID {fid}: FAILED - {e}")

                        last_id = fid

                except Exception as e:
                    print(f"[ERROR] Batch embed failed: {e}")
                    total_failed += len(batch_ids)

                cp = {"last_id": last_id, "embedded": total_embedded, "failed": total_failed}
                save_checkpoint(cp)

                batch_buffer = []
                batch_ids = []
                time.sleep(0.5)

        offset += 100

        # Safety limit - remove in production
        if offset >= 5000:
            print("\n[LIMIT] Reached offset limit. Remove to process all.")
            break

    print("\n" + "=" * 60)
    print("[DONE]")
    print(f"  Embedded: {total_embedded}")
    print(f"  Failed: {total_failed}")
    print(f"  Checkpoint: {CHECKPOINT_FILE}")
    print("=" * 60)

    if total_failed == 0 and total_embedded > 0:
        os.remove(CHECKPOINT_FILE)
        print("[CLEANUP] Checkpoint removed - all done!")


if __name__ == "__main__":
    main()
