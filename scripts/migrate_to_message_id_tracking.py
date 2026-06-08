#!/usr/bin/env python3
"""
Phase 3 migration: Initialize last_segmented_message_id for message ID-based tracking.

This eliminates the count-vs-index dual-semantics bug by tracking the actual
message ID of the last segmented message, rather than a count that could be
misinterpreted as a list index.

For each session:
- Finds the latest message ID (user or assistant role)
- Sets last_segmented_message_id to this ID
- Preserves existing memory_state fields

Run once:
    python scripts/migrate_to_message_id_tracking.py [--dry-run]

This script is idempotent - safe to run multiple times.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime

# Add parent directory to path for imports
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.connection import get_async_pool

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def get_all_sessions_async() -> list[dict]:
    """Get all sessions with their current memory_state."""
    pool = await get_async_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, name, memory_state FROM chat_sessions ORDER BY id"
            )
            columns = [desc[0] for desc in cur.description]
            rows = await cur.fetchall()
            return [dict(zip(columns, row)) for row in rows]


async def get_last_message_id_async(session_id: int) -> int | None:
    """Get the ID of the most recent user/assistant message in a session."""
    pool = await get_async_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id FROM messages
                WHERE session_id = %s AND role IN ('user', 'assistant')
                ORDER BY id DESC
                LIMIT 1
                """,
                (session_id,),
            )
            row = await cur.fetchone()
            return row[0] if row else None


async def update_memory_state_async(
    session_id: int, last_message_id: int | None, dry_run: bool = False
) -> bool:
    """Update memory_state with last_segmented_message_id."""
    if dry_run:
        logger.info(f"  [DRY-RUN] Would set last_segmented_message_id={last_message_id}")
        return True

    pool = await get_async_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            # Get current state
            await cur.execute(
                "SELECT memory_state FROM chat_sessions WHERE id = %s FOR UPDATE",
                (session_id,),
            )
            row = await cur.fetchone()
            if not row:
                return False

            state = row[0] if row[0] else {}

            # Add new field, preserving existing
            state["last_segmented_message_id"] = last_message_id
            state["migrated_to_id_tracking"] = True
            state["migrated_at"] = datetime.now().isoformat()

            await cur.execute(
                "UPDATE chat_sessions SET memory_state = %s, updated_at = %s WHERE id = %s",
                (json.dumps(state), datetime.now(), session_id),
            )
            return True


async def run_migration_async(dry_run: bool = False) -> dict:
    """Run the migration for all sessions."""
    logger.info("=" * 60)
    logger.info("Phase 3: Message ID Tracking Migration")
    logger.info("=" * 60)

    if dry_run:
        logger.info("🔍 DRY-RUN MODE - No changes will be made")
    else:
        logger.info("⚠️  LIVE MODE - Database will be updated")
    logger.info("")

    # Initialize connection pool
    logger.info("Initializing database connection pool...")
    await get_async_pool()

    # Fetch all sessions
    logger.info("Fetching all sessions...")
    sessions = await get_all_sessions_async()
    logger.info(f"Found {len(sessions)} sessions")
    logger.info("")

    if not sessions:
        logger.info("No sessions to migrate")
        return {"sessions": 0, "updated": 0, "skipped": 0}

    # Process each session
    updated_count = 0
    skipped_count = 0

    for session in sessions:
        session_id = session["id"]
        session_name = session.get("name", "Unknown")
        current_state = session.get("memory_state") or {}

        # Get the last message ID
        last_msg_id = await get_last_message_id_async(session_id)

        if last_msg_id is None:
            logger.info(f"[{session_id}] '{session_name}': no messages, skipping")
            skipped_count += 1
            continue

        # Check if already migrated
        existing_id = current_state.get("last_segmented_message_id")
        was_migrated = current_state.get("migrated_to_id_tracking", False)

        status = ""
        if was_migrated and existing_id is not None:
            if existing_id == last_msg_id:
                status = "(already up-to-date)"
            else:
                status = f"(was: msg_id {existing_id})"
        else:
            status = f"(was: count {current_state.get('last_segmented_count', 'N/A')})"

        logger.info(
            f"[{session_id}] '{session_name}': last_msg_id={last_msg_id} {status}"
        )

        # Perform the update
        success = await update_memory_state_async(session_id, last_msg_id, dry_run)

        if success:
            updated_count += 1

    logger.info("")
    logger.info("=" * 60)
    logger.info("Migration Summary")
    logger.info("=" * 60)
    logger.info(f"Total sessions: {len(sessions)}")
    logger.info(f"Updated: {updated_count}")
    logger.info(f"Skipped (no messages): {skipped_count}")

    if dry_run:
        logger.info("")
        logger.info("This was a DRY-RUN. Run without --dry-run to apply changes.")

    return {"sessions": len(sessions), "updated": updated_count, "skipped": skipped_count}


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate to message ID-based tracking"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without making changes",
    )
    args = parser.parse_args()

    # Check database environment variables
    required_vars = ["PGDATABASE", "PGUSER", "PGPASSWORD"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        logger.warning(f"⚠️  Missing environment variables: {', '.join(missing)}")
        logger.warning("Set PGDATABASE, PGUSER, PGPASSWORD before running")
        logger.warning("")
        logger.warning("Example:")
        logger.warning("  export PGDATABASE=yuzuki")
        logger.warning("  export PGUSER=icedeyes12")
        logger.warning("  export PGPASSWORD=Kawaii12")

    asyncio.run(run_migration_async(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
