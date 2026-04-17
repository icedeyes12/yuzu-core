# Yuzu Memory System

Long-term memory architecture for persistent, evolving AI companion relationships.

## Core Principles

| Principle | Description |
|-----------|-------------|
| **Separation** | Episodic (events) vs Semantic (facts) vs Working (recent) |
| **First-class** | Dedicated subsystem with scoring, decay, retrieval |
| **Importance-driven** | High-importance = long-term anchors, low = fades |
| **Composed context** | Relevant memories injected, not raw history dump |

---

## Architecture Overview

```
Conversation History
        ↓
Segmentation (segmenter.py) — Dual-channel: time-gap + LLM
        ↓
Episodic Memory (extractor.py) — Summarized events
        ↓
Semantic Extraction (extractor.py) — Facts via PCL pipeline
        ↓
Retention & Decay (review.py) — FSRS for episodic only
        ↓
Context Retrieval (retrieval.py) — RRF + hybrid scoring
        ↓
LLM Context Builder (app.py)
```

---

## Module Structure

```
memory/
├── __init__.py
├── db_memory.py         # Unified CRUD over semantic_facts
├── embedder.py          # Chutes API (Qwen3, 1024-dim)
├── extractor.py         # Semantic + episodic + PCL wiring
├── segmenter.py         # Dual-channel segmentation
├── retrieval.py         # RRF + hybrid scoring
├── review.py            # FSRS decay (episodic only)
├── memory_review.py     # LLM-based memory review
├── pcl.py               # Predict-Calibrate Learning
├── vector_store.py      # DEPRECATED: stub
└── docs/
    └── architecture.md  # Single source of truth
```

---

## Database: `semantic_facts`

```sql
CREATE TABLE semantic_facts (
    id SERIAL PRIMARY KEY,
    session_id INTEGER,
    fact_type VARCHAR(20),  -- 'static' | 'dynamic'
    content TEXT,
    embedding VECTOR(1024),
    metadata JSONB,
    created_at TIMESTAMP,
    last_accessed TIMESTAMP,
    invalid_at TIMESTAMP    -- Soft delete
);
```

**Indexes:** IVFFlat on `embedding`, GIN on `metadata`

---

## Memory Types

| Type | fact_type | Decay | Description |
|------|-----------|-------|-------------|
| **Semantic** | `static` | No | Facts (entity, relation, target) |
| **Episodic** | `dynamic` | FSRS | Summarized events |
| **Segments** | `dynamic` | FSRS | Conversation chunks |

---

## Retrieval

**Scoring:**
```
score = similarity × 0.6 + importance × 0.2 + confidence × 0.2
```

**RRF Merge:**
```
RRF_score = Σ 1.0 / (k + rank), k=60
```

---

## FSRS Retention (Episodic Only)

```
importance = importance × exp(-hours_since_last_access / stability)
stability = 24 × (1 + access_count × 0.5)
```

Semantic facts use `invalid_at` for temporal validity, no decay.

---

## Implementation Status

- ✅ Database schema (PostgreSQL + pgvector)
- ✅ Memory extraction (LLM-based)
- ✅ Conversation segmentation (dual-channel)
- ✅ Retrieval pipeline (RRF + hybrid)
- ✅ Context builder integration
- ✅ Review & decay system (FSRS)
- ✅ Migration from SQLite
- ✅ PCL pipeline + LLM review

---

## 8-Category Taxonomy

Every semantic fact assigned one category:

| Category | Captures |
|----------|----------|
| Identity | name, profession, location |
| Preference | likes, dislikes, favorites |
| Interest | topics, hobbies, domains |
| Personality | communication style, tendencies |
| Relationship | dynamics, shared routines |
| Experience | skills, past events |
| Goal | plans, aspirations |
| Guideline | how assistant should behave |

---

## Contribution

1. Read `docs/architecture.md` — single source of truth
2. Follow 8-category taxonomy
3. Use `db_memory.py` for all memory operations
4. Semantic = `static`, Episodic/Segments = `dynamic`
