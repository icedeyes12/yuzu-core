from __future__ import annotations
# FILE: app/memory/review.py
# DESCRIPTION: FSRS-style review and decay system for memory - uses db_memory


import logging
import json
import asyncio
from pathlib import Path
from datetime import datetime
from app.memory.db_memory_facade import MemoryDB, FACT_TYPE_DYNAMIC

logger = logging.getLogger(__name__)

_DECAY_STATE_FILE = Path(__file__).resolve().parent / ".decay_state.json"


def _get_last_decay_time():
    """Return the last time decay ran (epoch), or None if never run."""
    if not _DECAY_STATE_FILE.exists():
        return None
    try:
        data = json.loads(_DECAY_STATE_FILE.read_text())
        return data.get("last_decay")
    except (ValueError, IOError):
        return None


def _set_last_decay_time():
    """Record current time as last decay timestamp."""
    try:
        _DECAY_STATE_FILE.write_text(
            json.dumps({"last_decay": datetime.now().isoformat()})
        )
    except IOError as e:
        logger.warning(f"Could not write decay state: {e}")


def run_decay(session_id=None, force=False):
    """Run full decay cycle on episodic/dynamic memories only.

    Semantic (static) facts are NOT decayed — they use temporal validity
    (valid_at/invalid_at) instead of FSRS-style decay.

    Skips if decay ran within the last 6 hours unless force=True.

    Args:
        session_id: optional session to limit decay scope
        force: run even if recently ran
    """
    if not force:
        last = _get_last_decay_time()
        if last:
            try:
                last_dt = datetime.strptime(last, "%Y-%m-%dT%H:%M:%S.%f")
                hours_since = (datetime.now() - last_dt).total_seconds() / 3600.0
                if hours_since < 6.0:
                    logger.debug(
                        f"Skipped — ran {hours_since:.1f}h ago (min interval: 6h)"
                    )
                    return
            except (ValueError, TypeError):
                pass

    logger.info("Running memory decay...")

    # Decay episodic memories (dynamic facts) — NOT semantic static facts
    try:
        count_episodic = MemoryDB.decay_facts(
            session_id=session_id, fact_type=FACT_TYPE_DYNAMIC
        )
        logger.info(f"Decayed {count_episodic} episodic memories")
    except Exception as e:
        logger.warning(f"Episodic decay failed: {e}")

    _set_last_decay_time()
    logger.info("Done.")


async def run_decay_async(session_id=None, force=False):
    """Run full decay cycle (async)."""
    if not force:
        last = _get_last_decay_time()
        if last:
            try:
                last_dt = datetime.strptime(last, "%Y-%m-%dT%H:%M:%S.%f")
                hours_since = (datetime.now() - last_dt).total_seconds() / 3600.0
                if hours_since < 6.0:
                    return
            except (ValueError, TypeError):
                pass

    logger.info("Running memory decay async...")

    try:
        # Re-implementing logic of decay_facts with async SQL
        # I'll just use asyncio.to_thread for now because decay_facts logic
        # is complex and it's already implemented.
        # But wait, I'm supposed to make everything non-blocking.
        # I'll use asyncio.to_thread for the sync decay_facts call.
        count_episodic = await asyncio.to_thread(
            MemoryDB.decay_facts, session_id=session_id, fact_type=FACT_TYPE_DYNAMIC
        )
        logger.info(f"Decayed {count_episodic} episodic memories")
    except Exception as e:
        logger.warning(f"Episodic decay failed: {e}")

    _set_last_decay_time()
    logger.info("Done.")


def reinforce_memory(memory_id, memory_type="semantic"):
    """Increase importance when a memory is retrieved.

    Args:
        memory_id: ID of the memory to reinforce.
        memory_type: 'semantic' or 'episodic' (ignored, all use same table)
    """
    MemoryDB.increment_importance(memory_id, delta=0.05, cap=1.0)


async def reinforce_memory_async(memory_id, memory_type="semantic"):
    """Increase importance (async)."""
    await asyncio.to_thread(
        MemoryDB.increment_importance, memory_id, delta=0.05, cap=1.0
    )
