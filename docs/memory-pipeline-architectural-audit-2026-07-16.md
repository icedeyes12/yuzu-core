# Yuzu Companion — Memory Pipeline Architectural Audit

**Audit date:** 2026-07-16 (Asia/Jakarta)
**Scope:** static source inspection plus read-only PostgreSQL validation against the configured `yuzuki` database. No application code or database data was modified.

## Executive finding

The repeated-memory symptom is **not primarily a pgvector algorithm failure**. The strongest root cause is architectural:

1. **Per-turn prompt retrieval is accidentally routed through a synchronous implementation inside `asyncio.to_thread()`**, so it uses the sync DB path and a thread-local cache. That is not inherently wrong, but it creates a split runtime path that is difficult to observe and makes the prompt path different from the explicit async retrieval API.
2. **The prompt query is the current user message only**, while the injected global static memory pool contains a large cluster of persistent relationship/persona facts. The vector layer is demonstrably diverse, but the query distribution and the hybrid merge can repeatedly favor that stable cluster for semantically related conversational prompts.
3. **RRF is rank-only and does not use the actual similarity scores.** A result appearing in all three channels receives a large fixed advantage; the final parsed score is not used to reorder the fused result. This makes repeated cross-channel consensus dominate query-specific vector distance.
4. **Static facts are retrieved from a global per-user pool and are not recency- or diversity-aware.** The no-query path is explicitly `SELECT ... LIMIT` without `ORDER BY`; the query path returns at most five static facts to the prompt and applies no category/MMR/diversity suppression.
5. **Dynamic episodic memories are session-scoped, not independent-session global memories.** A new session cannot retrieve dynamic memories from prior sessions through the prompt path. Cross-session continuity therefore depends almost entirely on static facts and `profiles.global_knowledge`.
6. **The extraction/persistence pipeline is highly lossy and backlog-prone.** It triggers only at 40/50 conversational-message deltas, processes at most 100 messages per run, and can process only the first 100 of a large backlog before marking state using the total message count. This can permanently skip the remainder of a backlog.
7. **The database contains 14,079 messages but only 2,362 fact rows, of which 1,300 are active.** This is not evidence that thousands of messages should produce thousands of retrievable facts: the extractor deliberately compresses, skips low-importance segments, caps categories, deduplicates, invalidates, and runs only when gates pass.

**Most likely immediate cause of “nearly identical” prompt memories:** stable semantic/persona facts plus rank-only RRF and a five-item static prompt cap. The code also contains a separate async persistence defect: the async last-access update is called with `user_id`, but the underlying async function does not accept it and its SQL requires it; this is a confirmed code-path defect, while the exact historical runtime impact is not reconstructed from logs. The vector store itself is not collapsed: sampled active vectors have average pairwise cosine similarity ≈ 0.427, average cosine distance ≈ 0.573, and only 146/2,362 rows have NULL embeddings.

## 1. Complete architecture diagram

```mermaid
flowchart TD
    A[User turn] --> B[orchestrator.handle_user_message*]
    B --> C[Persist user message\nmodels_async.add_message_async]
    C --> D[LLM prompt build\nprompts.build_messages]
    D --> E[_retrieve_memories_async]
    E --> F[retrieve_memories_combined_async]
    F --> G[asyncio.to_thread]
    G --> H[retrieve_memories_combined sync path]
    H --> I[Query embedding\nembedder.embed_text]
    H --> J[pgvector search\nsemantic_facts.embedding <=> query]
    H --> K[pg_trgm search\nsimilarity(content, query)]
    H --> L[tsvector search\ntsv @@ plainto_tsquery]
    J --> M[Rank-only RRF]
    K --> M
    L --> M
    M --> N[_parse_fact_content + _format_*_context]
    N --> O[Static max 5 + dynamic max 3]
    O --> P[System prompt\nlegacy string OR structured JSON payload]
    P --> Q[LLM]
    Q --> R[Persist assistant/tool messages]
    R --> S[MemoryService post-turn checks]
    S --> T[Every 50 message-count boundary]
    T --> U[trigger_memory_pipeline_async]
    U --> V[40/50 delta + idle/fence gates]
    V --> W[run_memory_pipeline_async]
    W --> X[Fetch unsegmented user+assistant messages]
    X --> Y[Temporal or LLM batch segmentation]
    Y --> Z[Episode creation\ndynamic fact + embedding]
    Z --> AA[PCL predict/calibrate/consolidate]
    AA --> AB[Static fact upsert + embedding]
    AB --> AC[semantic_facts]
    AC --> J
```

## 2. Stage-by-stage walkthrough

| Stage | Input | Output | Responsible module/function | Transformation | Failure/weakness |
|---|---|---|---|---|---|
| Conversation capture | User/assistant/tool turn | `messages` row | `app/orchestrator.py`, `_persist_user_async`, `_persist_assistant_async`; `app/db/models_async.py`, `add_message_async` | Stores role, text, session/user IDs, attachments, tool calls, turn ID; DB timestamp is `NOW()` | 14,079 rows include 1,222 system, 937 image-tool, 65 tool, and other tool roles. Memory extraction later ignores all but user/assistant. Historical null-session rows exist (494). |
| Extraction window | Session message history | unsegmented list | `app/memory/memory.py`, `run_memory_pipeline_async` | If state has `last_segmented_message_id`, fetches `id > last_id`; otherwise fetches up to 10,000 and slices after `last_segmented_count`; filters role to user/assistant | `id > last_id` uses message IDs as processing order, while timestamps can be historical/imported. Initial count slicing is fragile. Hard cap 100. |
| Trigger | Current conversational count and memory state | background job | `MemoryService.run_per_message_checks_async`; `should_trigger_segmentation_async` | Checks only when `msg_count % 50 == 0`; then delta thresholds 40/50 and idle gate 3h unless force | Missed exact boundaries, fire-and-forget tasks, 5-minute debounce, and fence state can delay processing. |
| Segmentation | Up to 100 user/assistant messages | segment ranges/title/summary/surprise | `batch_segment_async`, `_apply_temporal_segmentation`, `_llm_batch_segment_async`, `_enhance_temporal_segments_async` | 30-minute timestamp gaps create temporal segments; otherwise one LLM JSON call; small segments merged | LLM parse fallback can create empty/poor segments. Temporal path sets surprise 0.2. Segment summaries are truncated/fallback text. |
| Episode/memory object | Segment + source messages | dynamic fact object | `create_episode_and_pcl_async` | `importance = 0.5 + surprise*0.3`; skips below 0.45; content is `title + summary`; metadata stores source message range/session/stability | The current threshold does not skip default low surprise because 0.56 >= 0.45. Dynamic objects are session-scoped and often are large conversation summaries rather than atomic memories. |
| Semantic extraction | Episode summary, actual segment messages, existing static facts | PCL actions | `app/memory/pcl.py`, `predict_episode_content_async`, `calibrate_and_extract_async` | Predict existing-fact topics; calibrate actual messages into `new/reinforce/update/invalidate`; normalize categories | Extraction is LLM-dependent, noise filtering is prompt-only, source IDs are model-provided, and assistant content is included as “AI” context. |
| Deduplication | Candidate fact text and embedding | reinforce or insert | `app/memory/extractor.py`, `upsert_semantic_memory_async`; `MemoryDB.save_fact_async` | Embeds `User relation target`; vector distance threshold 0.03; exact content check; DB duplicate check | Exact duplicate check is not unique-constrained and is race-prone. Vector dedupe is only evaluated against query-scoped results. Category caps can suppress new facts. |
| Persistence | Fact text, vector, metadata | `semantic_facts.id` | `app/memory/db_memory.py`, `save_fact_async`; SQL in `db_memory_queries.py` | Normalizes vector, validates 4096 dimensions, inserts JSONB metadata, soft-invalidates with `invalid_at` | Insert errors return `None`; some callers only log. Several direct updates omit `user_id` in PCL episode metadata updates. Live DB retains migration columns (`memory_json`, `embedding_1536`) not represented in current DDL. |
| Embedding generation | Fact/episode/query text | 4096-float vector or `None` | `app/memory/embedder.py`, Chutes Qwen3 Embedding 8B endpoint | Single-request HTTP call; unit-normalization occurs before storage/search | `embed_text_async` catches every exception and returns `None`; no retry at this layer; no provenance/model/version stored per vector. 146 NULL embeddings exist. |
| Vector storage | normalized 4096 vector | `vector(4096)` | `semantic_facts.embedding`; `save_fact_async` | Stored as interpolated pgvector literal | No vector index exists. At current 2,362 rows sequential scan is acceptable but architecture will degrade. Duplicate vector hashes exist. |
| Vector search | normalized query vector + filters | rows with distance | `MemoryDB.search_similar_async/sync`; `build_search_similar_query` | `embedding <=> query`, `embedding IS NOT NULL`, optional user/fact/session/metadata filters, distance threshold, `ORDER BY distance LIMIT` | SQL does not filter `invalid_at IS NULL` in vector search. Invalid facts can be returned. No vector index. |
| Keyword search | query text + filters | trigram/TSV ranked rows | `search_trgm*`, `search_tsv*` | `similarity >= 0.3`; `tsv @@ plainto_tsquery('english', query)` | Both builders omit `user_id` from the base conditions only if caller fails to supply it; more importantly, tsv uses English stemming for Indonesian/mixed content. |
| Retrieval merge | Three ranked channel lists | fused rows | `retrieval._hybrid_rrf_merge` | Adds `1/(60+rank)` per channel; stores first row per ID; sorts fused score, then original `item['score']` | Actual vector/trigram/TSV scores are not fused. RRF rewards repeated channel presence. No diversity, novelty, recency, category, or duplicate-family penalty. |
| Ranking | Fused rows | parsed memories | `_parse_fact_content`, `_score_fact` | Computes similarity*0.6 + importance*0.2 + confidence*0.2 | `_score_fact` is not used to reorder after RRF. For dynamic records metadata has no confidence, so fallback 0.5. FSRS helpers exist but are not applied in the combined prompt retrieval path. |
| Merge/context | static + dynamic parsed rows | strings | `retrieve_memories_combined`, `_format_static_context`, `_format_dynamic_context` | Static limited to 5 in prompt caller; dynamic to 3; static formatted as category/entity/relation/target; dynamic truncated to 150 chars | Static IDs are returned; dynamic IDs are discarded by `_retrieve_memories_async`. No provenance/source IDs are injected in prompt text. |
| Prompt assembly | memory strings + profile/global knowledge + history | system message and messages list | `app/prompts.py`, `build_system_message_async`, `_build_sections_async`, `_compose_structured_system_message`, `build_messages` | Legacy path inserts memory string; structured path wraps all memory text into one synthetic item `id=mem_ctx`, truncates it at 4,000 chars; global knowledge separately adds up to 2,000 chars | Structured prompt loses per-memory identity and score. Memory is fetched twice only if both builders are invoked separately; the prompt query is only current user text. History is capped by `history_limit` and 15,000 estimated tokens, but history is not the long-term retrieval corpus. |

## 3. Phase investigation

### Phase 1 — Conversation capture

**Observed database:** 14,079 total message rows. Of these, 5,614 are user and 6,059 assistant messages; 1,222 are system; 937 are `image_tools`; the remainder are tool-specific roles.

The memory pipeline explicitly filters to `role in ('user', 'assistant')` in both initial and incremental extraction. Tool messages, system messages, image messages, and tool-specific roles affect the stored conversation but do not enter segmentation/PCL. That is a deliberate exclusion, but it means tool-derived facts and tool outputs are invisible unless the assistant/user text restates them.

The extraction window is not the LLM prompt history window. The pipeline fetches up to 10,000 messages for initial processing and at most 100 messages per run. The AI prompt history independently uses `history_limit` (default 100) and a 15,000 estimated-token cap.

**Important state bug:** after processing only the first 100 messages of a backlog, `mark_segmentation_done_async()` stores `last_segmented_count = actual_total`, where `actual_total` is the full current conversational count, not the number actually processed. It also stores the last processed message ID. Future ID-based runs can still process messages after the last processed ID, but the count fallback can skip the remainder if the ID query fails. This makes the dual tracking semantics unsafe.

### Phase 2 — Memory creation

The live schema has one physical `semantic_facts` table with two logical fact types:

- `dynamic`: episodic summaries and older dynamic/segment material.
- `static`: semantic user facts extracted by PCL.

Metadata carries the logical schema: category, relation, entity, target, confidence, importance, session ID, source table, source message IDs/ranges, stability, surprise level, and source episodic IDs.

The live distribution is:

- 2,362 total facts; 1,300 active; 1,062 soft-invalid.
- 1,889 dynamic; 1,005 active.
- 473 static; 295 active.
- 1,811 rows have no metadata category, almost entirely dynamic facts.
- Static active importance is nearly constant: min/25th/median/75th/max = 0.7/0.7/0.7/0.7/0.9.
- Dynamic active importance ranges from ~1.6e-27 to 0.87; median 0.5.
- Static confidence ranges 0.5–1.0, mean ≈0.702. Dynamic confidence is absent and falls back to 0.5 in ranking.

The store is therefore not empty or vector-collapsed, but it is not a clean atomic memory set either. Many dynamic rows contain long raw conversation windows, tool output, errors, and roleplay. The exact duplicate query found no active duplicate content, but historical duplicates exist and duplicate vector hashes are present.

### Phase 3 — Persistence

Writes are performed through `save_fact_async()` with content-level duplicate checking scoped by `(fact_type, content, user_id, invalid_at IS NULL)`. The database does not enforce this uniqueness. Concurrent jobs can race.

Static upsert performs another vector deduplication pass with distance `< 0.03`, then exact content lookup, then insert. It increments/reinforces existing rows only when the nearest candidate's content is exactly equal. A semantically similar but textually different candidate is not reinforced by the extractor; it proceeds to exact check and insert.

Soft deletion uses `invalid_at`. Retrieval SQL is inconsistent: `search_trgm` and `search_tsv` add `invalid_at IS NULL`; vector search does not. `get_facts_by_session` also does not consistently exclude invalid rows. This allows stale invalid records to compete in vector retrieval and RRF.

### Phase 4 — Embedding

The endpoint is Chutes Qwen3 Embedding 8B, output dimension 4096. Vectors are normalized before storage and again before search. Storage dimensions are consistent: 2,216 non-null vectors all have dimension 4096.

The data test found 146 NULL embeddings (145 dynamic, 1 static), no NULL TSV values, and no evidence of a single constant vector. Random active-vector statistics: average cosine similarity ≈0.427; minimum ≈0.047; maximum ≈0.987. That rules out “all embeddings are identical.”

There are repeated vector hashes, including four identical static vectors and multiple repeated dynamic vectors. These likely correspond to repeated input summaries/content and should be traced to source text; they are not sufficient to explain all repeated retrieval.

### Phase 5 — Vector search

The vector SQL is a sequential scan with `embedding <=> query`, `ORDER BY distance`, and `LIMIT`. No pgvector index exists in the live database. At 2,362 rows this is not a correctness problem, only a future scale bottleneck.

The vector query applies `embedding IS NOT NULL`, user ID, fact type, and optional metadata/session filters, but it does **not** add `invalid_at IS NULL`. This is a correctness defect: invalidated memories can return from the vector channel and then be fused with active keyword results.

The sampled SQL nearest-neighbor searches changed substantially with different anchor vectors, demonstrating that the vector operator responds to query direction. Therefore repeated prompt results are not explained by an always-return-the-same SQL ordering bug.

### Phase 6 — Ranking

The system has three ranking layers but they do not compose cleanly:

1. SQL ranks vector rows by distance, trigram rows by similarity, TSV rows by `ts_rank`.
2. RRF replaces those scores with rank-only scores.
3. `_parse_fact_content()` computes a metadata-aware score, but RRF output is not sorted by that score. Its score is only a tie-break after fused score.

This makes repeated cross-channel hits sticky. A stable fact that receives moderate rank in all channels can outrank a highly relevant fact that appears only in vector search. There is no MMR, category quota, novelty, source-family suppression, or per-session/global balance.

Recency/importance is also not a true ranking input for the prompt path. `last_accessed` is updated on every retrieval, which creates feedback: repeatedly retrieved facts remain “recent,” while the ranking still does not use recency consistently. FSRS logic exists for episodic memories but is not applied by `retrieve_memories_combined()`.

### Phase 7 — Merge

RRF deduplicates by numeric fact ID across channels, which is good for same-row duplicates. It does not deduplicate semantically similar rows with different IDs. It retains the first row dictionary and does not merge channel-specific scores into an explainable object.

The combined path independently fuses static and dynamic channels, then truncates static to 5 and dynamic to 3. Static and dynamic are not globally balanced by novelty or source. A stable static cluster can therefore occupy all five static slots every turn.

### Phase 8 — Prompt assembly

The runtime prompt path is:

`build_messages()` → `_build_sections_async()` or `build_system_message_async()` → `_retrieve_memories_async()` → `retrieve_memories_combined_async()` → `asyncio.to_thread(retrieve_memories_combined)`.

The injected static context is limited to five rows and dynamic context to three. In structured mode, the individual memories are flattened into one JSON item with synthetic ID `mem_ctx`, score `1.0`, and content truncated to 4,000 characters. This removes the individual IDs/scores from the LLM-facing context and makes downstream auditing impossible without logs.

The prompt also includes `profiles.global_knowledge` and, structured mode only, legacy `session_context`/profile-memory blocks. These are separate memory channels that can make responses appear to repeat even when retrieved IDs change. The current user message is the retrieval query; there is no query expansion from conversation history, session title, active task, or recent turn summary.

## 4. Root-cause analysis by layer

| Layer | Verdict | Evidence |
|---|---|---|
| Extraction | **Contributing, not sole root cause** | Only user/assistant messages enter extraction; triggers are sparse; 100-message cap; backlog handling is dual-state and lossy; tool outputs are excluded. |
| Storage | **Contributing** | 2,362 facts exist, 1,300 active; invalid/stale rows are not consistently excluded by vector search; live schema has migration drift and no uniqueness constraint. |
| Embedding | **Not primary root cause** | 2,216 vectors are 4096-dimensional; random cosine distribution is broad; nearest neighbors vary by anchor. 146 NULL vectors and duplicate hashes are real weaknesses. |
| Vector search | **Correctness and scale weaknesses** | Sequential scan; invalid rows included; no vector index. But sampled nearest-neighbor behavior is query-sensitive. |
| Ranking | **Primary root cause** | Rank-only RRF ignores actual scores and does not apply diversity/recency/novelty. Stable facts appearing in multiple channels are repeatedly promoted. |
| Merge | **Primary root cause** | Five static slots, no semantic-family suppression, no category balance, no source/session diversity. |
| Prompt assembly | **Primary root cause / observability blocker** | Only current user text queries retrieval; static memories flattened/truncated; separate global knowledge and legacy blocks can repeat independently; IDs are removed in structured prompt. |

## 5. Discovered bottlenecks and architectural weaknesses

### Correctness

- `search_similar*` omits `invalid_at IS NULL`.
- `get_facts_by_session*` does not consistently filter invalid facts or order results.
- `SQL_FACT_SELECT_STATIC_LIMIT` has no `ORDER BY`; no-query retrieval is nondeterministic and often ID/order-biased.
- `update_last_accessed_async()` is defined without `user_id`, while callers pass `user_id=user_id`; this raises `TypeError` in the async prompt path and is caught by the surrounding retrieval/prompt error handling. Its SQL also requires a user parameter but the implementation omits it. The async prompt path therefore cannot reliably update access timestamps.
- PCL direct `UPDATE semantic_facts` calls for episode metadata do not always include tenant scope.
- `get_memory_state_async()` and fence queries omit user scope, creating cross-tenant correctness risk even though current data audit showed one dominant user.
- The live database still contains legacy `chat_sessions.memory_json`, `messages.legacy_session_id`, and `semantic_facts.embedding_1536` columns. This is schema drift, not necessarily the retrieval symptom, but it increases ambiguity.

### Recall and diversity

- Tool/system/image messages are excluded from memory extraction.
- Cross-session dynamic memories are intentionally not retrieved.
- Only 5 static and 3 dynamic memories reach the prompt.
- No MMR, source-family suppression, category quotas, novelty, or temporal diversity.
- RRF uses rank only; scores are not calibrated across channels.
- Tsvector uses the English configuration for Indonesian/mixed-language content.
- Query embedding is based only on the current user message.
- No provenance or memory IDs survive into the structured prompt.

### Pipeline throughput

- Trigger checks only at exact message-count multiples of 50.
- 3-hour idle gate applies to 40–49 deltas.
- Fire-and-forget background tasks can be lost on process restart and failures are not surfaced to the turn.
- One pipeline run processes at most 100 messages.
- Backlog state records total count after partial processing, creating fallback skip risk.
- PCL calls prediction and calibration per segment, plus segmentation and enhancement calls; a single large backlog is slow and rate-limited.

### Data quality

- 1,811 facts have no category, mostly dynamic.
- Dynamic facts often contain raw transcript/tool/error/roleplay material instead of atomic episodic statements.
- 1,062 invalid rows remain in the table and may still enter vector search.
- 146 facts have NULL embeddings.
- Exact historical duplicates and repeated vector hashes exist.
- Static importance is mostly fixed at 0.7, so importance has little discriminative value.
- Embedding model/version is not stored, preventing drift audits and safe re-embedding decisions.

## 6. Instrumentation result

The requested full trace cannot be produced from historical runtime logs because the current code does not emit a correlation ID linking:

`conversation → extracted action → stored fact ID → embedding → candidates → RRF → final prompt`.

Source inspection shows only coarse logs such as “Created episode”, “PCL result”, and pipeline counts. No persistent per-turn retrieval trace exists. The database audit was therefore read-only and aggregate; it did not modify behavior to add diagnostics.

The correct temporary trace fields should be:

- `trace_id`, `session_id`, `user_id`, `turn_id`
- input message IDs and roles used for extraction
- segment ranges and summaries
- PCL actions and source IDs
- saved/reinforced fact IDs
- embedding dimension, null status, model endpoint, and vector hash
- per-channel candidate IDs and raw scores
- RRF score, parsed score, recency/importance/confidence
- final static/dynamic IDs and exact injected text length

These should be emitted at DEBUG level with content redacted or hashed, then removed or gated after the audit.

## 7. Prioritized implementation plan — recommendations only, no fixes applied

### P0 — Make retrieval truthful and explainable

1. Add `invalid_at IS NULL` to every retrieval path, especially vector search.
2. Fix async `update_last_accessed_async()` parameter binding and make every update tenant-scoped.
3. Add deterministic `ORDER BY` to non-query fact retrieval.
4. Add temporary per-turn trace instrumentation with a correlation ID and candidate snapshots.
5. Preserve individual memory IDs, channel scores, fused score, and final order through formatting; do not flatten to synthetic `mem_ctx`.

### P1 — Stop stable clusters from monopolizing context

6. Replace rank-only RRF with score-aware fusion: normalize vector distance, trigram similarity, and TSV rank separately, then combine with explicit weights.
7. Apply a second-stage ranker that includes relevance, importance, confidence, recency, and source quality.
8. Add MMR or an equivalent semantic-family penalty; enforce category and source/session diversity.
9. Add explicit duplicate-family suppression for near-identical content/vector hashes.
10. Decide and document whether static facts are global cross-session memory and dynamic facts are session-local; if cross-session episodic recall is desired, add a separate global episodic channel rather than silently mixing scopes.

### P1 — Repair extraction completeness

11. Replace exact modulo-50 triggering with durable cursor-based queue/job scheduling.
12. Track `last_segmented_message_id` as the sole cursor; remove count fallback or make it provably consistent.
13. Advance the cursor only through the last successfully processed message, never to total count after a partial run.
14. Process backlog in ordered batches until caught up, with durable status and retry state.
15. Add an explicit policy for tool results/system observations: either extract selected tool outputs or document that they are never memory sources.

### P2 — Improve memory quality

16. Store atomic semantic facts separately from long episodic summaries; reject transcript-like dynamic content from semantic context.
17. Validate extraction output with deterministic checks, not only prompt instructions.
18. Store embedding provider/model/version and content hash.
19. Add database uniqueness protection or an idempotency key for active exact content.
20. Reconcile or archive invalid/legacy rows after retrieval correctness is fixed; do not delete before trace evidence is collected.

### P2 — Scale and language quality

21. Add an appropriate pgvector index after measuring query latency at the expected fact count; the current 2,362-row sequential scan is not the immediate correctness issue.
22. Add language-aware full-text search or remove TSV from the hybrid path for Indonesian/mixed-language queries.
23. Add bounded embedding retries with explicit failure metrics and a repair queue for NULL embeddings.

### P3 — Validation gates

24. Build a repeat-search test suite with 20 diverse query classes and assert candidate overlap, category coverage, invalid-row exclusion, and prompt ID fidelity.
25. Add end-to-end trace tests that use a synthetic session and verify every stage from message IDs to injected memory IDs.
26. Measure before/after with Recall@K, category diversity, cross-query Jaccard overlap, stale-row rate, NULL embedding rate, and prompt memory survival rate.

## 8. Final answer to the objective

The database is not failing to store memories, and the embeddings are not all identical. The system is producing a heterogeneous but noisy and partly stale fact corpus. Repeated retrieval is mainly caused by **query/context design plus ranking/merge policy**:

- the current user message is the only retrieval query;
- static cross-session facts are the primary continuity channel;
- RRF rewards repeated appearance across keyword/vector channels rather than calibrated relevance;
- no diversity or novelty policy prevents one semantic cluster from filling all five static slots;
- invalid vector rows are allowed into the vector channel;
- prompt assembly removes individual memory identity and also injects separate legacy/global knowledge blocks.

Extraction and persistence weaknesses explain why some newer conversation material never becomes eligible or never becomes a high-quality fact, but they do not explain an all-vectors-identical failure. The first implementation work should therefore target **retrieval correctness/traceability and score-aware diverse ranking**, followed immediately by durable backlog/cursor repair.
