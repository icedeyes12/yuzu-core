# Memory System Alignment Roadmap

Align `yuzu-companion` with `plast-mem` architecture.
Branch: `feature/memory-system-alignment`

> **Decisions locked:**
> - Target embedding dimension: **1024** (model: `Qwen/Qwen3-Embedding-0.6B`)
> - BM25: **skipped** (pg_bm25 unavailable on Termux/PostgreSQL) — pure vector + RRF only
> - Job queue: **inline/synchronous** (no background worker — keep it simple)

---

## Phase 0: Pre-flight Checks

- [x] **0.1** Verify current branch is `feature/memory-system-alignment`
- [x] **0.2** Run `ruff check app/memory/` — must be clean before starting
- [x] **0.3** Run `python3 -m py_compile` on all memory modules
- [ ] **0.4** Confirm PostgreSQL is reachable and `semantic_facts` table exists
- [ ] **0.5** Backup current `app/memory/docs/architecture.md`

---

## Phase 1: Fix `search_similar` (Critical Bug)

> **Problem:** Triple placeholder (`vec_str`/`vec_str2`/`vec_str3`) with a dead `AS distance` alias. The `ORDER BY embedding <=> %s` references a bare expression that isn't in the SELECT list, and the result's `distance` key comes from nowhere.

### 1.1 — Rewrite the query cleanly
- [x] Replace the three-vec pattern with a single normalized vector string
- [x] Remove the unused `AS distance` column alias
- [x] Compute distance once in SELECT, reuse in WHERE and ORDER BY via subquery or CTE
- [x] Verify param count matches placeholder count exactly

### 1.2 — Integration test
- [ ] Run: `python3 -c "from app.memory.db_memory import search_similar; r=search_similar([0.1]*1024,limit=3); print('ok:', len(r))"`
- [ ] Confirm no `IndexError: list index out of range`

---

## Phase 2: Switch Embedding Model to 1024-dim

### 2.1 — Update `embedder.py`
- [x] Change `CHUTES_EMBED_ENDPOINT` to `https://chutes-qwen-qwen3-embedding-0-6b.chutes.ai/v1/embeddings`
- [x] Change `DEFAULT_MODEL` to `Qwen/Qwen3-Embedding-0.6B`
- [x] Change `EMBEDDING_DIM` from `4096` to `1024`
- [x] Update docstring to reflect the model change

### 2.2 — Add dimension guard
- [ ] In `db_memory.save_fact`: assert `len(embedding) == 1024` before saving
- [ ] In `embedder.embed_texts`: validate returned vector length, raise if mismatched

### 2.3 — Re-embed all existing memories
- [ ] Write `scripts/reembed_all.py` that:
  - Fetches all rows from `semantic_facts` where `embedding IS NOT NULL`
  - Re-embeds each `content` using the new 1024-dim model
  - Updates the `embedding` column in batches
- [ ] Run the re-embed script — confirm row count updated
- [ ] Verify: `SELECT id, vector_dims(embedding) FROM semantic_facts LIMIT 10`

### 2.4 — Update architecture doc
- [ ] Update `EMBEDDING_DIM` reference in `app/memory/docs/architecture.md`

---

## Phase 3: Add Reciprocal Rank Fusion (RRF) Without BM25

### 3.1 — Implement RRF merge
- [ ] In `retrieval.py`, add `_rrf_merge(list_a, list_b, k=60)` function
- [ ] RRF formula: `score = Σ 1.0 / (k + rank)` per list
- [ ] Each input is a list of `(db_id, value)` dicts with a `score` key

### 3.2 — Dualsignal retrieval (no BM25 fallback)
- [ ] `retrieve_static_memories`: call `search_similar` (vector) — keep as-is for now
- [ ] `retrieve_dynamic_memories`: call `search_similar` (vector) — keep as-is for now
- [ ] Future: when BM25 becomes available, add it as a third signal

### 3.3 — Verify RRF scoring
- [ ] Confirm `_score_fact` applies after RRF: `similarity * 0.6 + importance * 0.2 + confidence * 0.2`
- [ ] Add unit test: `_rrf_merge([{id:1, score:0.9}], [{id:2, score:0.8}], k=60)` — verify ordering

---

## Phase 4: Semantic Memory — 8-Category + Soft Delete

### 4.1 — Add `category` to metadata
- [ ] Update `save_fact` / `upsert_fact` to accept explicit `category` param
- [ ] `memory_store.py` — ensure `category` is stored in metadata correctly
- [ ] `extractor.py` — map LLM relation output to category name

### 4.2 — Add `category` filter to `search_similar`
- [ ] `search_similar(..., category: str | None = None)` — filter on `metadata->>'category'`
- [ ] Update `retrieve_static_memories(query, limit, category=None)` to pass category

### 4.3 — Add `invalid_at` column (soft delete)
- [ ] Run ALTER: `ALTER TABLE semantic_facts ADD COLUMN invalid_at TIMESTAMP NULL;`
- [ ] `invalidate_fact(id)` — sets `invalid_at = NOW()`
- [ ] `get_active_facts(...)` — add `WHERE invalid_at IS NULL` to all reads
- [ ] Update `delete_fact` to call `invalidate_fact` (soft delete by default)

### 4.4 — Add source tracking in metadata
- [ ] Add `source_episodic_ids: list[int]` to metadata
- [ ] On `upsert_semantic_memory` reinforce: **append** to `source_episodic_ids` instead of just incrementing `access_count`
- [ ] On `upsert_semantic_memory` new: initialize `source_episodic_ids = [episode_id]`

### 4.5 — Update `extractor.py` storage
- [ ] `upsert_semantic_memory`: pass `category` mapped from relation
- [ ] On duplicate: append to `source_episodic_ids`
- [ ] On new: insert with `source_episodic_ids = [episode_id]`

---

## Phase 5: Predict-Calibrate Learning (Inline)

### 5.1 — PREDICT phase
- [ ] `predict_episode_content(existing_facts, episode_title)` — LLM call to predict episode content from known facts
- [ ] `load_relevant_semantic_facts(conversation_id, limit=10)` — fetch top facts to feed prediction

### 5.2 — CALIBRATE phase
- [ ] `calibrate_and_extract(predicted_content, actual_messages)` — LLM call to identify gaps between prediction and reality
- [ ] Output: list of `{fact, category, action: new|reinforce|update|invalidate}`

### 5.3 — CONSOLIDATE phase
- [ ] `consolidate_facts(extracted_facts, conversation_id)` — apply actions to DB
- [ ] Deduplication: cosine similarity ≥ 0.95 → merge, not insert

### 5.4 — Mark episode consolidated
- [ ] Add `consolidated_at` field to episodic metadata
- [ ] After PCL: set `consolidated_at = NOW()` on the episode

### 5.5 — Wire into `process_messages_for_memory`
- [ ] After episodic creation → trigger inline `run_predict_calibrate`
- [ ] Keep it synchronous (no background worker per Phase 0 decision)

---

## Phase 6: Segmentation — LLM Dual-Channel

### 6.1 — LLM boundary detection
- [ ] Add `_llm_detect_boundary(segment_messages, prev_summary)` in `segmenter.py`
- [ ] LLM prompt: returns `{should_segment: bool, surprise_level: float, topic_shift: bool}`

### 6.2 — Flashbulb stability boost
- [ ] If `surprise_level >= 0.85`: boost episodic `importance` and `stability` in metadata
- [ ] Pass `surprise_level` to `create_episodic_memory`

### 6.3 — Dual-channel decision
- [ ] `_should_segment(messages)` → True if **either** time-gap rule **or** LLM says segment
- [ ] Keep time-gap as fast-path (no LLM for obvious breaks)

### 6.4 — Remove MIN_MESSAGES_PER_SEGMENT for final flush
- [ ] Already implemented — verify and add assertion test

---

## Phase 7: Fix FSRS Scope (Episodic Only)

### 7.1 — Remove static fact decay
- [x] In `review.py`: **remove** `decay_facts(fact_type=FACT_TYPE_STATIC)` — semantic facts should NOT decay
- [ ] Only decay dynamic/episodic facts (those with `source_table = 'episodic_memories'`)

### 7.2 — Update `decay_facts` docstring
- [x] Clarify it applies to episodic/dynamic only

### 7.3 — Verify
- [ ] After `run_decay(session_id=1)`: static fact `importance` values should be unchanged

---

## Phase 8: LLM Memory Review (Inline)

### 8.1 — Add review trigger
- [ ] After `retrieve_memory` returns results: mark retrieved memories as "pending review" (add `pending_review: bool` to metadata or use a separate `memory_reviews` table)

### 8.2 — LLM reviewer
- [ ] `review_memory(memory_content, conversation_context)` — LLM rates: Again/Hard/Good/Easy
- [ ] Map rating to FSRS parameter updates in metadata

### 8.3 — Apply FSRS updates
- [ ] **Again**: stability × 0.5
- [ ] **Hard**: stability × 0.9
- [ ] **Good**: stability × 1.2
- [ ] **Easy**: stability × 1.5
- [ ] Update `last_reviewed_at = NOW()`

### 8.4 — Wire into session start
- [ ] On session start: process any pending reviews before serving

---

## Phase 9: Fix `retrieve_segments` Alias

### 9.1 — Correct alias mapping
- [ ] `retrieve_segments` should NOT alias to `retrieve_dynamic_memories`
- [ ] Create dedicated `retrieve_segments(session_id, query, limit)` using `metadata_filter={"source_table": "conversation_segments"}`

### 9.2 — Update callers
- [ ] Find all callers of `retrieve_segments` — confirm they pass correct `session_id`
- [ ] Add integration test: store a segment, retrieve it via `retrieve_segments`

---

## Phase 10: Documentation Update

- [ ] Update `app/memory/docs/architecture.md` to reflect actual implementation
- [ ] Update `CHANGELOG.md` with all changes in this branch
- [ ] Update `app/README.md` if memory layer references changed
- [ ] Remove outdated `ROADMAP.md` references to SQLite/FAISS

---

## Phase 11: Final Verification

### 11.1 — Lint & compile
- [ ] `ruff check app/memory/ app/tools/memory_store.py app/db_pg.py` — must be clean
- [ ] `python3 -m py_compile` on all modified files

### 11.2 — Runtime tests
- [ ] `search_similar` returns results without crash
- [ ] `retrieve_memory(1, "test")` returns `{static, dynamic, temporal_messages}`
- [ ] `process_messages_for_memory` stores and retrieves facts
- [ ] `run_decay` completes without error
- [ ] New embedding dimension (1024) is confirmed in DB: `SELECT id, vector_dims(embedding) FROM semantic_facts LIMIT 5`

### 11.3 — Commit & push
- [ ] `git add . && git co-author "feat: align memory system with plast-mem (1024-dim, RRF, categories, soft-delete, PCL)"`
- [ ] `git push -u origin feature/memory-system-alignment`
