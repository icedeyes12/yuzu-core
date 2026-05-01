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
Segmentation (memory.py) — Batch LLM + time-gap triggers
        ↓
Episodic Memory (extractor.py) — Summarized events
        ↓
Semantic Extraction (pcl.py) — Predict-Calibrate Learning
        ↓
Retention & Decay (review.py) — FSRS for episodic only
        ↓
Context Retrieval (retrieval.py) — RRF + hybrid scoring
        ↓
LLM Context Builder (orchestrator.py)
```

---

## Module Structure

```
memory/
├── __init__.py
├── memory.py             # Background pipeline + batch segmentation
├── db_memory.py          # Unified CRUD over semantic_facts
├── db_memory_queries.py  # SQL constants + query builders (NEW)
├── embedder.py           # Chutes API (Qwen3, 1024-dim)
├── extractor.py          # Semantic + episodic + PCL wiring
├── retrieval.py          # RRF + hybrid scoring
├── review.py             # FSRS decay (episodic only)
├── memory_review.py      # LLM-based memory review
├── pcl.py                # Predict-Calibrate Learning
└── docs/
    └── architecture.md   # Single source of truth
```

**Removed/Deprecated:**
- `segmenter.py` — merged into `memory.py`
- `models.py` — deleted (no ORM layer)
- `vector_store.py` — deprecated stub

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
    valid_at TIMESTAMP,    -- When fact became true (plast-mem pattern)
    created_at TIMESTAMP,
    last_accessed TIMESTAMP,
    invalid_at TIMESTAMP   -- Soft delete — NULL = active
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

**Library**: `fsrs>=6.3.1` — Free Spaced Repetition Scheduler

```python
from fsrs import FSRS, Card, Rating

# FSRS state transitions (aligned with plast-mem)
fsrs = FSRS(w=DEFAULT_PARAMETERS)
card = Card(stability=current_stability, difficulty=current_difficulty)
next_card, _ = fsrs.repeat(card, rating)
```

Semantic facts use `invalid_at` for temporal validity, no decay.

---

## Implementation Status

- ✅ Database schema (PostgreSQL + pgvector)
- ✅ Memory extraction (LLM-based)
- ✅ Conversation segmentation (batch LLM + temporal fast-path)
- ✅ Retrieval pipeline (RRF + hybrid)
- ✅ Context builder integration
- ✅ Review & decay system (FSRS library)
- ✅ Migration from SQLite
- ✅ PCL pipeline + LLM review
- ✅ SQL constants extracted (db_memory_queries.py)
- ✅ Logging migration (all print() → logging)
- ✅ plast-mem alignment verified
- ✅ **FSRS library integration** (fsrs>=6.3.1)
- ✅ **Temporal fast-path segmentation**
- ✅ **Flashbulb memory boost**

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
4. SQL constants go in `db_memory_queries.py`
5. Semantic = `static`, Episodic/Segments = `dynamic`
6. Use `logging` module, not `print()`

### Performance

- **Vector Search**: Exact Nearest Neighbor (Sequential Scan) — no HNSW/IVFFlat index due to SIGILL on Termux ARM
- **Current Scale**: 3,500+ rows, ~36ms query time (acceptable for real-time chat)
- **Max Scale**: ~50,000 rows before performance degradation
- **Recall**: 100% perfect (no approximation from ANN index)
