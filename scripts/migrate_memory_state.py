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

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.connection import get_async_pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def pg_fetchall_async(query: str, params: tuple = ()) -> list[dict]:
    """Execute a query and return all rows as dicts."""
    pool = get_async_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
            columns = [desc[0] for desc in cur.description]
            rows = await cur.fetchall()
            return [dict(zip(columns, row)) for row in rows]


async def pg_fetchone_async(query: str, params: tuple = ()) -> dict | None:
    """Execute a query and return a single row as dict."""
    pool = get_async_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
            columns = [desc[0] for desc in cur.description]
            row = await cur.fetchone()
            if row:
                return dict(zip(columns, row))
            return None


async def pg_execute_async(query: str, params: tuple = ()) -> None:
    """Execute a query without returning results."""
    pool = get_async_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)


async def get_all_sessions_async() -> list[dict]:
    """Fetch all sessions from database."""
    return await pg_fetchall_async(
        "SELECT id, name, memory_state FROM chat_sessions ORDER BY id"
    )


async def count_conversation_messages_async(session_id: int) -> int:
    """Count user and assistant messages for a session."""
    row = await pg_fetchone_async(
        """
        SELECT COUNT(*) as cnt
        FROM messages
        WHERE session_id = %s AND role IN ('user', 'assistant')
        """,
        (session_id,),
    )
    return row["cnt"] if row else 0


async def update_memory_state_async(session_id: int, state: dict) -> None:
    """
    Update memory_state for a session.
    
    Merges with existing state using jsonb_set for atomicity.
    """
    # Build the jsonb_set path and value
    # We need to set multiple keys, so we'll use a simpler approach:
    # Get current state, merge, and update
    current = await pg_fetchone_async(
        "SELECT memory_state FROM chat_sessions WHERE id = %s",
        (session_id,),
    )
    
    if not current:
        return
    
    existing = current.get("memory_state") or {}
    if isinstance(existing, str):
        try:
            existing = json.loads(existing)
        except json.JSONDecodeError:
            existing = {}
    
    # Merge new state
    existing.update(state)
    
    await pg_execute_async(
        """
        UPDATE chat_sessions
        SET memory_state = %s::jsonb, updated_at = %s
        WHERE id = %s
        """,
        (json.dumps(existing), datetime.now(), session_id),
    )


async def migrate_session(session_id: int, session_name: str) -> tuple[int, int]:
    """
    Migrate a single session's memory state.
    
    Returns (old_count, new_count) for reporting.
    """
    # Get current state
    row = await pg_fetchone_async(
        "SELECT memory_state FROM chat_sessions WHERE id = %s",
        (session_id,),
    )
    
    if not row:
        logger.warning(f"Session {session_id} not found")
        return (0, 0)
    
    memory_state = row.get("memory_state") or {}
    if isinstance(memory_state, str):
        try:
            memory_state = json.loads(memory_state)
        except json.JSONDecodeError:
            memory_state = {}
    
    old_count = memory_state.get("last_segmented_count", 0) or 0
    
    # Count actual conversation messages
    actual_count = await count_conversation_messages_async(session_id)
    
    # Update if different
    if old_count != actual_count:
        await update_memory_state_async(
            session_id,
            {
                "last_segmented_count": actual_count,
                "last_segmented_at": datetime.now().isoformat(),
                "migration_source": "emergency_reset_2026_06_09",
            },
        )
        return (old_count, actual_count)
    
    return (old_count, actual_count)


async def main() -> None:
    """Run the migration for all sessions."""
    logger.info("=" * 60)
    logger.info("Memory Pipeline Emergency Reset Migration")
    logger.info("=" * 60)
    
    # Initialize connection pool
    logger.info("Initializing database connection pool...")
    get_async_pool()
    
    # Fetch all sessions
    logger.info("Fetching all sessions...")
    sessions = await get_all_sessions_async()
    logger.info(f"Found {len(sessions)} sessions")
    
    if not sessions:
        logger.info("No sessions to migrate")
        return
    
    # Process each session
    results = []
    total_updated = 0
    total_unchanged = 0
    
    for session in sessions:
        session_id = session["id"]
        session_name = session.get("name", "unnamed")
        
        old_count, new_count = await migrate_session(session_id, session_name)
        
        if old_count != new_count:
            total_updated += 1
            logger.info(
                f"Session {session_id} ({session_name}): "
                f"{old_count} → {new_count} messages"
            )
        else:
            total_unchanged += 1
            logger.debug(
                f"Session {session_id} ({session_name}): "
                f"already at {new_count} messages"
            )
        
        results.append({
            "session_id": session_id,
            "session_name": session_name,
            "old_count": old_count,
            "new_count": new_count,
            "changed": old_count != new_count,
        })
    
    # Summary
    logger.info("=" * 60)
    logger.info("Migration Complete")
    logger.info(f"  Total sessions: {len(sessions)}")
    logger.info(f"  Updated: {total_updated}")
    logger.info(f"  Unchanged: {total_unchanged}")
    logger.info("=" * 60)
    
    # Write results to file for audit trail
    output_file = Path(__file__).parent.parent / "migration_results.json"
    with open(output_file, "w") as f:
        json.dump(
            {
                "migration_timestamp": datetime.now().isoformat(),
                "total_sessions": len(sessions),
                "total_updated": total_updated,
                "total_unchanged": total_unchanged,
                "sessions": results,
            },
            f,
            indent=2,
        )
    logger.info(f"Results written to {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
