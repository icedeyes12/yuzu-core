# 蛇足 (Snake Feet) Audit — Yuzu Companion

> **Date:** 2026-06-28
> **Scope:** Full codebase audit for unnecessary complexity
> **Goal:** Simplify, make robust, future-proof

---

## Executive Summary

The codebase has **~4,500+ lines of dead/redundant code** across the DB layer, provider layer, and orchestrator. The most critical issue is the **complete duplication of the database layer** (`models.py` and `models_async.py` are near-identical copies), plus a **dual tool-protocol system** (`<command>` blocks AND native function calling) that creates two parallel execution paths in the orchestrator. There are also several dead functions, over-abstracted provider dispatch layers, and redundant SQL queries.

---

## Issues Found

### 1. CRITICAL: Entire `app/db/models.py` is dead code (sync DB layer)

- **File:** `app/db/models.py` (583 lines)
- **Lines:** 1–583 (entire file)
- **What's wrong:** The sync `models.py` is a complete duplicate of `models_async.py`. Every function has an async counterpart that is the one actually used. The sync version is imported only by `facade.py` and `__init__.py` to populate the `Database` class sync methods, but those sync methods are never called from the async FastAPI application. AGENTS.md line 624 explicitly says "Don't import `models.py` directly from business logic." The facade's sync methods are dead code.
- **Suggested fix:** Remove `models.py` entirely. Remove all sync method assignments from `facade.py` (lines 158–236 sync portion). Remove sync imports from `__init__.py`. This eliminates ~583 lines + ~80 lines of facade boilerplate.
- **Priority:** Critical
- **Effort:** Medium (need to verify no CLI/scripts use sync path)

### 2. CRITICAL: Dual tool protocol — `<command>` blocks AND native function calling

- **File:** `app/orchestrator.py`, `app/commands.py`, `app/prompts.py`
- **Lines:** orchestrator.py:459–505 (`_process_tool_commands_async`), 508–645 (`_run_orchestration_loop_async`); commands.py:119–212 (`parse_tool_blocks`); prompts.py:367–440 (tool section in system prompt)
- **What's wrong:** The system maintains TWO parallel tool invocation protocols:
  1. **Native function calling** (OpenAI `tool_calls` in API response) — used in `handle_user_message()` (lines 768–834)
  2. **`<command>` block parsing** (text regex from response) — used in `handle_user_message_streaming()` (lines 1055–1098) and `_run_orchestration_loop_async`
  
  The sync path (`handle_user_message`) uses native tool_calls. The streaming path (`handle_user_message_streaming`) uses `<command>` block parsing. This means the system prompt must document BOTH protocols (prompts.py lines 376–440), and the model must be trained on both. The streaming path re-implements tool execution via `parse_tool_blocks → execute_commands` which duplicates `_execute_tool_calls_async`.
  
  The `_build_streaming_ephemeral_context` function (lines 253–283) exists solely to reconstruct conversation context for the streaming path because it doesn't have structured tool_calls.
- **Suggested fix:** Standardize on native function calling for both paths. The streaming path should use `stream: true` with tool_calls in the SSE stream (OpenRouter supports this). Remove `_process_tool_commands_async`, `_run_orchestration_loop_async`, `_build_streaming_ephemeral_context`, and the `<command>` block tool section from the system prompt. If streaming with tool_calls isn't possible with current providers, keep `<command>` blocks as the single protocol and remove native function calling from the sync path.
- **Priority:** Critical
- **Effort:** High (requires provider support verification)

### 3. HIGH: `_build_ephemeral_context` is dead code

- **File:** `app/orchestrator.py`
- **Lines:** 192–250
- **What's wrong:** `_build_ephemeral_context` is defined but never called. The streaming path uses `_build_streaming_ephemeral_context` instead. The sync path (`handle_user_message`) doesn't use any ephemeral context — it persists tool_calls to DB and relies on DB history for synthesis.
- **Suggested fix:** Delete `_build_ephemeral_context`.
- **Priority:** High
- **Effort:** Trivial

### 4. HIGH: `_persist_observation_async` is dead code

- **File:** `app/orchestrator.py`
- **Lines:** 360–366
- **What's wrong:** `_persist_observation_async` is defined but never called anywhere in the codebase. It was likely superseded by `_persist_tool_result_async`.
- **Suggested fix:** Delete `_persist_observation_async`.
- **Priority:** High
- **Effort:** Trivial

### 5. HIGH: `_apply_vision_routing` is a no-op stub

- **File:** `app/llm_client.py`
- **Lines:** 123–132
- **What's wrong:** The function body is just `return messages, provider, model` — it does nothing. The docstring says "DEPRECATED: Automatic vision model switching is removed." But the function is still defined and presumably called (though I found no callers). It's dead code with a deprecation note but never removed.
- **Suggested fix:** Delete `_apply_vision_routing` and any references.
- **Priority:** High
- **Effort:** Trivial

### 6. HIGH: `_get_relevant_tools` return value is discarded

- **File:** `app/prompts.py`
- **Lines:** 287–336 (definition), 365 (call site)
- **What's wrong:** Line 365 calls `_get_relevant_tools(user_message or "")` but discards the return value. The function builds tool documentation strings but they're never used. The actual tool section in the system prompt is the hardcoded block at lines 367–440.
- **Suggested fix:** Remove the call on line 365. Consider removing the entire `_get_relevant_tools` function (lines 287–336) since it's dead code, OR wire it up if selective tool documentation is desired.
- **Priority:** High
- **Effort:** Trivial

### 7. HIGH: `format_observation` in commands.py is only used by tests

- **File:** `app/commands.py`
- **Lines:** 390–450
- **What's wrong:** `format_observation` wraps tool results in `<SYSTEM_OBSERVATION>` tags. It's only referenced in `tests/test_commands.py`. No production code calls it. The orchestrator uses `_persist_tool_result_async` directly instead.
- **Suggested fix:** Delete `format_observation` (and its tests).
- **Priority:** High
- **Effort:** Trivial

### 8. HIGH: `send_message_raw` in base class is a sync-in-async antipattern

- **File:** `app/providers/base.py`, `app/providers/openrouter.py`, `app/providers/ollama.py`, `app/providers/cerebras.py`
- **Lines:** base.py:254–260, 384–403; openrouter.py:145–172; ollama.py:33; cerebras.py:30
- **What's wrong:** `send_message_raw` is declared `async` in the base class (line 254) but the OpenRouter, Ollama, and Cerebras implementations are **synchronous methods** using `requests.post` (blocking I/O). Only Chutes has a proper async implementation. The base class's `send_message_raw` (line 257) calls `self.send_message()` which is also sync in most providers. This means `await ai_manager.send_message_raw(...)` in `llm_client.py:186` is awaiting a coroutine that wraps blocking `requests.post` calls — blocking the event loop.
- **Suggested fix:** Either: (a) make all providers use `httpx.AsyncClient` for true async, or (b) wrap sync calls with `asyncio.to_thread()` / `loop.run_in_executor()`. The base class `send_message_raw` should not be `async` if implementations are sync.
- **Priority:** High (correctness/performance)
- **Effort:** Medium

### 9. MEDIUM: `chutes_chat` in `llm_client.py` duplicates provider functionality

- **File:** `app/llm_client.py`
- **Lines:** 31–117
- **What's wrong:** `chutes_chat` is a standalone function that directly calls the Chutes API, completely bypassing the provider registry and `ChutesProvider`. It has its own retry logic, rate limiting, and error handling that duplicates what the provider class does. It's a parallel code path outside the architecture.
- **Suggested fix:** Remove `chutes_chat` and route all Chutes calls through `ChutesProvider`. If it's used by scripts, have them use the provider manager instead.
- **Priority:** Medium
- **Effort:** Low

### 10. MEDIUM: `get_recent_sessions` / `get_recent_sessions_for_session` are dead code

- **File:** `app/db/models.py:443–450`, `app/db/models_async.py:464–475`
- **What's wrong:** `get_recent_sessions` queries `SQL_MESSAGE_RECENT_SYSTEM_GLOBAL` (system messages) and returns them as "recent sessions" — but the actual session topology in prompts.py uses `get_recent_active_sessions_async` (which queries `chat_sessions` table). `get_recent_sessions` and `get_recent_sessions_for_session` have no callers outside of being defined and exported.
- **Suggested fix:** Delete `get_recent_sessions`, `get_recent_sessions_for_session`, and their async counterparts. Remove from `__all__` and facade.
- **Priority:** Medium
- **Effort:** Low

### 11. MEDIUM: `add_memory_note` / `add_memory_note_async` are pure aliases

- **File:** `app/db/models.py:466–468`, `app/db/models_async.py:520–521`, `app/db/facade.py:484–497`
- **What's wrong:** `add_memory_note` is literally `return add_system_note(session_id, content)` — a 1-line alias maintained in 3 files (models.py, models_async.py, facade.py) with 4 exported names. The docstring says "Alias for add_system_note."
- **Suggested fix:** Remove `add_memory_note` entirely. If any callers exist, replace with `add_system_note`.
- **Priority:** Medium
- **Effort:** Low

### 12. MEDIUM: `get_recent_messages` / `get_recent_messages_async` are pure aliases

- **File:** `app/db/models.py:392–394`, `app/db/models_async.py:413–414`
- **What's wrong:** `get_recent_messages` is `return get_session_messages(session_id, limit)` — a 1-line alias. The docstring even says "Alias kept for backward compatibility with older callers." Exported in `__all__` and facade.
- **Suggested fix:** Remove the alias, update any callers to use `get_session_messages` directly.
- **Priority:** Medium
- **Effort:** Low

### 13. MEDIUM: `add_tool_result` / `add_tool_result_async` are redundant wrappers

- **File:** `app/db/models.py:458–459`, `app/db/models_async.py:510–513`
- **What's wrong:** `add_tool_result` is `return add_message(session_id, tool_role_for(tool_name), result_content)` — a thin wrapper. The orchestrator already has `_persist_tool_result_async` which does the same thing but with proper `tool_call_id` support. `add_tool_result` doesn't support `tool_call_id`, `image_paths`, or `user_id`.
- **Suggested fix:** Delete `add_tool_result`. All tool result persistence should go through `_persist_tool_result_async` in the orchestrator.
- **Priority:** Medium
- **Effort:** Low

### 14. MEDIUM: `update_session_memory` vs `update_memory_state` — overlapping responsibilities

- **File:** `app/db/models_async.py:215–224` vs `app/db/models_async.py:272–285`
- **What's wrong:** `update_session_memory` blindly overwrites `memory_state` with the given dict. `update_memory_state` reads existing state, merges, then writes. Both write to the same column. `update_memory_state` is the correct approach (atomic merge), while `update_session_memory` is dangerous (overwrites). But both exist and are exported.
- **Suggested fix:** Remove `update_session_memory`. All callers should use `update_memory_state` which does proper merge semantics.
- **Priority:** Medium
- **Effort:** Low

### 15. MEDIUM: `get_session_memory` queries wrong data

- **File:** `app/db/queries.py:443–449`, `app/db/models_async.py:227–229`
- **What's wrong:** `get_session_memory` queries `SQL_SESSION_MEMORY_NOTES` which fetches `role IN ('system', 'memory')` messages — NOT the `memory_state` column from `chat_sessions`. But the function name and callers expect session memory context. Meanwhile, `get_memory_state` reads the actual `memory_state` column. These are two different things with confusingly similar names.
- **Suggested fix:** Rename `get_session_memory` to `get_session_notes` or similar to clarify it fetches historical system/memory messages, not the current memory state.
- **Priority:** Medium
- **Effort:** Low

### 16. MEDIUM: `suppress_tools` parameter is overloaded

- **File:** `app/llm_client.py`, `app/prompts.py`, `app/providers/base.py`, `app/providers/openrouter.py`
- **Lines:** llm_client.py:177, 225, 266, 299; prompts.py:345, 535; base.py:275; openrouter.py:176
- **What's wrong:** `suppress_tools` is threaded through 4 layers (orchestrator → llm_client → prompts → provider) and does two different things: (1) strips tool definitions from the API call, (2) removes tool docs from system prompt. In the OpenRouter provider, it only does (1) — popping `tools` from payload. The synthesis pass always uses `suppress_tools=True`, which means the model can't do multi-step tool use during synthesis. This is correct behavior but the parameter name and threading are confusing.
- **Suggested fix:** Consider splitting into two explicit parameters (`include_tools_in_api` and `include_tools_in_prompt`) or at minimum document the dual effect clearly.
- **Priority:** Medium
- **Effort:** Low

### 17. LOW: `SQL_SESSION_MEMORY_NOTES` queries non-existent 'memory' role

- **File:** `app/db/queries.py:443–449`
- **What's wrong:** The SQL filters `role IN ('system', 'memory')` but there is no 'memory' role in the system. Tool results use specific roles like `image_tools`, `shell_tools`, etc. The 'memory' role condition is dead.
- **Suggested fix:** Change to `role = 'system'` or remove the IN clause.
- **Priority:** Low
- **Effort:** Trivial

### 18. LOW: `format_relative_time` has redundant branch

- **File:** `app/prompts.py:72–113`
- **Lines:** 82–87
- **What's wrong:** The `if "T" in ts_str` and `else` branches do the exact same thing: `iso_str = ts_str.split("+")[0].split(".")[0]; past = datetime.fromisoformat(iso_str)`. The condition is meaningless.
- **Suggested fix:** Remove the if/else and just execute the common code.
- **Priority:** Low
- **Effort:** Trivial

### 19. LOW: `build_profile_update` doesn't include all profile fields

- **File:** `app/db/queries.py:325–353`
- **What's wrong:** `build_profile_update` has an allowlist (`_PROFILE_JSON_FIELDS`, `_PROFILE_TEXT_FIELDS`) that doesn't include `avatar_url`, `location_lat`, `location_lon`, or `image_model`/`vision_model` (wait, those two are in `_PROFILE_TEXT_FIELDS`). But `avatar_url` and location columns exist in the schema and have dedicated update SQL constants (`SQL_PROFILE_UPDATE_AVATAR`) that are never used by `build_profile_update`.
- **Suggested fix:** Either extend the allowlist or remove the dedicated SQL constants if `build_profile_update` is meant to be the single path.
- **Priority:** Low
- **Effort:** Trivial

### 20. LOW: `DEFAULT_PROFILE_PARAMS` includes `timestamp` which is redundant

- **File:** `app/db/queries.py:296–307`
- **What's wrong:** `DEFAULT_PROFILE_PARAMS` includes `"{}"` for `timestamp` column, but the schema has `timestamp TIMESTAMP DEFAULT NOW()` — the DB will set it automatically. Passing it explicitly is redundant.
- **Suggested fix:** Remove `timestamp` from `DEFAULT_PROFILE_PARAMS` and from `SQL_PROFILE_INSERT_DEFAULT`.
- **Priority:** Low
- **Effort:** Trivial

---

## Priority Summary

| Priority | Count | Est. Lines to Remove |
|----------|-------|---------------------|
| Critical | 2 | ~1,200 |
| High | 5 | ~350 |
| Medium | 8 | ~400 |
| Low | 5 | ~30 |
| **Total** | **20** | **~1,980** |

## Recommended Order of Attack

1. **Dead function cleanup** (issues 3, 4, 5, 6, 7) — trivial, zero risk, immediate clarity
2. **Remove sync `models.py`** (issue 1) — biggest single win, need to verify no CLI dependency
3. **Unify tool protocol** (issue 2) — highest architectural impact
4. **Fix sync-in-async providers** (issue 8) — correctness fix
5. **Remove redundant aliases** (issues 10, 11, 12, 13) — incremental simplification
6. **Clean up SQL/query issues** (issues 15, 17, 19, 20) — polish
