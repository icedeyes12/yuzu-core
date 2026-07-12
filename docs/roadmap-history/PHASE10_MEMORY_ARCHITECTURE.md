# Phase 10: Memory Architecture Lifecycle

## Overview
This document serves as the formal lifecycle mapping and audit report for the Phase 10 Memory Architecture. The goal of this phase was to remap vector memories, search structures, and semantic facts directly onto the new canonical message flows, ensuring single ownership, strict multi-tenant isolation, and resilient embedding ingestion.

## Memory Lifecycle

1. **Message Created & Persisted:**
   A message originates from standard chat routing (via `ConversationService` or tools) and is persisted via canonical database operations.
   
2. **Pipeline Triggering:**
   The orchestrator checks conditions (e.g. idle gap, message count thresholds). If met, it pushes the session to the background queue using `trigger_memory_pipeline_async(session_id, count, user_id)`.

3. **Background Ingestion & Batching:**
   The `_background_worker_async` continuously processes the queue. It fetches the session's new unsegmented messages securely (filtering by `user_id`) using the standard model abstraction `get_session_messages_after_id_async`.

4. **Segment Extraction:**
   The LLM partitions the new messages into conversational "episodes" or segments.

5. **Embedding Generation:**
   Segment summaries are passed to `app.memory.embedder.embed_text_async`. This step abstracts vector generation away from individual callers, centralizing model invocation.

6. **Semantic Mapping (PCL - Predict, Calibrate, Learn):**
   New segments trigger fact extraction (`create_episodic_memory`). If static semantic facts are implied, `upsert_semantic_memory_async` uses similarity checks (via pgvector) to decide between updating existing memory (to reinforce importance/decay) or inserting new semantic facts.

7. **Indexed Storage:**
   Facts are inserted via the `MemoryDB` facade, which acts as the absolute gateway to Postgres, securely binding every insert and fetch command to the corresponding `user_id`.

8. **Retrieval & Context Injection:**
   On future conversational requests, `retrieve_memories_combined_async` performs a single, multi-channel hybrid search (vector, trigram, tsvector) bounded by `user_id`. This output statically populates the pre-LLM system context without requiring secondary inline queries.

9. **Decay & Reinforcement (FSRS):**
   Idle sessions undergo periodic spaced-repetition evaluations via `run_memory_review_async`, adjusting fact importance and stability, and dropping items below the viability threshold.

## Architectural Audit Conclusions

* **No legacy memory pipeline:** All legacy multi-tenant leaks have been patched. Database fetches rely strictly on standard abstractions (`models_async.py` & `db_memory_facade.py`).
* **No duplicate retrieval pipeline:** Retrieval centers entirely on `MemoryDB.search_similar` and its async equivalent.
* **No raw database bypass:** All message queries inside the memory loop utilize canonical endpoints.
* **No cross-user leakage:** All CRUD operations inside `db_memory.py` and downstream pipelines now force a mandatory `user_id` context parameter.
* **No stale semantic fact generation:** PCL deduplication logic merges overlaps correctly via the `update_fact_metadata_async` flow.
* **No inconsistent message ownership:** Memory relies solely on the globally tracked `messages` tables; memory nodes no longer cache ghost states.

*(Audit completed July 2026)*