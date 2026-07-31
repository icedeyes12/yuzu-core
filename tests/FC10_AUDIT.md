# FC10 — Coverage Audit Report

> **Date:** 2026-06-30
> **Phase:** A — Coverage Audit (before writing tests)

---

## Existing Test Files

| File | Lines | Relevance to FC Migration |
|------|-------|--------------------------|
| `test_commands.py` | 175 | HIGH — tests legacy `<command>` parser + `execute_commands` |
| `test_db_queries.py` | 312 | MEDIUM — tests `format_ai_history_rows`, `parse_message_row`, tool contract parsers |
| `test_database_facade.py` | ~200 | LOW — tests DB facade, not directly FC-related |
| `test_memory.py` | ~150 | LOW — memory pipeline, not FC-specific |
| `test_shell_exec.py` | ~100 | LOW — individual tool, not protocol |
| `test_python_exec.py` | ~100 | LOW — individual tool, not protocol |
| `test_fs_operations.py` | ~100 | LOW — individual tool, not protocol |
| `test_db_query.py` | ~80 | LOW — individual tool, not protocol |
| `test_profile_analysis.py` | ~100 | LOW — deleted module tests |
| `test_vision_pipeline.py` | ~150 | LOW — vision, not FC protocol |
| `test_tenant_isolation.py` | ~100 | LOW — multi-tenancy, not FC |

---

## Classification of Existing Tests

### `test_commands.py`

| Test Class | Action | Rationale |
|------------|--------|-----------|
| `TestParseToolBlocks` | **KEEP** | Parser still used by orchestrator (strip-and-warn) and `has_tool_blocks` |
| `TestHasToolBlocks` | **KEEP** | Used in orchestration loop |
| `TestParseImagePath` | **KEEP** | Used in persistence layer |
| `TestExecuteCommands` | **UPDATE** | Rename to `TestExecuteCommandsLegacy`, add assertion that it's NOT called from orchestrator |

### `test_db_queries.py`

| Test Class | Action | Rationale |
|------------|--------|-----------|
| `TestFormatAiHistoryRows` | **UPDATE** | Add coverage for `tool_calls` JSONB + `turn_id` reconstruction |
| `TestToolContractParsers` | **KEEP** | Legacy contract parsers still in use |
| `TestToolRoleHelpers` | **KEEP** | Role mapping still used |
| All others | **KEEP** | Unrelated to FC |

---

## Missing Coverage (Introduced by FC1–FC9)

### Tool Registry (`app/tools/schemas.py`, `app/tools/registry.py`)
- ❌ `ToolDefinition.to_llm_schema()` serialization
- ❌ `get_tool_schemas()` deduplication + filtering
- ❌ `get_tool_capabilities()` capability flags
- ❌ `execute_tool_event()` → `ToolResultEvent` round-trip
- ❌ `make_tool_call_event()` factory
- ❌ `StreamToolEvent.to_sse()` serialization

### Provider Layer (`app/providers/`)
- ❌ `ProviderCapabilities` declaration accuracy
- ❌ `AIProviderManager.provider_supports_tools()` routing
- ❌ `AIProviderManager.parse_tool_calls()` canonical output
- ❌ OpenRouter streaming tool-call delta parsing
- ❌ `supports_streaming_fc` matches actual behavior

### LLM Client (`app/services/llm_client.py`)
- ❌ `_unique_tool_schemas()` deduplication
- ❌ Streaming yields `str | StreamToolEvent` union type
- ❌ `provider_supports_fc` passed to `build_messages`

### Orchestrator (`app/services/orchestrator.py`)
- ❌ `_parse_raw_tool_calls_async()` canonical output
- ❌ `_execute_tool_calls_async()` event-driven dispatch
- ❌ Streaming `StreamToolEvent` handling
- ❌ `turn_id` propagation through persistence
- ❌ `<command>` blocks stripped (not executed) in synthesis loop

### Streaming (`app/services/stream_manager.py`, `app/services/chat_service.py`)
- ❌ `StreamBuffer` handles `StreamToolEvent` objects
- ❌ `ChatService` serializes typed events as SSE
- ❌ SSE envelope shapes: token, tool_call, tool_result, done

### Persistence (`app/db/queries.py`)
- ❌ `turn_id` in `parse_message_row`
- ❌ `format_ai_history_rows` with `tool_calls` JSONB + `turn_id`
- ❌ `format_ai_history_rows` with `tool_call_id` (OpenAI format)

### Frontend (`static/js/modules/multimodal.js`)
- ❌ Typed event parsing (token, tool_call, tool_result, done)
- ❌ Tool call indicator rendering
- ❌ Tool result rendering

### System Prompt (`app/services/prompt_service.py`)
- ❌ `provider_supports_fc=True` → native FC instructions
- ❌ `provider_supports_fc=False` → `<command>` instructions

---

## Test Plan

### New Test Files

1. **`test_fc_registry.py`** — Tool registry + event schema
2. **`test_fc_provider.py`** — Provider capability matrix + parsing
3. **`test_fc_orchestrator.py`** — Orchestrator event dispatch + streaming
4. **`test_fc_streaming.py`** — SSE event envelope + StreamToolEvent
5. **`test_fc_persistence.py`** — turn_id + tool_calls reconstruction

### Updated Test Files

1. **`test_commands.py`** — Rename `TestExecuteCommands` → `TestExecuteCommandsLegacy`
2. **`test_db_queries.py`** — Add `turn_id` + `tool_calls` reconstruction tests

### Estimated Test Count

- ~40 new tests across 5 new files
- ~5 updated tests in 2 existing files
- Total: ~45 tests covering the FC architecture end-to-end
