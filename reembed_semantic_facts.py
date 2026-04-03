#!/usr/bin/env python3
"""
Re-embed semantic_facts with NULL embeddings using Chutes batch API.
Uses keyset pagination (WHERE id > last_id) for efficient NULL-only processing.
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


def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {"last_id": 0, "embedded": 0, "failed": 0, "started_at": time.time()}


def save_checkpoint(cp):
    cp["last_run"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(cp, f, indent=2)


def get_null_embeddings_batch(last_id: int, batch_size: int = 100):
    """Get NULL embeddings where id > last_id, ordered by id."""
    return pg_fetchall(
        "SELECT id, content, metadata FROM semantic_facts WHERE embedding IS NULL AND id > %s ORDER BY id LIMIT %s",
        (last_id, batch_size)
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
    print("Method: Keyset pagination (WHERE id > last_id)")
    print()

    cp = load_checkpoint()
    last_id = cp.get("last_id", 0)
    total_embedded = cp.get("embedded", 0)
    total_failed = cp.get("failed", 0)

    print(f"Checkpoint: last_id={last_id}, embedded={total_embedded}, failed={total_failed}")

    consecutive_empty = 0
    max_empty = 3  # Stop after 3 consecutive empty fetches

    while consecutive_empty < max_empty:
        rows = get_null_embeddings_batch(last_id, batch_size=100)

        if not rows:
            consecutive_empty += 1
            print(f"\n[FETCH] No more rows after id={last_id} (empty #{consecutive_empty}/{max_empty})")
            time.sleep(1)
            continue

        consecutive_empty = 0
        print(f"\n[FETCH] Got {len(rows)} rows, last_id in batch={rows[-1]['id']}")

        batch_buffer = []
        batch_ids = []

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
                        if emb is None or len(emb) == 0:
                            total_failed += 1
                            print(f"  - ID {fid}: NULL embedding returned")
                            continue

                        try:
                            update_embedding(fid, emb)
                            total_embedded += 1
                            print(f"  + ID {fid}: OK ({len(emb)} dims)")
                            last_id = fid
                        except Exception as e:
                            total_failed += 1
                            print(f"  - ID {fid}: FAILED - {e}")

                except Exception as e:
                    print(f"[ERROR] Batch embed failed: {e}")
                    total_failed += len(batch_ids)

                cp = {"last_id": last_id, "embedded": total_embedded, "failed": total_failed}
                save_checkpoint(cp)

                batch_buffer = []
                batch_ids = []
                time.sleep(0.5)  # Rate limit

        # Save checkpoint after each batch of 100
        cp = {"last_id": last_id, "embedded": total_embedded, "failed": total_failed}
        save_checkpoint(cp)

    print("\n" + "=" * 60)
    print("[DONE]")
    print(f"  Embedded: {total_embedded}")
    print(f"  Failed: {total_failed}")
    print("=" * 60)

    if total_failed == 0 and total_embedded > 0:
        try:
            os.remove(CHECKPOINT_FILE)
            print("[CLEANUP] Checkpoint removed - all done!")
        except Exception:
            pass


if __name__ == "__main__":
    main()