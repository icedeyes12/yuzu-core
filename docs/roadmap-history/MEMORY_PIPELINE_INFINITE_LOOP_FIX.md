# Memory Pipeline Infinite Loop — Root Cause Analysis

**Status**: Audit Complete — Awaiting Fix Implementation  
**Date**: 2026-06-09  
**Severity**: Critical (System hangs, resource exhaustion)

---

## Executive Summary

The memory pipeline enters an **infinite historical backlog processing loop** due to a fundamental design flaw in how `last_segmented_count` is used as both:
1. A **message count** (stored in DB)
2. A **list index** (used in Python slice operations)

This dual semantics breaks down when:
- Historical messages exist in the database
- Pipeline state is partially updated (e.g., after crash, manual intervention, or schema migration)
- The pipeline incorrectly interprets old messages as "new unsegmented messages"

---

## Symptom

From user report:
> *"creating episodes 3417, 3418, 3419 sequentially for ~2 hours until manually killed"*

This indicates:
- Pipeline is processing **thousands of historical messages** sequentially
- Each run creates a few episodes (3417, 3418, 3419...) from small message batches
- The loop doesn't self-terminate because trigger condition remains satisfied

---

## Architecture Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      ORCHESTRATOR                                │
│  (handle_user_message_streaming → post-turn cleanup)            │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                  MemoryService.trigger_pipeline_async           │
│  - Throttle: Check every 50 messages                            │
│  - Debounce: Min 5 minutes between triggers                     │
│  - Semaphore: Max 2 concurrent pipelines globally               │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│          trigger_memory_pipeline_async (memory.py)              │
│  1. should_trigger_segmentation_async:                         │
│     - delta = current_count - last_segmented_count             │
│     - if delta >= 50 OR (delta >= 40 AND idle ≥ 3h) → trigger  │
│  2. _try_set_fence_async: Prevent concurrent runs              │
│  3. enqueue_memory_pipeline_async: Queue for background worker │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│          run_memory_pipeline_async (memory.py:807-890)          │
│  1. Get last_segmented_count from DB                           │
│  2. Fetch ALL messages (limit=10000)                           │
│  3. Filter to user/assistant messages                          │
│  4. Slice: unsegmented = messages[last_segmented_count:]       │
│  5. Batch segment → create episodes → PCL                      │
│  6. mark_segmentation_done_async(last_segmented_count + count) │
└─────────────────────────────────────────────────────────────────┘
```

---

## Root Cause: Count/Index Dual-Semantics Bug

### The Bug

**File**: `app/memory/memory.py`  
**Lines**: 827, 840-846

```python
# Line 827
last_segmented_count = state.get("last_segmented_count", 0) or 0

# Lines 833-842
all_messages = await get_session_messages_async(session_id, limit=10000)
conversation_messages = [
    m for m in all_messages if m.get("role") in ("user", "assistant")
]

# CRITICAL BUG: Uses count as list index
unsegmented = conversation_messages[last_segmented_count:]
unsegmented_count = len(unsegmented)
```

### Why This Breaks

1. **`last_segmented_count` is stored as a message count** (e.g., "processed 3417 messages total")
2. **But used as a Python list index** (`conversation_messages[3417:]`)
3. **The two are NOT equivalent** when:
   - Messages are deleted
   - Messages are filtered by role (user/assistant only)
   - The conversation list order differs from DB order

### Scenario: Historical Backlog Loop

```
Initial State:
  - Total messages in DB: 5000
  - Conversation messages (user/assistant filtered): 4000
  - last_segmented_count: 0

Run 1:
  - Processes messages 0-49 (50 messages)
  - Creates episodes
  - Updates: last_segmented_count = 50

Run 2:
  - Crash or manual intervention after processing message at index 3417
  - State corrupted: last_segmented_count = 3417 (partial update)

Run 3 (Restart):
  - Fetches all messages → conversation_messages (4000 items)
  - Slices: conversation_messages[3417:] → 583 messages
  - These are HISTORICAL messages, not new ones!
  - Creates episodes 3417, 3418, 3419...
  - Updates: last_segmented_count = 3468

Trigger Check (after Run 3):
  - current_count = 5000 (total DB count)
  - delta = 5000 - 3468 = 1532
  - delta >= 50 → TRIGGER AGAIN!

Run 4, 5, 6... (Infinite Loop):
  - Processes messages 3468-3519, 3519-3570, etc.
  - Each run advances last_segmented_count
  - Delta never drops below threshold
  - Runs for hours until manually killed
```

---

## Contributing Factors

### 1. No Scope Limitation Per Run

**File**: `app/memory/memory.py`  
**Lines**: 840-846

```python
unsegmented = conversation_messages[last_segmented_count:]
```

**Issue**: No cap on `unsegmented_count`. Pipeline attempts to process ALL unsegmented messages in a single run.

**Impact**: If `last_segmented_count = 3417` and there are 1583 historical messages, pipeline attempts to process all 1583 in one go.

### 2. Trigger Doesn't Track Processing Completion

**File**: `app/memory/memory.py`  
**Lines**: 240-241

```python
last_count = state.get("last_segmented_count", 0) or 0
delta = current_count - last_count
```

**Issue**: `delta` is calculated from DB total count, not from actual processing progress.

**Impact**: Even if pipeline is making progress through historical backlog, `delta` remains large and triggers continue.

### 3. Filtered List Mismatch

**File**: `app/memory/memory.py`  
**Lines**: 835-837

```python
conversation_messages = [
    m for m in all_messages if m.get("role") in ("user", "assistant")
]
```

**Issue**: `conversation_messages` is a filtered subset, but `last_segmented_count` is supposed to represent **total message count** (including filtered ones).

**Impact**: 
- If there are 1000 system/tool messages scattered throughout history
- `conversation_messages` has 4000 items (vs 5000 in DB)
- `last_segmented_count = 3417` → `conversation_messages[3417:]` skips to near the end
- Pipeline misses messages that should be processed

### 4. No Historical Backlog Detection

**File**: `app/memory/memory.py`  
**Lines**: 233-249

```python
async def should_trigger_segmentation_async(session_id, current_count):
    if await _is_fence_active_async(session_id):
        return False, 0
    
    state = await _get_cached_memory_state_async(session_id)
    last_count = state.get("last_segmented_count", 0) or 0
    delta = current_count - last_count
    
    if delta >= WINDOW_MAX:
        return True, delta  # <-- Triggers on historical backlog too
    
    if delta < WINDOW_BASE:
        return False, delta
    
    idle_hours = await _get_session_idle_hours_async(session_id)
    if idle_hours is not None and idle_hours < IDLE_GATE_HOURS:
        return False, delta
    
    return True, delta
```

**Issue**: No distinction between:
- "New messages arrived since last segmentation"
- "Historical backlog exists from previous incomplete runs"

**Impact**: Historical backlog is treated the same as new message accumulation, triggering infinite loop.

---

## Data Flow Diagram

```
DB: chat_sessions.memory_state
  └─ last_segmented_count: 3417
         │
         ▼
get_memory_state_async(session_id)
         │
         ▼
last_segmented_count = 3417  ←── Treated as "processed 3417 messages"
         │
         ▼
get_session_messages_async(session_id, limit=10000)
         │
         ▼
all_messages (5000 items, ordered by timestamp)
         │
         ▼
conversation_messages (4000 items, user/assistant only)
         │
         ▼
unsegmented = conversation_messages[3417:]  ←── Treated as "start from index 3417"
         │                                    This is a LIST INDEX, not a message count!
         ▼
process 583 historical messages (indices 3417-4000)
         │
         ▼
mark_segmentation_done_async(3417 + 583 = 4000)
         │
         ▼
last_segmented_count = 4000
         │
         ▼
Next trigger check:
  current_count = 5000
  delta = 5000 - 4000 = 1000
  1000 >= 50 → TRIGGER AGAIN!
```

---

## Recommended Fixes

### Option A: Migrate to Message ID-Based Indexing (Recommended)

**Rationale**: Use database message IDs instead of counts. This is robust against:
- Message deletions
- Filtering
- Order changes

**Implementation**:

```python
# DB schema change
# memory_state: {
#   "last_segmented_message_id": <int>,  # Last processed message DB ID
#   "last_segmented_at": <timestamp>
# }

async def run_memory_pipeline_async(session_id: int, message_count: int) -> dict:
    state = await get_memory_state_async(session_id)
    last_message_id = state.get("last_segmented_message_id", 0) or 0
    
    # Query messages AFTER the last processed ID
    unsegmented = await get_messages_after_id_async(session_id, last_message_id, limit=100)
    
    if not unsegmented:
        return {"segments": 0, "episodes": 0, "pcl_runs": 0}
    
    # Process...
    
    # Update with last processed message ID
    last_id = unsegmented[-1]["id"]
    await update_memory_state_async(session_id, {
        "last_segmented_message_id": last_id,
        "last_segmented_at": datetime.now().isoformat(),
    })
```

**Pros**:
- Idempotent: Re-running processes same messages
- No confusion between count and index
- Handles deletions gracefully

**Cons**:
- Requires schema migration
- More complex query logic

---

### Option B: Add Scope Limit + Backlog Detection

**Rationale**: Keep count-based logic but add safeguards to prevent runaway processing.

**Implementation**:

```python
# Constants
MAX_MESSAGES_PER_RUN = 100
HISTORICAL_BACKLOG_THRESHOLD = 1000

async def run_memory_pipeline_async(session_id: int, message_count: int) -> dict:
    state = await get_memory_state_async(session_id)
    last_count = state.get("last_segmented_count", 0) or 0
    
    all_messages = await get_session_messages_async(session_id, limit=10000)
    conversation_messages = [
        m for m in all_messages if m.get("role") in ("user", "assistant")
    ]
    
    # SCOPE LIMIT: Process only MAX_MESSAGES_PER_RUN at a time
    start_idx = min(last_count, len(conversation_messages))
    end_idx = min(start_idx + MAX_MESSAGES_PER_RUN, len(conversation_messages))
    unsegmented = conversation_messages[start_idx:end_idx]
    
    if len(unsegmented) < MIN_MESSAGES:
        await mark_segmentation_done_async(session_id, len(conversation_messages))
        return {"segments": 0, "episodes": 0, "pcl_runs": 0}
    
    # Process...
    
    # Mark done with actual processed count
    new_count = start_idx + len(unsegmented)
    await mark_segmentation_done_async(session_id, new_count)

async def should_trigger_segmentation_async(session_id: int, current_count: int):
    # Check if there's remaining backlog to process
    state = await get_memory_state_async(session_id)
    last_count = state.get("last_segmented_count", 0) or 0
    
    # NEW: Check remaining backlog
    remaining_backlog = current_count - last_count
    
    # Don't trigger on huge historical backlogs (assume it's from migration)
    if remaining_backlog > HISTORICAL_BACKLOG_THRESHOLD:
        # Set a flag for manual review or one-time migration
        logger.warning(f"Historical backlog detected: {remaining_backlog} messages")
        return False, remaining_backlog
    
    if remaining_backlog >= WINDOW_MAX:
        return True, remaining_backlog
    
    # ... rest of logic
```

**Pros**:
- Minimal schema change
- Limits resource usage per run
- Detects anomalies

**Cons**:
- Still has count/index semantic confusion
- Requires tuning thresholds

---

### Option C: One-Time Historical Migration

**Rationale**: Set `last_segmented_count` to current total for all existing sessions, preventing historical processing.

**Implementation**:

```python
# scripts/migrate_memory_state.py

import asyncio
from app.db import pg_fetchall_async, pg_execute_async

async def migrate():
    """Set last_segmented_count to current total for all sessions."""
    sessions = await pg_fetchall_async("SELECT id FROM chat_sessions")
    
    for session in sessions:
        session_id = session["id"]
        
        # Count total user/assistant messages
        count_row = await pg_fetchall_async("""
            SELECT COUNT(*) as cnt FROM messages
            WHERE session_id = %s AND role IN ('user', 'assistant')
        """, (session_id,))
        
        total = count_row[0]["cnt"]
        
        # Set last_segmented_count to total
        await pg_execute_async("""
            UPDATE chat_sessions
            SET memory_state = jsonb_set(
                COALESCE(memory_state, '{}'::jsonb),
                '{last_segmented_count}',
                %s::jsonb
            )
            WHERE id = %s
        """, (str(total), session_id))
        
        print(f"Migrated session {session_id}: last_segmented_count = {total}")

if __name__ == "__main__":
    asyncio.run(migrate())
```

**Pros**:
- Quick fix, no code changes
- Prevents historical processing immediately

**Cons**:
- Doesn't fix the underlying bug
- Historical messages never get processed (might be desired, might not)
- Pipeline will still break if state gets corrupted again

---

## Additional Issues Found

### 1. Temporal Segmentation Merge Can Create Overlaps

**File**: `app/memory/memory.py`  
**Lines**: 665-688

```python
def _merge_small_segments(segments: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for seg in segments:
        size = seg["end_idx"] - seg["start_idx"]
        if size < MIN_SEGMENT_MESSAGES and merged:
            # Absorb into previous segment
            merged[-1]["end_idx"] = seg["end_idx"]  # <-- Overlap risk?
```

**Issue**: If segment indices are overlapping or non-contiguous, merging might create segments that cover the same messages twice.

**Recommendation**: Add validation to ensure no overlaps after merging.

---

### 2. PCL Pipeline Lacks Idempotency Check

**File**: `app/memory/pcl.py`  
**Lines**: 483-512

```python
async def run_predict_calibrate_async(session_id, episode_summary, messages, episode_id):
    # No check for: Was this episode already consolidated?
    
    # Mark episode consolidated
    if episode_id:
        meta["consolidated_at"] = datetime.now().isoformat()
```

**Issue**: If pipeline retries after crash, same episode gets PCL again, potentially creating duplicate semantic facts.

**Recommendation**: Check `consolidated_at` before running PCL:

```python
episode = await get_fact_by_id_async(episode_id)
if episode.get("metadata", {}).get("consolidated_at"):
    logger.info(f"Episode {episode_id} already consolidated, skipping PCL")
    return None
```

---

### 3. Category Cap Check Races

**File**: `app/memory/pcl.py`  
**Lines**: 364-369

```python
async def _get_category_counts_async(session_id: int) -> dict[str, int]:
    facts = await get_facts_by_session_async(...)
    counts: dict[str, int] = {}
    for f in facts:
        cat = f.get("metadata", {}).get("category", "Experience")
        counts[cat] = counts.get(cat, 0) + 1
    return counts
```

**Issue**: Counts are fetched once per consolidation run. If multiple pipelines run concurrently (despite fence), category caps might be exceeded.

**Recommendation**: Use atomic increment-check in DB or serialize category fact creation.

---

## Summary Table

| Issue | Location | Severity | Fix Priority |
|-------|----------|----------|--------------|
| Count → Index dual-semantics | `memory.py:840-842` | Critical | P0 |
| No scope limit per run | `memory.py:840-842` | High | P1 |
| Trigger ignores historical backlog | `memory.py:233-249` | High | P1 |
| PCL lacks idempotency | `pcl.py:483-512` | Medium | P2 |
| Category cap races | `pcl.py:364-369` | Low | P3 |
| Temporal merge overlaps | `memory.py:665-688` | Low | P3 |

---

## Conclusion

The infinite loop is caused by **fundamental semantic confusion** between message count and list index, combined with **missing safeguards** for historical backlog processing.

**Root Cause**: `last_segmented_count` is stored as a count but used as an index, breaking when state is partially updated or when conversations are filtered.

**Recommended Fix**: Migrate to message ID-based indexing (Option A) for long-term stability, combined with scope limits (Option B) for defense-in-depth.

**Immediate Workaround**: Run one-time migration (Option C) to set `last_segmented_count` to current totals, preventing historical processing until proper fix is implemented.
