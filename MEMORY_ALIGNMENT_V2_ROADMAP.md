# Memory System Alignment Roadmap — V2

Align `yuzu-companion` with `plast-mem` architecture.
Branch: `feature/memory-system-alignment-v2`

> **Decisions locked:**
> - Target embedding dimension: **1024** (model: `Qwen/Qwen3-Embedding-0.6B`)
> - Termux-compatible search stack: **`pgvector`** (ANN) + **`pg_trgm`** (keyword/fuzzy) — replaces ParadeDB BM25
> - Hybrid search: RRF merge of pgvector channel + pg_trgm channel
> - Job queue: **inline/synchronous** (no background worker)

---

## Background: Termux Search Stack

| Feature | ParadeDB / pg_search | Termux Replacement |
|---|---|---|
| Semantic ANN search | `bm25_search()` / `pg_search` | `pgvector` (`<=>` cosine, HNSW/IVFFlat) ✅ done |
| Fuzzy / keyword match | Tantivy trigram | `pg_trgm` (`%` similarity operator + GIN index) ✅ done |
| Hybrid search | Built-in BM25 + vector RRF | SQL RRF merge of two channels 🔴 **MISSING** |

This roadmap fills the two missing pieces so retrieval has **both** vector similarity AND keyword/fuzzy matching — matching what plast-mem gets from ParadeDB.

---

## Phase 0: Pre-flight Checks

- [x] **0.1** Verify current branch is `feature/memory-system-alignment-v2`
- [x] **0.2** Run `ruff check app/memory/ app/tools/memory_store.py app/db_pg.py` — must be clean
- [x] **0.3** Run `python3 -m py_compile` on all memory modules
- [x] **0.4** Confirm PostgreSQL is reachable and `semantic_facts` table exists
- [x] **0.5** Confirm `pgvector` extension is installed: `SELECT extname FROM pg_extension WHERE extname = 'vector';`
- [x] **0.6** Check `pg_trgm` availability: `SELECT extname FROM pg_extension WHERE extname = 'pg_trgm';`

---

## Phase 1: Add pg_trgm Extension + Index

### 1.1 — Enable pg_trgm in PostgreSQL

Run once (superuser or owned DB):

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

Update `db_pg_models.py` or `scripts/setup_db.py` to include this in the extension setup.

### 1.2 — Add GIN trigram index on content

```sql
CREATE INDEX IF NOT EXISTS semantic_facts_content_trgm_idx 
  ON semantic_facts USING gin (content gin_trgm_ops);
```

Also add a `tsvector` column for full-text search as a secondary option:

```sql
ALTER TABLE semantic_facts ADD COLUMN tsv tsvector 
  GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;
CREATE INDEX IF NOT EXISTS semantic_facts_tsv_idx ON semantic_facts USING gin (tsv);
```

### 1.3 — Create migration script

- [x] `scripts/add_trgm_extension.sql` — the SQL above
- [ ] Document in `INSTALL.md` that `pg_trgm` is required

---

## Phase 2: pg_trgm Search Function

### 2.1 — Add `search_trgm` to `db_memory.py`

```python
def search_trgm(
    query: str,
    session_id: int | None = None,
    fact_type: str | None = None,
    limit: int = 15,
    similarity_threshold: float = 0.3,
) -> list[dict]:
    """
    Keyword/fuzzy search via pg_trgm similarity.
    
    Uses the `%` (similarity) operator with a GIN index.
    Falls back to `ILIKE %%` substring match if similarity returns nothing.
    
    Returns list of dicts: {id, content, fact_type, metadata,
                            last_accessed, created_at, similarity}
    """
```

Logic:
1. Build conditions: `fact_type`, optional `session_id` filter, `invalid_at IS NULL`
2. Run similarity query: `SELECT ..., similarity(content, query) AS similarity FROM semantic_facts WHERE content % %s ORDER BY similarity DESC`
3. If results < limit, also fetch ILIKE matches as fallback
4. Return merged + deduped results sorted by similarity

### 2.2 — Add to `embedder.py` or create `_normalize_trgm_output`

- Normalize similarity score to 0.0–1.0 range for RRF compatibility

### 2.3 — Add `LIMIT` and `similarity_threshold` tuning

- Default threshold 0.3 (pg_trgm default)
- Allow override per query type (semantic static facts can be stricter)

---

## Phase 3: Hybrid RRF — Vector + Trgm Channels

### 3.1 — Refactor `_rrf_merge` to accept scored lists

Current `retrieval.py` `_rrf_merge` takes `list_a, list_b`. Extend to:

```python
def _hybrid_rrf_merge(
    vector_results: list[dict],   # from pgvector search
    trgm_results: list[dict],     # from pg_trgm search  
    k: int = 60,
) -> list[dict]:
```

- Both inputs already have a `distance` (vector) or `similarity` (trgm) field
- Normalize to a common `score` key before RRF
- RRF formula: `score = Σ 1.0 / (k + rank)` per channel

### 3.2 — Update `retrieve_static_memories` to use hybrid search

Current flow:
```
query → embed_text → search_similar (vector) → return
```

New flow:
```
query → embed_text → search_similar (vector) ─┐
query ───────────→ search_trgm (keyword)  ────┼→ _hybrid_rrf_merge → return
```

- Run vector and trgm searches in parallel (or sequential if threading not needed)
- Pass merged results through `_score_fact` for final ranking

### 3.3 — Update `retrieve_dynamic_memories` same way

- Episodic memories also benefit from keyword matching (e.g., searching "tidur" finds session summaries with that word)

### 3.4 — Add `include_trgm=True/False` parameter

- Allow callers to disable trgm channel when doing pure semantic similarity (e.g., "things similar to X")
- Default: `True`

### 3.5 — Test hybrid scoring

```
python3 -c "
from app.memory.retrieval import retrieve_static_memories, _hybrid_rrf_merge
from app.memory.db_memory import search_similar, search_trgm
from app.memory.embedder import embed_text

q = 'tidur'
vec = embed_text(q)
vr = search_similar(vec, fact_type='static', limit=15)
tr = search_trgm(q, fact_type='static', limit=15)
merged = _hybrid_rrf_merge(vr, tr)
print(f'Vector: {len(vr)}, Trgm: {len(tr)}, Merged: {len(merged)}')
"
```

---

## Phase 4: PostgreSQL Full-Text Search Channel (tsvector)

> This is an **optional enhancement** on top of pg_trgm. It provides rank-ordered full-text matching.

### 4.1 — Add `search_tsv` function

```python
def search_tsv(
    query: str,
    session_id: int | None = None,
    fact_type: str | None = None,
    limit: int = 15,
) -> list[dict]:
```

Uses `plainto_tsquery` + `ts_rank_cd` for weighted full-text ranking.

### 4.2 — Three-channel RRF (optional)

If `search_tsv` is implemented, extend `_hybrid_rrf_merge` to:

```
vector_results ─┐
trgm_results   ─┼→ _hybrid_rrf_merge(k=60) → final ranked list
tsv_results    ─┘
```

---

## Phase 5: Fix Retrieval — FSRS Retrievability Re-rank (episodic only)

### 5.1 — Add retrievability factor to episodic scoring

In `plast-mem`, episodic results are re-ranked by:
```
 retrievability = exp(-hours_since_last_access / stability)
 final_score = rrf_score * retrievability
```

Currently yuzu-companion does NOT apply this re-rank. Add it:

### 5.2 — Update `_score_fact` for dynamic facts

In `retrieval.py`, when scoring a dynamic/episodic fact:

```python
def _episodic_score(r: dict) -> float:
    """Hybrid score with FSRS retrievability for episodic memories."""
    base = _score_fact(r)  # similarity * 0.6 + importance * 0.2 + confidence * 0.2
    meta = r.get("metadata", {})
    last_accessed = r.get("last_accessed")
    
    # Apply retrievability if stability is present
    stability = meta.get("stability", 24.0)  # default 24h half-life
    retrievability = _recency_factor(last_accessed)  # already computed
    # stability modifier: higher stability → slower decay
    retrievability = math.exp(-retrievability / max(stability, 0.1))
    
    return base * (0.5 + 0.5 * retrievability)
```

### 5.3 — Only apply to dynamic/episodic facts

Static (semantic) facts do NOT get FSRS re-ranking — they use pure hybrid score.

### 5.4 — Verify

```
python3 -c "
from app.memory.retrieval import retrieve_dynamic_memories
r = retrieve_dynamic_memories(session_id=1, query='test')
for item in r:
    meta = item.get('metadata', {})
    print(f'  id={item[\"id\"]} stability={meta.get(\"stability\")} score={item[\"score\"]:.3f}')
"
```

---

## Phase 6: Fix Retrieval — `context_pre_retrieve` (Semantic-Only)

### 6.1 — Add dedicated semantic-only retrieval [DONE]

In `plast-mem`, `POST /api/v0/context_pre_retrieve` returns only semantic (static) facts for pre-LLM system prompt injection — without recording pending review.

Create:

```python
def retrieve_for_context(session_id: int, query: str | None = None, limit: int = 10) -> str:
    """
    Retrieve ONLY static semantic memories for context injection.
    Does NOT mark facts as pending_review.
    Returns formatted string for system prompt.
    """
    static = retrieve_static_memories(query=query, limit=limit)
    # Format as context string (no "pending review" markers)
    return _format_static_context(static)
```

### 6.2 — Update `format_memory` to have two modes [DONE]

- `format_memory()` — full context with pending review markers (existing)
- `_format_static_context()` — clean context for system prompt injection (new)

### 6.3 — Update callers in `app.py` [DONE]

Find all places where memory is injected into the system prompt. Confirm they use the semantic-only path when appropriate.

---

## Phase 7: Add `pending_review` as Native Column

### 7.1 — Migration

Current: `pending_review` is stored as JSONB `metadata->>'pending_review'` and queried as:
```sql
WHERE (metadata->>'pending_review')::bool = true
```

This works but is slow at scale. Add native boolean column:

```sql
ALTER TABLE semantic_facts 
  ADD COLUMN pending_review BOOLEAN NOT NULL DEFAULT FALSE;
  
UPDATE semantic_facts 
  SET pending_review = (metadata->>'pending_review')::bool 
  WHERE pending_review IS DISTINCT FROM (metadata->>'pending_review')::bool;
```

### 7.2 — Update `memory_review.py`

- `mark_retrieved_as_pending_review()` → write to native `pending_review` column
- `get_pending_review_count()` → query native column
- Keep JSONB in sync for backward compat, or update all reads to use the native column

### 7.3 — Add index on `pending_review`

```sql
CREATE INDEX IF NOT EXISTS semantic_facts_pending_review_idx 
  ON semantic_facts (pending_review) WHERE pending_review = TRUE;
```

---

## Phase 8: Background Job System (Optional — for Later)

> **Note:** This is out of scope for the current alignment push. Flagged for future.

- [ ] Add a `memory_jobs` table (message_queue equivalent in plast-mem)
- [ ] `SegmentationJob`, `PredictCalibrateJob`, `MemoryReviewJob` as deferred workers
- [ ] Move PCL and segmentation out of the hot request path

---

## Phase 9: Existing Phase Items — Verify & Close

### Phase 4.3 — `invalid_at` column (still unchecked)

```sql
ALTER TABLE semantic_facts ADD COLUMN invalid_at TIMESTAMP NULL;
```

- [x] Verify `invalid_at` column exists
- [x] Confirm `get_active_facts` filters correctly
- [ ] Run: `SELECT column_name FROM information_schema.columns WHERE table_name='semantic_facts' AND column_name='invalid_at';`

### Phase 6.4 — Remove MIN_MESSAGES_PER_SEGMENT assertion [DONE]

- [x] Verify final flush group is NOT subject to `MIN_MESSAGES_PER_SEGMENT` threshold

### Phase 8.4 — Verify session start wiring

- [x] Confirm `mark_retrieved_as_pending_review` fires on session start

---

## Phase 10: Final Verification

### 10.1 — Lint & compile
 - [x] `ruff check app/memory/ app/tools/memory_store.py app/db_pg.py`
- [x] `python3 -m py_compile` on all modified files

### 10.2 — Retrieval tests
```bash
# Hybrid search returns results
python3 -c "
from app.memory.retrieval import retrieve_static_memories, retrieve_dynamic_memories
s = retrieve_static_memories(query='tidur', limit=10)
d = retrieve_dynamic_memories(session_id=1, query='test', limit=5)
print(f'static={len(s)}, dynamic={len(d)}')
"

# search_similar (vector) still works
python3 -c "
from app.memory.db_memory import search_similar
from app.memory.embedder import embed_text
v = embed_text('test query')
r = search_similar(v, limit=3)
print(f'vector search: {len(r)} results')
"

# search_trgm (keyword) works
python3 -c "
from app.memory.db_memory import search_trgm
r = search_trgm('tidur', limit=5)
print(f'trgm search: {len(r)} results')
"
```

### 10.3 — DB state check
```sql
-- Confirm extensions
SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pg_trgm');

-- Confirm columns
SELECT column_name FROM information_schema.columns 
  WHERE table_name = 'semantic_facts' 
  AND column_name IN ('invalid_at', 'pending_review', 'tsv');

-- Confirm indexes
SELECT indexname FROM pg_indexes 
  WHERE tablename = 'semantic_facts';
```

### 10.4 — Commit
```bash
git add .
git co-author "feat: add pg_trgm hybrid search, FSRS retrievability, context_pre_retrieve (V2 alignment)"
```

---

## Priority Order (Suggested)

```
Phase 1  → Phase 2  → Phase 3  → Phase 5  → Phase 6  → Phase 7  → Phase 9  → Phase 10
(pg_trgm)  (search)   (hybrid)   (FSRS)     (pre_ctx)  (col)      (verify)   (final)
```

Phases 4 (tsvector) and 8 (jobs) are optional/ deferrable.

---

## Key File Changes Summary

| File | Changes |
|---|---|
| `app/memory/db_memory.py` | Add `search_trgm()`, `search_tsv()`, native `pending_review` column support |
| `app/memory/retrieval.py` | `_hybrid_rrf_merge()` (3-channel), `retrieve_for_context()`, FSRS retrievability scoring |
| `app/memory/memory_review.py` | Native `pending_review` column reads/writes |
| `app/db_pg_models.py` | Add `pg_trgm` to setup checklist |
| `scripts/add_trgm_extension.sql` | New — GIN index + tsvector column |
| `INSTALL.md` | Document `pg_trgm` requirement |
| `app/memory/docs/architecture.md` | Update retrieval diagram to show dual-channel RRF |
| `ROADMAP_MEMORY_ALIGNMENT.md` | Deprecate — this is V2 |
