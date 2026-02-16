# Memory System Implementation TODO

This document tracks the staged rollout of the memory subsystem.

---

## Phase 1 — Episodic Memory (Foundation)

Goal:
Create structured episodic memory from message logs.

Tasks:

- [ ] Create `episodic_memory` table
- [ ] Implement segmentation module
- [ ] Fixed-window episode creation
- [ ] Episode summarization
- [ ] Importance scoring
- [ ] Store episodes in database

Files:

- memory/segmentation.py
- memory/episodic.py

---

## Phase 2 — Semantic Memory

Goal:
Extract stable user facts.

Tasks:

- [ ] Create `semantic_memory` table
- [ ] Extract semantic triples from episodes
- [ ] Merge duplicate facts
- [ ] Implement confidence scoring

Files:

- memory/semantic.py

---

## Phase 3 — Retrieval Integration

Goal:
Replace current context builder.

Tasks:

- [ ] Implement retrieval logic
- [ ] Semantic memory retrieval
- [ ] Episodic memory ranking
- [ ] Combine with recent messages
- [ ] Replace `_build_generation_context()`

Files:

- memory/retrieval.py
- memory/context_builder.py

---

## Phase 4 — Retention Model

Goal:
Enable memory decay and reinforcement.

Tasks:

- [ ] Add stability/difficulty fields
- [ ] Implement retrievability updates
- [ ] Reinforcement logic
- [ ] Periodic decay process

Files:

- memory/episodic.py
- memory/scheduler.py

---

## Phase 5 — Background Scheduler

Goal:
Automate memory maintenance.

Tasks:

- [ ] Scheduler loop
- [ ] Periodic segmentation
- [ ] Semantic extraction
- [ ] Retention updates

Files:

- memory/scheduler.py

---

## Phase 6 — Scaling (Optional)

Goal:
Prepare for large-scale memory.

Tasks:

- [ ] Migrate to PostgreSQL
- [ ] Add indexes
- [ ] Convert JSON fields to JSONB