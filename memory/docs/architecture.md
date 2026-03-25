# Memory Architecture

This document defines the structure, database schema, and implementation
phases of the long-term memory system used by the Yuzu companion.

The memory subsystem transforms raw chat logs into structured, retrievable,
and scalable memory layers.

---

## Memory Layers

The system is divided into three main layers:

1. Raw message log (`messages` table)
2. Episodic memory (`episodic_memory` table) — summarized conversation segments
3. Semantic memory (`semantic_memory` table) — abstracted user/relationship facts

Each layer has a dedicated table and processing logic.

---

## Database Schema

### 1. messages (existing)

Source-of-truth conversation log.

Columns:
- `id` (INTEGER, PK)
- `session_id` (INTEGER)
- `role` (TEXT)
- `content` (TEXT)
- `timestamp` (TEXT)
- `image_paths` (TEXT, nullable)

No changes required.

### 2. episodic_memory (new)

Represents summarized conversation segments.

Table: `episodic_memory`

Columns:
- `id` (INTEGER, PK)
- `session_id` (INTEGER, indexed)
- `summary` (TEXT) — LLM-generated 1-3 sentence summary
- `importance` (REAL) — 0.0–1.0, decays over time
- `emotional_weight` (REAL) — 0.0–1.0, triggers episodic creation
- `embedding` (BLOB) — vector of the summary for cosine similarity

Retention fields:
- `stability` (REAL)
- `difficulty` (REAL)

Usage fields:
- `retrieval_count` (INTEGER, default 0)
- `access_count` (INTEGER, default 0)
- `last_accessed` (DATETIME)

Metadata:
- `created_at` (DATETIME)

### 3. semantic_memory (new)

Stores abstracted user or relationship knowledge as RDF-like triples.

Table: `semantic_memory`

Columns:
- `id` (INTEGER, PK)

Triple:
- `entity` (TEXT)
- `relation` (TEXT)
- `target` (TEXT)

Confidence:
- `confidence` (REAL) — increases on duplicate facts
- `importance` (REAL) — decays over time

Source:
- `source_episodic_ids` (TEXT, JSON array)

Usage:
- `access_count` (INTEGER, default 0)
- `last_accessed` (DATETIME)
- `embedding_vector` (BLOB) — vector of "entity relation target" text

Metadata:
- `created_at` (DATETIME)

### 4. conversation_segments (new)

Structured message windows from raw segmentation.

Table: `conversation_segments`

Columns:
- `id` (INTEGER, PK)
- `session_id` (INTEGER, indexed)
- `start_message_id` (INTEGER)
- `end_message_id` (INTEGER)
- `summary` (TEXT)
- `importance` (REAL)
- `embedding` (BLOB)
- `created_at` (DATETIME)

---

## Directory Structure

```
memory/
├── __init__.py
├── embedder.py       # Chutes API client, vec↔blob, cosine similarity
├── extractor.py      # Semantic fact extraction, episodic summary (LLM)
├── segmenter.py     # Message window segmentation → conversation_segments
├── retrieval.py      # Cosine-similarity + hybrid scoring retrieval
├── review.py         # FSRS-style decay & reinforcement
├── models.py         # Re-export from database.py
└── docs/
    ├── architecture.md
    ├── retrieval.md
    ├── segmentation.md
    └── fsrs.md
```

---

## Core Modules

### embedder.py
Chutes API embedding client. Handles:
- `embed_text(text)` → single embedding
- `embed_texts(texts)` → batch embeddings
- `cosine_similarity(a, b)`
- `vec_to_blob(v)` / `blob_to_vec(b)` — SQLite BLOB serialization

### extractor.py
Memory extraction layer. Handles:
- `extract_semantic_facts(messages)` — regex-based triple extraction
- `calculate_emotional_weight(messages)` — keyword intensity scoring
- `should_create_episodic(messages)` — triggers episodic creation
- `generate_episodic_summary(messages)` — LLM summarization (fallback: truncation)
- `upsert_semantic_memory(...)` — insert or reinforce semantic triples
- `create_episodic_memory(...)` — store episodic with embedding
- `process_messages_for_memory(...)` — main pipeline entry point

### segmenter.py
Conversation segmentation engine. Handles:
- `_get_unsegmented_messages(session_id)` — fetch unsegmented messages
- `_detect_boundaries(messages)` — split by time gap (15 min) or size (20 msgs)
- `_create_segment(session_id, group)` — store `ConversationSegment`
- `segment_session(session_id)` — main entry, returns count created

### retrieval.py
Memory retrieval with cosine similarity + hybrid scoring. Handles:
- `_recency_factor(last_accessed)` — half-life 24h exponential decay
- `retrieve_semantic_memories(session_id, query, limit)` — score = sim×0.6 + importance×0.2 + confidence×0.2
- `retrieve_episodic_memories(session_id, query, limit)` — score = sim×0.5 + importance×0.25 + recency×0.25
- `retrieve_segments(session_id, query, limit)`
- `retrieve_memory(session_id, query)` — main entry, returns bundle
- `format_memory(memory_bundle)` — formats for system message injection

### review.py
FSRS-inspired retention model. Handles:
- `_hours_since(dt)` — time delta calculation
- `decay_semantic_memories(session_id)` — importance × exp(−hours/stability)
- `decay_episodic_memories(session_id)`
- `reinforce_memory(memory_id, memory_type)` — bump importance on retrieval
- `run_decay(session_id)` — full decay cycle

---

## High-Level Flow

```
User message
  ↓
messages table
  ↓
segmenter.segment_session()      → conversation_segments
  ↓
extractor.process_messages_for_memory()
  ├── extract_semantic_facts()   → semantic_memory
  └── should_create_episodic() → generate_episodic_summary() (LLM)
                               → episodic_memory
  ↓
review.run_decay()               → decay importance over time
  ↓
retrieval.retrieve_memory()      → context_builder builds prompt
  ↓
LLM (with memory-augmented context)
```

---

## Integration Points

### app.py / web.py

On session start:
```python
from memory.segmenter import segment_session
from memory.review import run_decay
from memory.extractor import process_messages_for_memory

segment_session(session_id)
run_decay(session_id)
process_messages_for_memory(session_id, recent_messages)
```

On retrieval (context building via `retrieval.retrieve_memory` + `format_memory`).

---

## Implementation Phases

### ✅ Phase 1 — Database & Episodic Layer
- `episodic_memory` table created
- Fixed-window segmentation via `segmenter.py`
- LLM-powered episodic summaries via `extractor.py`

### ✅ Phase 2 — Semantic Layer
- `semantic_memory` table created
- Regex-based fact extraction from user messages
- Duplicate merging via upsert logic

### ✅ Phase 3 — Retrieval Integration
- Hybrid scoring (cosine + importance + recency)
- Context formatting for LLM injection
- All wiring in app.py / web.py

### ✅ Phase 4 — Retention Model
- FSRS-inspired decay in `review.py`
- Stability derived from access_count
- Reinforcement on retrieval

### ✅ Phase 5 — Background Processing
- Segmentation on session start
- Decay on session start
- Semantic extraction on new messages

### Future — Phase 6 (optional PostgreSQL migration)
- Replace SQLite engine
- Add proper JSONB indexing for source_episodic_ids
- No logic changes required
