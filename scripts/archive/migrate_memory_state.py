#!/usr/bin/env python3
"""
Emergency reset for memory pipeline state.

Sets last_segmented_count to the current total of user/assistant messages
for all existing sessions. This acts as a circuit breaker to stop the
infinite loop caused by count/index dual-semantics bug.

Run once:
    python scripts/migrate_memory_state.py

This script is idempotent - safe to run multiple times.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os

# Ensure app module is accessible
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Database connection (standalone, no app imports) ─────────────────────────────


def _build_dsn() -> str:
    """Build PostgreSQL DSN from environment."""
    host = os.getenv("PGHOST", os.getenv("DB_HOST", "localhost"))
    port = os.getenv("PGPORT", os.getenv("DB_PORT", "5432"))
    dbname = os.getenv("PGDATABASE", os.getenv("DB_NAME", "yuzu"))
    user = os.getenv("PGUSER", os.getenv("DB_USER", "postgres"))
    password = os.getenv("PGPASSWORD", os.getenv("DB_PASSWORD", ""))
    return f"host={host} port={port} dbname={dbname} user={user} password={password}"


# Global pool - initialized once in main()
_pool: AsyncConnectionPool | None = None


async def _get_pool() -> AsyncConnectionPool:
    """Get or create the async connection pool."""
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=_build_dsn(),
            min_size=1,
            max_size=3,
            kwargs={"row_factory": dict_row},
            open=False,
        )
        await _pool.open()
        logger.info("Connection pool opened")
    return _pool


async def pg_fetchall_async(query: str, params: tuple = ()) -> list[dict]:
    """Execute a query and return all rows as dicts."""
    pool = await _get_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()
            return list(rows)


async def pg_fetchone_async(query: str, params: tuple = ()) -> dict | None:
    """Execute a query and return a single row as dict."""
    pool = await _get_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
            row = await cur.fetchone()
            return row


async def pg_execute_async(query: str, params: tuple = ()) -> None:
    """Execute a query without returning results."""
    pool = await _get_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
            await conn.commit()


async def get_all_sessions_async() -> list[dict]:
    """Fetch all sessions with their current memory_state."""
    return await pg_fetchall_async(
        "SELECT id, name, memory_state FROM chat_sessions ORDER BY id"
    )


async def get_message_count_async(session_id: int) -> int:
    """Count user and assistant messages for a session."""
    row = await pg_fetchone_async(
        """
        SELECT COUNT(*) as count
        FROM messages
        WHERE session_id = %s AND role IN ('user', 'assistant')
        """,
        (session_id,),
    )
    return row["count"] if row else 0


async def update_memory_state_async(session_id: int, state: dict) -> None:
    """Update memory_state for a session (merge with existing)."""
    # Fetch existing
    row = await pg_fetchone_async(
        "SELECT memory_state FROM chat_sessions WHERE id = %s FOR UPDATE",
        (session_id,),
    )
    if not row:
        return

    existing = row.get("memory_state") or {}
    existing.update(state)

    await pg_execute_async(
        "UPDATE chat_sessions SET memory_state = %s, updated_at = NOW() WHERE id = %s",
        (json.dumps(existing), session_id),
    )


async def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Connection pool closed")


# ── Migration logic ─────────────────────────────────────────────────────────────


async def migrate_session(session_id: int, session_name: str, dry_run: bool) -> dict:
    """
    Reset memory_state.last_segmented_count for a single session.

    Returns dict with migration details.
    """
    # Get current state
    row = await pg_fetchone_async(
        "SELECT memory_state FROM chat_sessions WHERE id = %s",
        (session_id,),
    )
    current_state = row.get("memory_state") or {} if row else {}
    current_count = current_state.get("last_segmented_count", 0)

    # Get actual message count
    actual_count = await get_message_count_async(session_id)

    result = {
        "session_id": session_id,
        "session_name": session_name,
        "old_count": current_count,
        "actual_count": actual_count,
        "changed": current_count != actual_count,
    }

    if not dry_run and current_count != actual_count:
        await update_memory_state_async(
            session_id, {"last_segmented_count": actual_count}
        )
        logger.info(
            f"Session {session_id} ({session_name[:30]}): {current_count} → {actual_count}"
        )

    return result


async def main():
    """Run the migration for all sessions."""
    parser = argparse.ArgumentParser(description="Reset memory pipeline state")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would change, don't write"
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Memory Pipeline Emergency Reset Migration")
    if args.dry_run:
        logger.info("[DRY RUN - no changes will be written]")
    logger.info("=" * 60)

    # Fetch all sessions
    logger.info("Fetching all sessions...")
    sessions = await get_all_sessions_async()
    logger.info(f"Found {len(sessions)} sessions")

    if not sessions:
        logger.info("No sessions to migrate")
        await close_pool()
        return

    # Process each session
    results = []
    total_updated = 0

    for session in sessions:
        session_id = session["id"]
        session_name = session.get("name", "Unnamed")

        result = await migrate_session(session_id, session_name, dry_run=args.dry_run)
        results.append(result)

        if result["changed"]:
            total_updated += 1

    # Close pool
    await close_pool()

    # Summary
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total sessions: {len(sessions)}")
    logger.info(f"Sessions needing update: {total_updated}")

    if args.dry_run:
        logger.info("[DRY RUN - no changes written]")

    # Show details for changed sessions
    if total_updated > 0:
        logger.info("")
        logger.info("Changes:")
        for r in results:
            if r["changed"]:
                logger.info(
                    f"  Session {r['session_id']} ({r['session_name'][:30]}): "
                    f"{r['old_count']} → {r['actual_count']}"
                )


if __name__ == "__main__":
    asyncio.run(main())
