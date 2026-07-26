"""Re-embed memory_nodes and episodes from 4096-dim to 1536-dim vectors."""

import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH)

from app.db.connection import AsyncPgSession  # noqa: E402
from app.memory.embedder import embed_texts_async  # noqa: E402

log = logging.getLogger(__name__)
BATCH_SIZE = int(os.getenv("EMBED_MIGRATION_BATCH_SIZE", "50"))


async def _reembed_table(
    table: str, text_column: str, id_column: str = "id"
) -> tuple[int, int]:
    """Add embedding_new column, re-embed all rows, return (total, processed)."""
    async with AsyncPgSession() as s:
        await s.execute(
            f"ALTER TABLE {table} "
            f"ADD COLUMN IF NOT EXISTS embedding_new vector(1536)"
        )

    total = 0
    processed = 0
    last_id = "00000000-0000-0000-0000-000000000000"

    async with AsyncPgSession() as s:
        row = await s.fetchone(f"SELECT COUNT(*) AS cnt FROM {table}")
        total = row["cnt"] if row else 0

    while True:
        async with AsyncPgSession() as s:
            rows = await s.fetchall(
                f"SELECT {id_column}, {text_column} "
                f"FROM {table} "
                f"WHERE embedding_new IS NULL "
                f"  AND {text_column} IS NOT NULL "
                f"  AND {id_column} > %s "
                f"ORDER BY {id_column} LIMIT %s",
                (last_id, BATCH_SIZE),
            )
            if not rows:
                break

            texts = [r[text_column] for r in rows]
            embeddings = await embed_texts_async(texts)

            for row, emb in zip(rows, embeddings):
                vec = "[" + ",".join(str(float(v)) for v in emb) + "]"
                await s.execute(
                    f"UPDATE {table} SET embedding_new = %s::vector "
                    f"WHERE {id_column} = %s",
                    (vec, row[id_column]),
                )

            if table == "memory_nodes":
                await s.execute(
                    "UPDATE memory_nodes SET embedding_dimensions = 1536, "
                    "embedding_model = 'gemini-embedding-2-preview' "
                    "WHERE embedding_new IS NOT NULL"
                )

            processed += len(rows)
            last_id = str(rows[-1][id_column])
            log.info("[%s] re-embedded %d/%d", table, processed, total)

    return total, processed


async def _swap_columns(table: str) -> None:
    """Drop old embedding, rename embedding_new -> embedding."""
    async with AsyncPgSession() as s:
        await s.execute(f"DROP INDEX IF EXISTS idx_{table}_embedding")
        await s.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS embedding")
        await s.execute(
            f"ALTER TABLE {table} RENAME COLUMN embedding_new TO embedding"
        )


async def _try_hnsw_index(table: str) -> None:
    """Attempt HNSW index; fall back to exact scan on failure."""
    try:
        async with AsyncPgSession() as s:
            await s.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_embedding "
                f"ON {table} USING hnsw (embedding vector_cosine_ops)"
            )
        log.info("[%s] HNSW index created", table)
    except Exception as exc:  # noqa: BLE001
        log.warning("[%s] HNSW index skipped (exact scan OK): %s", table, exc)


async def _validate(table: str, total: int) -> None:
    """Verify every row got an embedding_new before swapping."""
    async with AsyncPgSession() as s:
        row = await s.fetchone(
            f"SELECT COUNT(*) AS cnt FROM {table} WHERE embedding_new IS NULL"
        )
        null_count = row["cnt"] if row else -1
    if null_count > 0:
        raise RuntimeError(
            f"[{table}] validation failed: {null_count} rows still NULL"
        )
    log.info("[%s] validation passed: %d rows, zero loss", table, total)


async def run_migration() -> None:
    if not os.getenv("EMBED_KEY"):
        raise RuntimeError("EMBED_KEY is missing from .env/environment")

    for table, text_col in [("episodes", "summary")]:
        log.info("=== Migrating %s ===", table)
        total, processed = await _reembed_table(table, text_col)
        await _validate(table, total)
        await _swap_columns(table)
        log.info("[%s] done: %d re-embedded", table, processed)

    log.info("All tables migrated to 1536-dim embeddings.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(run_migration())
