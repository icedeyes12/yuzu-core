# Memory Architecture

This document defines the structure, database schema, and implementation
phases of the long-term memory system used by the Yuzu companion.

The memory subsystem transforms raw chat logs into structured, retrievable,
and scalable memory layers.

---

## Memory Layers

The system is divided into three main layers:

1. Raw message log
2. Episodic memory (events)
3. Semantic memory (facts)

Each layer has a dedicated table and processing logic.

---

## Database Schema

### 1. messages (existing)

Source-of-truth conversation log.

Columns:
- id (INTEGER, PK)
- session_id (INTEGER)
- role (TEXT)
- content (TEXT)
- timestamp (TEXT)
- image_paths (TEXT, nullable)

No changes required in this table.

---

### 2. episodic_memory (new)

Represents summarized conversation segments.

Table: episodic_memory

Columns:

- id (INTEGER, PK)
- session_id (INTEGER, indexed)
- start_message_id (INTEGER)
- end_message_id (INTEGER)
- summary (TEXT)

Scoring fields:
- importance_score (REAL)
- surprise_score (REAL)

Retention fields:
- stability (REAL)
- difficulty (REAL)
- retrievability (REAL)

Usage fields:
- retrieval_count (INTEGER, default 0)
- last_accessed_at (TEXT)

Metadata:
- created_at (TEXT)

Indexes:
- session_id
- importance_score
- retrievability

---

### 3. semantic_memory (new)

Stores abstracted user or relationship knowledge.

Table: semantic_memory

Columns:

- id (INTEGER, PK)

Triple:
- entity (TEXT)
- relation (TEXT)
- target (TEXT)

Confidence:
- confidence (REAL)

Source:
- source_episodic_ids (TEXT, JSON array)

Usage:
- access_count (INTEGER, default 0)
- last_accessed_at (TEXT)

Metadata:
- created_at (TEXT)

Indexes:
- entity
- relation
- confidence

---

## Directory Structure

memory/ ├── README.md ├── todo.md ├── episodic.py ├── semantic.py ├── segmentation.py ├── retrieval.py ├── context_builder.py ├── scheduler.py └── docs/ ├── architecture.md ├── episodic_memory.md ├── semantic_memory.md ├── segmentation.md ├── retrieval.md └── fsrs.md

---

## Core Modules

### episodic.py
Responsible for:

- Creating episodic memory records
- Scoring importance and surprise
- Managing stability and retrievability

---

### semantic.py
Responsible for:

- Extracting semantic facts from episodes
- Updating or merging existing facts
- Managing confidence scores

---

### segmentation.py
Responsible for:

- Dividing raw messages into episodes
- Detecting boundaries

Initial version:
- Fixed message window segmentation

---

### retrieval.py
Responsible for:

- Selecting relevant episodic memories
- Selecting semantic facts
- Ranking results

---

### context_builder.py
New context builder that replaces the current:

_build_generation_context()

Responsibilities:

1. Load system message
2. Retrieve semantic memory
3. Retrieve episodic memory
4. Append recent messages
5. Produce final prompt context

---

### scheduler.py
Background memory maintenance:

- Episode creation
- Semantic extraction
- FSRS updates

Runs periodically or after message thresholds.

---

## High-Level Flow

User message ↓ messages table ↓ segmentation.py ↓ episodic_memory ↓ semantic.py ↓ semantic_memory ↓ retrieval.py ↓ context_builder.py ↓ LLM

---

## Implementation Phases

### Phase 1 — Database & Episodic Layer

Files:
- memory/episodic.py
- memory/segmentation.py

Tasks:
- Create episodic_memory table
- Implement fixed-window segmentation
- Store episode summaries

No semantic memory yet.

---

### Phase 2 — Semantic Layer

Files:
- memory/semantic.py

Tasks:
- Create semantic_memory table
- Extract semantic facts from high-importance episodes
- Merge duplicate facts

---

### Phase 3 — Retrieval Integration

Files:
- memory/retrieval.py
- memory/context_builder.py

Tasks:
- Replace current context builder
- Retrieve:
  - top semantic facts
  - top episodic memories
  - recent messages

---

### Phase 4 — Retention Model

Files:
- memory/episodic.py
- memory/scheduler.py

Tasks:
- Implement FSRS-like retrievability updates
- Add decay over time
- Reinforce frequently accessed memories

---

### Phase 5 — Background Processing

Files:
- memory/scheduler.py

Tasks:
- Run segmentation automatically
- Run semantic extraction
- Periodic memory maintenance

---

### Phase 6 — Database Migration (Optional)

If scaling beyond SQLite:

Target:
- PostgreSQL

Changes:
- Replace SQLite engine
- Add proper indexing
- Add JSONB for semantic source references

No logic changes required.

---

## Integration Points

### app.py

Replace:

`_build_generation_context()`

With:

`memory.context_builder.build_context()`

All memory logic must stay inside the `memory/` module.

---

## Performance Goals

Target limits:

- Context assembly: < 50 ms
- Episodic retrieval: top 5–10 episodes
- Semantic retrieval: top 10–20 facts

Avoid:

- Full history summarization
- Reprocessing entire message logs