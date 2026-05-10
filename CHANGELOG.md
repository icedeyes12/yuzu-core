# Changelog

All notable changes to this project will be documented in this file.

## \[3.0.3\] - 2026-05-10

### Fixed — FSRS Implementation Corrected

Fixed broken FSRS (Free Spaced Repetition Scheduler) implementation that was crashing and always falling back to simple multipliers.

**Root Cause**: Card constructor used invalid parameters (`elapsed_days`, `scheduled_days`, `reps`, `lapses`) that don't exist in fsrs v6.3.1 API.

**Files Changed**:

- `file app/memory/memory_review.py` — Fixed Card constructor, state extraction, added State import
- `file app/memory/retrieval.py` — Fixed retrievability calculation, added timezone-aware datetime handling

**Changes**:

- Added `State` import from fsrs library
- Fixed Card constructor to use correct v6.3.1 API (`stability`, `difficulty`, `state`, `due`, `last_review`)
- Fixed state extraction after `review_card()` call
- Added edge case protection for None/zero stability and invalid state values
- Fixed timezone awareness in retrievability calculation
- Added logging for FSRS review operations

**Verification**:

- FSRS Good rating now correctly increases stability (24 → 918.6 days)
- FSRS Again rating now correctly decreases stability (100 → 17 days)
- Retrievability decays correctly over time (fresh 0.994 → 30 days 0.884)
- Edge cases handled without crash

## \[3.0.2\] - 2026-05-10

### Changed — Memory System Performance Optimization

Reduced per-turn API calls by 70-80% through request-scoped caching and throttled pipeline checks.

#### Performance Impact

| Metric | Before | After |
| --- | --- | --- |
| Embeddings/turn | 2 | 0-1 |
| LLM calls/turn | 1-3 | 1 |
| DB queries/turn | \~10 | \~3 |
| Pipeline gate checks | Every turn | Every 5th turn |

#### Changes

**Throttled Pipeline Checks (`file orchestrator.py`):**

- Pipeline gate check now runs every 5th turn instead of every turn
- Reduces DB queries from 4 per turn to 2 per turn (cached)
- Gate thresholds corrected: WINDOW_BASE=40, WINDOW_MAX=50, IDLE_GATE_HOURS=3.0

**Request-Scoped Caching:**

- `file memory.py`: `_request_cache` (thread-local) caches memory state per-request
- `file retrieval.py`: `_embedding_cache` (thread-local) caches query embeddings
- Caches cleared at turn end via `_clear_request_cache()` + `_clear_embedding_cache()`
- Short query skip: queries &lt; 4 chars skip embedding entirely

**Combined Retrieval (`file retrieval.py`):**

- New `retrieve_memories_combined()` fetches static + dynamic in single embedding call
- `file prompts.py` updated to use combined retrieval
- Reduces embedding calls from 2 to 1 per turn

#### Files Modified

| File | Changes |
| --- | --- |
|  | Added `_request_cache`, `_get_cached_memory_state()`, `_clear_request_cache()` |
|  | Added `_embedding_cache`, `_get_cached_embedding()`, `_clear_embedding_cache()`, `retrieve_memories_combined()`, `_MIN_QUERY_LEN_FOR_EMBEDDING` |
|  | Added `_PIPELINE_CHECK_INTERVAL=5`, throttled check in `_post_turn()`, cache clearing |
|  | Added `_retrieve_memories()` combined retrieval, updated `build_system_message()` |

#### Documentation Updated

- `file app/memory/docs/architecture.md` — Architecture diagram, Request Caching section, Integration Points, Key Design Decisions
- `file app/README.md` — Memory System section, Architecture Principles #7
- `file app/memory/README.md` — Performance Optimizations section, Pipeline Triggers table, Implementation Status

#### Verification

- All Python files pass `python -m py_compile` syntax validation
- Ruff linting passes with no errors
- No architectural drift from documentation

### Fixed — Typing Indicator Architecture Consolidation

Consolidated two competing typing indicator systems into a single, clean dynamic implementation.

#### Problem

The codebase had **two overlapping systems**:

1. **Legacy static**: `<div id="typingIndicator">` in HTML, toggled via `classList.add/remove("hidden")`
2. **Dynamic**: JS-created `.typing-indicator-message` appended to chat container

The legacy element had no CSS styling (invisible) and caused confusion about which system was active.

#### Solution

- **Removed** legacy static `#typingIndicator` HTML element from `file templates/chat.html`
- **Removed** legacy classList toggling pattern from `file static/js/chat.js`
- **Standardized** on dynamic in-flow message system with proper styling

#### Files Modified

| File | Change |
| --- | --- |
|  | Removed `<div id="typingIndicator">` element |
|  | Replaced classList toggling with `showTypingIndicator()`/`hideTypingIndicator()` calls; increased `bottomMargin` from 20px to 60px |
|  | Removed hardcoded `min-height` and mobile media query padding override |

#### Architecture

```markdown
┌─────────────────────────────────────────────┐
│  .chat-container (flex-column, gap: 0.8rem) │
│  ┌─────────────────────────────────────┐   │
│  │ .message.user                       │   │
│  └─────────────────────────────────────┘   │
│  ┌─────────────────────────────────────┐   │
│  │ .message.ai                         │   │
│  └─────────────────────────────────────┘   │
│  ┌─────────────────────────────────────┐   │
│  │ .typing-indicator-message ← DYNAMIC │   │
│  │   (appended via JS, in-flow)        │   │
│  └─────────────────────────────────────┘   │
│                                             │
│  ↓ padding-bottom (dynamic via JS)          │
├─────────────────────────────────────────────┤
│  .input-area (position: fixed, bottom: 0)   │
└─────────────────────────────────────────────┘
```

#### Dynamic Layout System

The `updateDynamicLayout()` function calculates:

- `paddingTop` = header height (48px) + margin
- `paddingBottom` = input area height + 60px margin

Triggered by:

- Initial page load
- Textarea input (auto-resize)
- Window resize
- ResizeObserver on input area

#### Browser Compatibility Note

Some mobile browsers (e.g., Queta) may require fullscreen mode for correct viewport calculation. Kiwi Browser handles this correctly in all modes.

## \[3.0.1\] - 2026-04-25

### Changed — Python 3.13 Compatibility Upgrade

This release modernizes the codebase for Python 3.13 while maintaining backward compatibility with Python 3.12+.

#### Type Annotation Modernization

- **PEP 585/604 Syntax**: All legacy `typing` imports converted to modern syntax

  - `List[X]` → `list[X]`
  - `Dict[K, V]` → `dict[K, V]`
  - `Optional[X]` → `X | None`
  - `Union[A, B]` → `A | B`

- `from __future__ import annotations`: Added to 34 Python files

  - Enables lazy evaluation of annotations
  - Allows forward references without quotes
  - Required for PEP 585 syntax in class bodies

#### Files Modified

| Category | Files |
| --- | --- |
| Core | `file app/app.py`, `file app/providers.py`, `file app/database.py`, `file web.py`, `file main.py` |
| Tools | All `file app/tools/*.py` (7 files) |
| Memory | All `file app/memory/*.py` (10 files) |
| API | `file app/api/routes.py`, `file app/api/__init__.py` |
| Models | `file app/db_pg_models.py`, `file app/db_pg_models_async.py`, `file app/db_queries.py` |
| Other | `file app/encryption.py`, `file app/key_manager.py`, `file app/visual_context.py`, `file app/__init__.py` |

#### Documentation

- **`file requirements.txt`**: Added `[PYTHON]: 3.12+ (3.13 compatible)` header
- **`file AGENTS.md`**: Updated Tech Stack to show `Python 3.12+ (3.13 compatible)`
- **`file README.md`**: Added `**Python 3.12+ (3.13 compatible)**` under project title

#### Dependencies

- No new dependencies added
- All existing dependencies verified compatible with Python 3.13:
  - `psycopg[binary,pool]>=3.1` — pre-compiled wheels available
  - `pydantic>=2.8.0` — pydantic-core has pre-compiled `aarch64` wheels
  - `fsrs>=6.3.1` — pure Python, no Rust dependency

#### Verification

- All Python files pass `python3 -m py_compile` syntax validation
- Ruff linting passes with no errors
- No legacy `typing.List`, `typing.Dict`, `typing.Optional`, `typing.Union` patterns remain

## \[3.0.0\] - 2026-04-19

### Changed — Complete Codebase Refactor (Stages 1-6)

This is a **major refactor** focused on simplicity, clarity, and maintainability.

#### Stage 1: Foundation Modules

- **`file app/logging_config.py`** (NEW): Centralized logging setup with `get_logger()`
- **`file app/commands.py`** (NEW): `/command` detection, `StreamFilter` for streaming, markdown-image guards
- **`file app/prompts.py`** (NEW): System prompt assembly, message context building
- **`file app/llm_client.py`** (NEW): AI response generation + `chutes_chat()` helper (consolidated 3 call sites)
- **`file app/orchestrator.py`** (NEW): Message handling pipeline — image cache, vision routing, tool exec, synthesis
- **`file app/profile_analysis.py`** (NEW): Profile & memory analysis utilities
- **`file app/session_lifecycle.py`** (NEW): Session start/end logic extracted from `file app.py`
- **`file app/app.py`**: Reduced from 1400 lines to thin shim (\~50 lines)

#### Stage 2: Database Simplification

- **`file app/database.py`**: **DELETED** — removed passthrough wrapper
- All callers migrated to direct `db_pg_models` imports

#### Stage 3: db_pg Cleanup

- **`file app/db_queries.py`** (NEW): Single source of truth for SQL constants, parsers, DDL
- **`file app/db_pg_models.py`**: Refactored to thin wrappers around `db_queries`
- **`file app/db_pg_models_async.py`**: Refactored to thin wrappers around `db_queries`
- Fixed `pg_scalar()` bug (was returning dict instead of scalar)

#### Stage 4: Memory Package Refactor

- **`file app/memory/db_memory_queries.py`** (NEW): SQL constants + query builders
- **`file app/memory/db_memory.py`**: Removed 282 lines — SQL extracted, dead code deleted
- **Deleted dead code**: `upsert_fact()`, `search_trgm_keywords()`, `update_fact_importance()`
- **Logging migration**: All `print()` → `logging` across memory package
- **plast-mem alignment verified**: 11/11 features aligned with reference architecture

#### Stage 5: Tools Package Refactor

- **`file app/tools/registry.py`**: Logging migration, removed legacy `TOOL_ROLE_MAP`
- **All tool modules**: Logging migration, replaced deprecated `Database` imports

#### Stage 6: Scripts Cleanup

- Scripts already clean (CLI utilities, `print()` is appropriate)

#### Stage 7: API Routing Decomposition (NEW)

**Added:**

- `app/api/` package with extracted API routes from `file web.py`
- `file app/api/__init__.py` — Package init
- `file app/api/routes.py` — All `/api/*` endpoints
- `GET /api/config` — Frontend configuration endpoint (provider/model info, vision capabilities)
- `fsrs>=6.3.1` dependency for proper FSRS state transitions

**Changed:**

- `file web.py` — Reduced to minimal entry point (\~50 lines), imports router from `app/api/`
- `file requirements.txt` — Added `fsrs>=6.3.1` for FSRS library integration
- Memory pipeline trigger — Now uses actual message count instead of session_memory dict
- PCL (Predict-Calibrate Learning) — Enhanced with segment context and temporal contradiction guidance
- Documentation — Updated `file AGENTS.md`, `file app/README.md`, `file app/memory/README.md`, `file app/memory/docs/architecture.md` for FSRS library integration
- **Chat responses** — Removed `max_tokens=4096` limit; models now use their natural response length

**Fixed:**

- Memory pipeline now triggers correctly (was using wrong field for message count)
- FSRS integration uses proper `Scheduler` class and `Card` objects
- Documentation clarified: distance threshold is `<= 0.05` (not `< 0.05`)
- Termux ARM limitation documented — IVFFlat/HNSW indexes require SIMD instructions not available on ARM

**Security:**

- Dependencies cleaned — Removed unused packages (beautifulsoup4, numpy, scipy, SQLAlchemy)

### Security

All **GitHub Advanced Security alerts resolved**:

- **ReDoS (Polynomial Regex)**: Changed unbounded quantifiers (`*`, `+`) to bounded (`{0,N}`, `{1,N}`)
  - `file app/commands.py`: `_MARKDOWN_IMAGE_PATH`, `_MARKDOWN_IMAGE_ANY`, `_GENERATED_IMAGE_SRC`
  - `file app/orchestrator.py`: `_MD_IMAGE_PATTERN`
  - `file app/tools/multimodal.py`: `extract_image_urls()`, `detect_uploaded_images()`
  - `file app/db_queries.py`: All regex patterns bounded
- **Path Traversal (CWE-22)**: Path normalization + whitelist validation in `file orchestrator.py`

### Tests

- **`file tests/test_commands.py`** (NEW): Tests for command detection, StreamFilter
- **`file tests/test_db_queries.py`** (NEW): Tests for SQL constants, parsers
- **`file tests/test_prompts.py`** (NEW): Tests for prompt assembly
- **`file tests/test_profile_analysis.py`** (NEW): Tests for profile analysis
- **`file tests/test_stream_filter.py`** (NEW): Tests for streaming command detection

### Documentation

- **`file AGENTS.md`**: Updated to reflect new modular architecture
- **`file ROADMAP.md`**: Added complete refactor timeline
- **`file app/memory/docs/architecture.md`**: Updated with plast-mem alignment details

### Stats

- **40 files changed**
- **+5,229 lines added**
- **-4,344 lines removed**
- **Net -900 lines through consolidation**

## \[2.3.1\] - 2026-04-12

### Changed — Codebase Simplification

- **`file app/visual_context.py`** (NEW): Extracted from `file app/app.py`

  - `store_visual_context()` — thread-safe visual context buffer
  - `consume_visual_context()` — decrementing turn counter
  - `has_visual_reference()` — regex pattern for "yang tadi", "the previous", etc.
  - `_VISUAL_CONTEXT_TURNS = 3` — follow-up turns before context expires

- **`file app/providers.py`**: Consolidated `_normalize_messages()` to `AIProvider` base class

  - Removed duplicate implementations from `OllamaProvider` and `ChutesProvider`
  - Single normalization logic for all providers

- **`file app/tools/registry.py`**: Removed `build_markdown_contract()` wrapper

  - Now imports and uses `build_tool_contract()` from `file schemas.py` directly
  - Legacy `TOOL_ROLE_MAP` kept for backward compat

- **`file app/app.py`**: Removed 8 unused utility functions (99 lines)

  - `_generate_tool_call_id` — never called
  - `_is_image_generation_tool` — never called
  - `_is_tool_markdown` — never called
  - `_extract_tool_role` — never called
  - `_extract_command_from_markdown` — never called
  - `_handle_ai_image_generation` — never called
  - `build_visual_context` — never called
  - `save_section_content` — never called

### Documentation

- **`file AGENTS.md`**: Cleaned up
  - Removed reference to non-existent `file ROADMAP_MEMORY_ALIGNMENT_V2.md`
  - Added architecture summary table
  - Simplified structure

## \[2.3.0\] - 2026-04-05

### Added — Memory System Major Upgrade (Phases 3-8)

- **`file app/memory/pcl.py`** (NEW): Predict-Calibrate Learning pipeline

  - `run_predict_calibrate()` — aligned with plast-mem's PCL: PREDICT → CALIBRATE → CONSOLIDATE
  - `load_relevant_semantic_facts()` — fetches top active semantic facts as prediction context
  - `predict_episode_content()` — LLM predicts episode content from existing knowledge
  - `calibrate_and_extract()` — identifies knowledge gaps between prediction and reality
  - `consolidate_facts()` — applies actions: new / reinforce / update / invalidate
  - Wired into `process_messages_for_memory()` after episodic creation

- **`file app/memory/memory_review.py`** (NEW): LLM-based memory review system

  - `review_memory()` — LLM rates each retrieved memory: Again/Hard/Good/Easy
  - `mark_retrieved_as_pending_review()` — marks retrieved facts for deferred review
  - FSRS parameter updates: Again (×0.5), Hard (×0.9), Good (×1.2), Easy (×1.5)
  - `pending_review` flag in metadata cleared after review

- **`file app/memory/segmenter.py`** — LLM dual-channel segmentation

  - `_llm_detect_boundary()` — LLM returns `{should_segment, surprise_level, topic_shift}`
  - `_should_segment()` — dual-channel: time-gap rule OR LLM decides
  - `surprise_level` passed to `create_episodic_memory` → flashbulb stability boost
  - `segment_session()` threads previous summary for LLM context

- **`file app/memory/retrieval.py`** — Reciprocal Rank Fusion (RRF) + dedicated segment retrieval

  - `_rrf_merge()` — full RRF implementation: `score = Σ 1.0 / (k + rank)`, k=60
  - Hybrid scoring after RRF: `similarity × 0.6 + importance × 0.2 + confidence × 0.2`
  - `retrieve_segments()` — dedicated segment retrieval (source_table filter), not alias
  - `retrieve_memory()` wires `mark_retrieved_as_pending_review()` on all returned fact IDs

### Changed — Memory System

- **`file app/memory/embedder.py`**: Switched to Qwen3-Embedding-0.6B (1024-dim)

  - Endpoint: `https://chutes-qwen-qwen3-embedding-0-6b.chutes.ai/v1/embeddings`
  - `EMBEDDING_DIM`: 4096 → 1024
  - Dimension guard in `embed_texts()` — raises if returned vector != 1024

- **`file app/memory/db_memory.py`**: Search + storage improvements

  - `search_similar()` — direct string interpolation for vec_literal (avoids psycopg2 CTE binding issues)
  - `save_fact()` — dimension assert (raises if embedding != 1024)
  - `_normalize()` — unit-length for cosine similarity
  - `invalidate_fact()` — soft delete: sets `invalid_at = NOW()`
  - `get_active_facts()` — excludes soft-deleted facts (`invalid_at IS NULL`)
  - `soft_delete_fact()` — alias for `invalidate_fact()`
  - `save_fact()` accepts explicit `category` param

- **`file app/memory/extractor.py`**: 8-category taxonomy + source tracking

  - `_RELATION_TO_CATEGORY` mapping — all 8 plast-mem categories
  - `upsert_semantic_memory()` — category mapped from relation, `source_episodic_ids` tracked
  - On reinforce: appends to `source_episodic_ids` (not just `access_count`)
  - On new: initializes `source_episodic_ids = [episode_id]`
  - `create_episodic_memory()` returns `fact_id` for PCL chaining

- **`file app/memory/review.py`**: FSRS scope narrowed

  - Decay applies to episodic/dynamic only — static/semantic facts NOT decayed
  - Semantic facts use temporal validity (`valid_at`/`invalid_at`) instead of FSRS decay

- **`file app/db_pg.py`**: `Vector` class repr fixed

  - `__repr__` uses `[]` (pgvector array syntax) not `{}`

### Changed — Embedding Infrastructure

- **`file scripts/reembed_all.py`** (NEW): Three-phase column migration
  - `--migrate` — adds `embedding_1024` column (VECTOR(1024))
  - `--reembed` — re-embed all existing 4096-dim memories to 1024-dim
  - `--finalize` — rename `embedding_1024 → embedding`, drop old column
  - Uses direct SQL string interpolation for pgvector literals

### Documentation

- **`file app/memory/docs/architecture.md`**: Fully rewritten
  - Reflects current implementation: Qwen3-Embedding-0.6B, 1024-dim, RRF, PCL, dual-channel segmentation, LLM review
  - All Mermaid diagrams updated
  - Core Modules Summary now includes `file pcl.py` and `file memory_review.py`

## \[2.2.0\] - 2026-04-03

### Changed — Database Architecture (Breaking)

- **Complete migration from SQLite to PostgreSQL**: All data now stored in PostgreSQL (`yuzuki` database)
  - Hybrid Library architecture: SQLAlchemy-style ORM + raw psycopg2 for vector operations
  - NO SQLite, NO `yuzu_core.db` — all tables in PostgreSQL
  - pgvector extension for native vector storage and ANN search

### Added — PostgreSQL Infrastructure

- **`file app/db_pg.py`**: New psycopg2 connection pool with `ThreadedConnectionPool`

  - `PgSession` context manager for transaction-safe queries
  - Environment-driven config: `PG_HOST`, `PG_PORT`, `PG_DBNAME`, `PG_USER`, `PG_PASSWORD`
  - Module-level helpers: `pg_fetchone()`, `pg_fetchall()`, `pg_execute()`

- **`file app/db_pg_models.py`**: PostgreSQL models for core tables

  - `profiles` — user profile and preferences
  - `chat_sessions` — conversation sessions
  - `messages` — all chat messages with tool role support
  - `api_keys` — encrypted API key storage
  - Full CRUD operations via raw psycopg2 SQL

- **`file app/memory/db_memory.py`**: Unified memory layer over `semantic_facts` table

  - `save_fact()` — insert with optional embedding
  - `upsert_fact()` — insert or reinforce existing (duplicate detection via vector distance)
  - `search_similar()` — pgvector ANN search via `<=>` operator
  - `decay_facts()` — FSRS-style importance decay
  - Supports `fact_type='static'` (semantic) and `fact_type='dynamic'` (episodic/segments)

### Changed — Memory System

- **`file app/memory/embedder.py`**: Removed `vec_to_blob()`/`blob_to_vec()` — PostgreSQL handles `list[float]` natively

- **`file app/memory/vector_store.py`**: DEPRECATED — FAISS replaced by pgvector, stub delegates to `db_memory.search_similar()`

- **`file app/memory/retrieval.py`**: Rewritten for PostgreSQL vector search

  - `_search_semantic_pg()` — queries `semantic_facts` with `fact_type='static'`
  - `_search_episodic_pg()` — queries with `fact_type='dynamic'` + metadata filter
  - `_search_segments_pg()` — queries with `fact_type='dynamic'` + source_table filter
  - Hybrid scoring: `(distance * 0.6 + importance * 0.2 + confidence * 0.2)`

- **`file app/memory/extractor.py`**: Uses `db_memory.save_fact()` instead of ORM

- **`file app/memory/segmenter.py`**: Uses `db_memory.save_fact()` instead of ORM

- **`file app/memory/review.py`**: Uses `db_memory` for decay operations

### Changed — Tools

- **`file app/tools/memory_store.py`**: Uses `db_memory.save_fact()` with raw `list[float]` embedding
  - Duplicate detection via `search_similar()` distance &lt; 0.05
  - Reinforces existing facts on duplicate instead of inserting

### Changed — Database Interface

- **`file app/database.py`**: Refactored as thin delegate layer
  - All operations delegate to `file db_pg_models.py`
  - ORM models removed: `SemanticMemory`, `EpisodicMemory`, `ConversationSegment` → deprecated
  - `Profile`, `ChatSession`, `Message`, `APIKey` tables remain (via psycopg2)

### Removed — Migration Scripts (Cleanup)

- `file app/memory/batch_migrate.py` — deleted (SQLite migration complete)
- `file app/memory/episodic_migrate.py` — deleted (SQLite migration complete)
- `file app/memory/quality_migrate.py` — deleted (SQLite migration complete)
- `migrate_from_sqlite()` in `file db_pg_models.py` — deleted (no longer needed)

### Dependencies

- Added `psycopg2-binary>=2.9.9` to requirements.txt

### Documentation

- **`file app/memory/docs/architecture.md`** — consolidated into single source of truth
  - Absorbed content from `file fsrs.md`, `file retrieval.md`, `file segmentation.md`, `file semantic_memory.md`
  - All diagrams use Mermaid syntax (no ASCII art)
  - Removed outdated SQLite/FAISS references
- Deleted deprecated doc files: `file fsrs.md`, `file retrieval.md`, `file segmentation.md`, `file semantic_memory.md`

### Migration

- Data migrated via `file a.py` and `file b.py` scripts (already run)
- All SQLite → PostgreSQL migration code removed (migration complete)

## \[2.1.0\] - 2026-03-30

### Added — Standard Tool Calling System

- **`file app/tools/schemas.py`**: New tool schema system with `ToolParam` and `ToolDefinition` dataclasses

  - Standardized tool definitions with name, description, and typed parameters
  - Every tool module now exports `TOOL_DEFINITION` for declarative schema

- **`file app/tools/registry.py`**: Central tool registry — single source of truth for dispatch

  - Lazy-loaded `TOOL_DEFINITIONS` collected from each tool module on first access
  - `get_tool_definitions()` — returns list of all registered tool schemas
  - `get_tool_definition(name)` — returns schema for a specific tool
  - `format_tool_result()` — produces structured `GenerateResult(text, tool_calls)`
  - Legacy `execute_tool()` and `get_tool_role()` maintained for backward compat

- **`file app/tools/__init__.py`**: Re-exports new registry API

### Changed — Provider Tool Support

- **`file app/providers.py`**: OpenRouter and Chutes providers now accept `tools=[]` parameter
  - OpenAI-compatible `function` call schemas injected into chat completions payload
  - `send_message_full()` — returns `GenerateResult(text, tool_calls, provider, model)`
  - `parse_tool_calls()` — extracts structured tool calls from LLM response

### Changed — App Orchestration

- **`file app/app.py`**: `handle_user_message` now dispatches structured tool_calls first
  - `ToolCall` and `GenerateResult` dataclasses for typed tool call handling
  - `generate_ai_response()` calls `send_message_full(tools=[...])` — LLM sees tool schemas
  - **New priority**: structured `tool_calls[0]` from LLM → execute via registry → done
  - **Fallback**: legacy `/command` text detection still works (backward compat)
  - Image tools remain terminal (no synthesis pass on success)

### Tool Schemas Registered

| Tool | Role | Params |
| --- | --- | --- |
| `image_generate` | `image_tools` | `prompt` (str, required) |
| `request` | `request_tools` | `url` (str, required), `method` (str, optional) |
| `memory_search` | `memory_search_tools` | `query` (str, required) |
| `memory_store` | `memory_store_tools` | `fact` (str, required), `category` (str, optional) |

## \[2.0.0\] - 2026-03-29

### Changed — Architecture (Breaking)

- **Complete migration from Flask to FastAPI**: Entire web interface (`file web.py`) rewritten with FastAPI best practices
  - Replaces `Flask(__name__)` with `FastAPI()` application instance
  - Replaces `@app.route()` decorators with `@app.get()` / `@app.post()`
  - Replaces Flask `render_template()` with `Jinja2Templates` + `TemplateResponse`
  - Replaces Flask `send_from_directory()` with `FileResponse`
  - Replaces Flask `jsonify()` with native Pydantic model responses or `dict`
  - Replaces Flask `session` cookies with in-memory `_web_session_tracker` dict

### Removed — Flask Stack

- **Flask** (`Flask>=3.0.0`) — web framework
- **Werkzeug** (`Werkzeug>=3.0.0`) — WSGI utilities (no longer needed with ASGI/uvicorn)

### Added — FastAPI Stack

- **FastAPI** (`fastapi>=0.115.0`) — modern, high-performance web framework
- **uvicorn** (`uvicorn[standard]>=0.30.0`) — ASGI server with auto-reload support
- **python-multipart** (`python-multipart>=0.0.9`) — form data/file upload handling
- **Pydantic v2** integrated validation for all request/response models:
  - `MessageRequest`, `StreamMessageRequest`, `ApiKeyRequest`, `ChutesKeyRequest`
  - `SessionCreateRequest`, `SessionSwitchRequest`, `SessionRenameRequest`, `SessionDeleteRequest`
  - `ProviderSetRequest`, `ProviderTestRequest`, `LocationUpdateRequest`, `GlobalKnowledgeUpdateRequest`

### Added — FastAPI Database Support

- `file app/database.py`: Added `get_db()` generator for FastAPI `Depends()` dependency injection
  - Maintains compatibility with legacy `get_db_session()` context manager

### Migrated — Entry Point

- `file main.py`: `launch_web_interface()` updated to use `uvicorn.run()` instead of Flask `app.run()`
  - Supports configurable `host`, `port`, and `reload` parameters

### Notes

- API routes remain at the same paths (`/api/*`) — backward compatible with frontend
- Static file serving moved from `flask.send_from_directory` to `fastapi.staticfiles.StaticFiles`
- Template rendering moved from `flask.render_template` to `fastapi.templating.Jinja2Templates`

### Fixed — Critical (Post-Migration)

- **P1**: `get_chat_history_for_ai` missing — restored full implementation with markdown contract parsing
- **P2**: `get_chat_history` filter too restrictive — added `ALL_TOOL_ROLES` to include tool messages in UI
- **P3**: Chat history limit too low — changed `limit=1000` to `limit=None` for sessions with 4000+ messages
- **P4**: Datetime serialization error — fixed `api_get_profile` datetime → ISO string conversion
- **P5**: Missing Database methods — added `add_image_tools_message`, `add_tool_result`, `add_system_note`, `add_memory_note`

## \[1.0.69.29\] - 2026-03-27

### Fixed — Memory System (Critical)

- **C1**: `process_messages_for_memory` name collision — canonical function is now `extractor.process_messages_for_memory`; removed shadowing alias from `file segmenter.py`
- **C2**: `source_episodic_ids` never populated — `create_episodic_memory` now accepts `source_message_ids` and cross-links episodic↔semantic records
- **C3**: Inconsistent `access_count` initialization — standardized `access_count=1` for new records across all creation paths

### Fixed — Memory System (High)

- **H1**: Idempotency check missed `ConversationSegment` — added `seg_count > 0` to `already_initialized` guard in `file app.py` session init
- **H2**: Semantic extraction not idempotent — `upsert_semantic_memory` now uses embedding cosine similarity (&gt;0.95) duplicate detection, matching `memory_store` tool strategy; prevents near-duplicate fact accumulation
- **H3**: Last segment silently discarded when &lt; 5 messages — removed minimum threshold; final group always flushed as a segment
- **H4**: `file migrate_history.py` type mismatch — `segment_count = segment_session()` returned `dict`, not `int`; fixed to `seg_result.get('segments_created', 0)`

### Fixed — Memory System (Medium)

- **M1**: Inconsistent `confidence`/`importance` across creation paths — standardized to `confidence=0.7, importance=0.7` in `upsert_semantic_memory` and all migration paths
- **M3**: `file models.py` was empty and misleading — now properly re-exports `SemanticMemory`, `EpisodicMemory`, `ConversationSegment` from `app.database` with `__all__`
- **M4**: `source_episode_id` misattributed — all facts in a batch were tagged with `batch[0]["id"]`; fixed to round-robin per-episode attribution
- **M5**: Inconsistent dedup strategy between `memory_store` tool and `upsert_semantic_memory` — resolved (both now use cosine similarity &gt;0.95)

### Added — Memory System

- `app.memory.extractor`: `__all__` exported for clean import surface
- `app.memory.segmenter`: `__all__` exported (`segment_session`, `_detect_boundaries`, `_create_segment`)

## \[1.0.69.28v4\] - 2026-03-24

### Added

- Embedding model for semantic memory search
- Preview button for HTML codeblocks
- Docker installation support (Dockerfile, docker-compose.yml)

### Fixed

- Various bug fixes