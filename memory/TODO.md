# Memory System Implementation TODO

This document tracks the staged rollout of the memory subsystem.

---

## Phase 1 — Database Schema ✅

Goal:
Add new memory tables without modifying the existing messages table.

Tasks:

- [x] Create `semantic_memories` table
- [x] Create `episodic_memories` table
- [x] Create `conversation_segments` table
- [x] Add indexes for performance
- [x] Verify existing sessions and messages unaffected

Files:

- database.py

---

## Phase 2 — Memory Extraction ✅

Goal:
Extract semantic facts and episodic summaries from conversations.

Tasks:

- [x] Create `memory/extractor.py`
- [x] Implement semantic fact extraction (preferences, identity, patterns)
- [x] Implement emotional weight calculation
- [x] Implement episodic memory triggers
- [x] Implement upsert logic for semantic triples
- [x] Support Indonesian language patterns

Files:

- memory/extractor.py

---

## Phase 3 — Conversation Segmentation ✅

Goal:
Group messages into conversation segments.

Tasks:

- [x] Create `memory/segmenter.py`
- [x] Fixed-window segmentation (max 20 messages)
- [x] Time gap detection (15-minute threshold)
- [x] Episode summarization
- [x] Store segments in database

Files:

- memory/segmenter.py

---

## Phase 4 — Retrieval Pipeline ✅

Goal:
Score and select relevant memories for context building.

Tasks:

- [x] Create `memory/retrieval.py`
- [x] Semantic memory retrieval (importance × confidence)
- [x] Episodic memory ranking (importance + emotional_weight + recency)
- [x] Segment retrieval
- [x] Structured memory bundle format
- [x] Memory formatting for system prompt injection

Files:

- memory/retrieval.py

---

## Phase 5 — Context Builder Integration ✅

Goal:
Replace history-only context with structured memory system.

Tasks:

- [x] Modify `_build_generation_context()` in app.py
- [x] Inject structured memory into system message
- [x] Maintain backward compatibility with legacy memory sources
- [x] Add memory extraction after each assistant response
- [x] Fallback to raw history if memory retrieval fails

Files:

- app.py

---

## Phase 6 — Review & Decay System ✅

Goal:
Enable memory decay and reinforcement over time.

Tasks:

- [x] Create `memory/review.py`
- [x] Implement FSRS-style decay (exponential)
- [x] Stability based on access count
- [x] Memory reinforcement on retrieval
- [x] `run_decay()` function for periodic use

Files:

- memory/review.py

---

## Phase 7 — Migration & Fallback ✅

Goal:
Backward compatibility and migration tools.

Tasks:

- [x] Create `memory/migrate_history.py`
- [x] Batch extraction from old messages
- [x] Segment creation for existing sessions
- [x] Fallback to raw history on failure
- [x] Non-crash guarantees (all extraction wrapped in try/except)

Files:

- memory/migrate_history.py

---

## New File Structure

```
memory/
    __init__.py
    models.py
    extractor.py
    segmenter.py
    retrieval.py
    review.py
    migrate_history.py
    README.md
    TODO.md
    docs/
        architecture.md
        semantic_memory.md
        segmentation.md
        retrieval.md
        fsrs.md
```