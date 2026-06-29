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

## Phase 1 — Verify audit coverage

### Top-level repository checklist

| Top-level directory/package | Status | Notes |
| --- | --- | --- |
| `.gemini/` | Not audited | Tooling scratch space, not part of the application surface. |
| `.github/` | Not audited | Repository automation and CI config were not reviewed in this pass. |
| `.hermes/` | Not audited | Local metadata/tooling area, not part of the runtime surface. |
| `.pytest_cache/` | Not audited | Cache directory, excluded from code audit. |
| `.ruff_cache/` | Not audited | Cache directory, excluded from code audit. |
| `__pycache__/` | Not audited | Bytecode cache, excluded from code audit. |
| `app/` | Partially audited | Core backend was reviewed previously, but `app/auth/`, `app/core/`, `app/services/`, and `app/api/endpoints/` still need file-level review. |
| `archive/` | Not audited | Historical material only; not reviewed for runtime behavior. |
| `cli/` | Partially audited | CLI structure and a subset of files were inspected, but the package was not reviewed end-to-end. |
| `docs/` | Not audited | Documentation and roadmap history were not audited as code. |
| `migrations/` | Not audited | Migration scripts were not reviewed in this pass. |
| `scripts/` | Partially audited | File inventory was checked, but the scripts were not reviewed individually. |
| `static/` | Partially audited | Frontend structure was inspected, but the JS/CSS surface is still incomplete. |
| `templates/` | Not audited | Template files were listed but not reviewed line-by-line. |
| `tests/` | Partially audited | Test inventory was checked, but the suite was not fully reviewed. |
| `yuzu_companion.egg-info/` | Not audited | Packaging metadata only; no runtime behavior. |

### Missing or partially reviewed areas

- `app/auth/`
- `app/core/`
- `app/services/`
- `app/api/endpoints/`
- `cli/`
- `static/js/`
- `static/css/`
- `templates/`
- `scripts/`
- `tests/`
- `archive/`
- `docs/`
- `migrations/`

The current audit report is therefore **incomplete**. The remaining work is concentrated in the service layer, auth/session plumbing, API endpoint wrappers, and the still-partially reviewed frontend and utility surfaces.

---

## Phase 2 — New findings from the unaudited areas

### 21. HIGH: `SessionService` keeps a large legacy sync surface that the live app does not use

- **File:** `app/services/session_service.py`
- **Lines:** 38–143, 264–314
- **What's wrong:** The class carries a parallel sync API and several legacy helpers that are not used by the live app: `start_session`, `end_session_cleanup`, `generate_connection_msg`, `_last_active_timestamp`, `_bootstrap_memory`, and `_bootstrap_memory_async`. The current API routes and orchestrator only call the async path (`start_session_async`, `end_session_cleanup_async`, `auto_name_session_if_needed_async`). The sync methods are only referenced by legacy docs and archived code, not by the current runtime path.
- **Why it matters:** This doubles the surface area of the service for no production benefit and makes it harder to see which path is authoritative. It also keeps deprecated connection-log behavior around even though the app explicitly stopped using it.
- **Impact:** Medium
- **Simplest practical fix:** Remove the sync wrappers and the unused helper methods after confirming no live caller needs them. Keep the async path as the single implementation.

### 22. HIGH: `ConfigService` still exposes dead sync setters alongside the live async API

- **File:** `app/services/config_service.py`
- **Lines:** 119–141
- **What's wrong:** `set_preferred_provider()` and `set_vision_model()` are sync wrappers around the async configuration path, but the current API routes call only `set_preferred_provider_async()` and `set_vision_model_async()`. The sync wrappers are only referenced by legacy docs and archived code.
- **Why it matters:** The extra wrappers do nothing but widen the public API and preserve an unnecessary `asyncio.run()` boundary. That is avoidable complexity in a service that already has a clean async call path.
- **Impact:** Medium
- **Simplest practical fix:** Delete the sync setters and keep the async versions only. If any scripts still need sync behavior, move them onto the async API explicitly instead of maintaining two code paths.

### 23. MEDIUM: The memory pipeline throttle is split across two conflicting constants

- **File:** `app/orchestrator.py`, `app/services/memory_service.py`
- **Lines:** orchestrator.py:426; memory_service.py:20, 78
- **What's wrong:** `app/orchestrator.py` still defines `_PIPELINE_CHECK_INTERVAL = 5`, but the live per-message throttle is now owned by `MemoryService._PIPELINE_CHECK_INTERVAL = 50`. The orchestrator constant is no longer the behavior source.
- **Why it matters:** Two constants with different values make the actual trigger cadence easy to misread. That invites accidental edits in the wrong layer and obscures which code path really controls pipeline pressure.
- **Impact:** Low
- **Simplest practical fix:** Delete the stale orchestrator constant and keep the throttle in one place only.

### 24. LOW: `api_update_weather_location` is a pure alias with no behavioral difference

- **File:** `app/api/endpoints/profile.py`
- **Lines:** 171–176
- **What's wrong:** `api_update_weather_location()` does nothing except call `api_update_location()` with the same payload. It adds no validation, no transformation, and no compatibility guard beyond the route name.
- **Why it matters:** This is duplicate surface area for the same behavior. It makes the endpoint list look larger than it is and gives future changes two route names to keep in sync for no gain.
- **Impact:** Low
- **Simplest practical fix:** Collapse it into a single route. If compatibility is required, keep the alias only at the router level or document it as a compatibility shim.

### 25. MEDIUM: `api_test_vision` is a fake test endpoint

- **File:** `app/api/endpoints/profile.py`
- **Lines:** 184–185
- **What's wrong:** The endpoint always returns `{"status": "success", "message": "Vision model test successful"}` without calling any provider or checking any model. It is a stub that reports success regardless of reality.
- **Why it matters:** A test endpoint that cannot fail is misleading. It hides provider regressions and creates a false sense of validation in the API surface.
- **Impact:** Medium
- **Simplest practical fix:** Either wire it to a real provider health check or remove it entirely if the app does not need a dedicated vision test endpoint.

---

## Phase 3 — Continued audit of remaining surfaces

### 26. MEDIUM: `get_client_id()` uses Python's salted `hash()` and is not stable across restarts

- **File:** `app/api/utils.py`
- **Lines:** 7–10
- **What's wrong:** `get_client_id()` builds the client key from `request.client.host` plus `hash(user_agent) % 10000`. Python's `hash()` is salted per process, so the same user agent can produce a different client ID after restart. The `% 10000` also keeps collisions cheap.
- **Why it matters:** Session-tracking and duplicate-connection suppression become non-deterministic across restarts. A browser can look like a new client just because the process restarted.
- **Impact:** Medium
- **Simplest practical fix:** Replace the salted hash with a stable digest such as SHA-256 truncated to a small prefix, or use the authenticated session/user ID instead of user-agent hashing.

### 27. LOW: History pagination helpers are exported but unused

- **File:** `static/js/modules/history.js`, `static/js/modules/state.js`
- **Lines:** history.js: 13–31; state.js: 6–10
- **What's wrong:** `isHistoryLoading()`, `getPendingSessionId()`, and `_currentPage` are exported, but no code in the repository imports them. They are public API with no consumer.
- **Why it matters:** Dead exports increase the frontend surface and make the history module look more stateful than it is. That makes future changes harder to reason about.
- **Impact:** Low
- **Simplest practical fix:** Remove the unused exports and keep the loading state local to `history.js` until there is an actual consumer.

### 28. LOW: `MultimodalManager.finalizeStreamMessage()` is dead code

- **File:** `static/js/modules/multimodal.js`
- **Lines:** 486–529
- **What's wrong:** `finalizeStreamMessage()` is defined but has no callers in the current repository. The live streaming path already finalizes through `renderStreamChunk()` and the stream completion flow, so this helper never runs.
- **Why it matters:** There are now two finalization paths in the file, but only one is active. That is exactly the sort of leftover branch that makes streaming bugs harder to audit.
- **Impact:** Medium
- **Simplest practical fix:** Delete `finalizeStreamMessage()` and keep all finalization logic in the active completion path.

### 29. LOW: `cli/widgets/chat_log.py` has a dead hidden-tag filtering path

- **File:** `cli/widgets/chat_log.py`
- **Lines:** 13–15, 57–91
- **What's wrong:** `HIDDEN_TAGS` and `_filter_hidden_tags()` exist, but `_parse_and_render_content()` does not call them. Instead, it strips every angle-bracket tag with a generic regex. The specialized hidden-tag path is therefore unused.
- **Why it matters:** The widget carries two competing sanitization ideas, but only the broad tag stripper actually executes. That makes the code look more intentional than it is.
- **Impact:** Low
- **Simplest practical fix:** Remove the dead hidden-tag helper and its constant, or wire it into `_parse_and_render_content()` if that was the real intent.

### 30. MEDIUM: `init_new_session()` / `init_new_session_async()` are unused leftovers and the sync version assumes the wrong profile shape

- **File:** `app/services/session_service.py`
- **Lines:** 385–434
- **What's wrong:** Neither `init_new_session()` nor `init_new_session_async()` has a caller in the live codebase. Worse, both treat `session_history` as a scalar counter (`(profile.get("session_history") or 0) + 1`), even though the active code paths elsewhere use it as a dictionary of session metadata.
- **Why it matters:** This is dead code that also encodes the wrong data shape, so it is actively misleading if anyone finds it later and tries to reuse it.
- **Impact:** Medium
- **Simplest practical fix:** Delete both helpers. If a session bootstrap helper is still needed, reintroduce one version that matches the current `session_history` schema.

---

## Phase 4 — Additional findings from remaining audited surfaces

### 31. LOW: `generate_token()` in `app/auth/session.py` is a one-line wrapper with no added value

- **File:** `app/auth/session.py`
- **Lines:** 17–19
- **What's wrong:** `generate_token()` just returns `secrets.token_urlsafe(32)`, and it has only one caller (`create_session()`). The wrapper adds no policy, no validation, and no naming benefit.
- **Why it matters:** This is pure ceremony. One extra function for a single standard-library call makes the session module look more complex than it is.
- **Impact:** Low
- **Simplest practical fix:** Inline the token generation into `create_session()` and delete `generate_token()`.

### 32. LOW: `_persist_display_name()` in `app/api/endpoints/auth.py` is an unnecessary helper around a single DB call

- **File:** `app/api/endpoints/auth.py`
- **Lines:** 95–100
- **What's wrong:** `_persist_display_name()` wraps a single `Database.update_profile_display_name_async()` call and is only used inside `_map_identity_to_profile()`.
- **Why it matters:** The helper does not reduce duplication enough to justify another named function. It adds indirection in the exact place where the auth/profile flow should stay obvious.
- **Impact:** Low
- **Simplest practical fix:** Inline the display-name update call at the two call sites and delete `_persist_display_name()`.

### 33. LOW: History loading state exports in `static/js/modules/history.js` and `static/js/modules/state.js` have no consumers

- **File:** `static/js/modules/history.js`, `static/js/modules/state.js`
- **Lines:** history.js: 13–31; state.js: 6–10
- **What's wrong:** `isHistoryLoading()`, `getPendingSessionId()`, and `_currentPage` are exported, but nothing in the repository imports them. The loading guard is already private inside `history.js`.
- **Why it matters:** Dead exports inflate the module surface and make the history/state split look intentional when it is really just leftover scaffolding.
- **Impact:** Low
- **Simplest practical fix:** Remove the unused exports and keep the history-loading state private until a real consumer appears.

### 34. MEDIUM: `MultimodalManager.finalizeStreamMessage()` is dead code

- **File:** `static/js/modules/multimodal.js`
- **Lines:** 486–529
- **What's wrong:** `finalizeStreamMessage()` has no callers in the current repository. The active streaming path finalizes through `renderStreamChunk()` and the stream completion flow instead.
- **Why it matters:** This leaves two competing finalization concepts in the same module while only one is alive. That is needless complexity in the most fragile part of the frontend.
- **Impact:** Medium
- **Simplest practical fix:** Delete `finalizeStreamMessage()` and keep the single active completion path.

### 35. LOW: `cli/widgets/chat_log.py` keeps a dead hidden-tag filtering path

- **File:** `cli/widgets/chat_log.py`
- **Lines:** 13–15, 57–91
- **What's wrong:** `HIDDEN_TAGS` and `_filter_hidden_tags()` exist, but `_parse_and_render_content()` never calls them. The actual code path strips all angle-bracket tags with a generic regex, so the hidden-tag-specific helper is unused.
- **Why it matters:** The widget carries two sanitization ideas, but only one executes. That is extra surface area with no behavior change.
- **Impact:** Low
- **Simplest practical fix:** Remove `HIDDEN_TAGS` and `_filter_hidden_tags()` unless you wire the helper into `_parse_and_render_content()`.

---

## Phase 4 — static/css/

### 31. LOW: `static/css/index.css` is orphaned

- **File:** `static/css/index.css`
- **What’s wrong:** This stylesheet exists in the repository but is not referenced by any template or bundle in the live app. The runtime pages load `style.css`, `theme.css`, `chat.css`, `home.css`, `about.css`, `config.css`, `sidebar.css`, `marked.css`, and `multimodal.css`, but not `index.css`.
- **Why it matters:** Dead stylesheets are maintenance debt. They drift, confuse ownership, and tempt future changes to land in a file that nothing actually uses.
- **Impact:** Low
- **Simplest practical fix:** Delete `index.css` unless a route is intentionally meant to use it, or wire it into one template and remove the duplicated baseline rules elsewhere.

### 32. Medium: Multimodal styling is split across two overlapping sources of truth

- **Files:** `static/css/multimodal.css`, `static/css/components/multimodal.css`, `static/css/chat.css`, `templates/chat.html`
- **What’s wrong:** The chat page pulls in `static/css/multimodal.css` directly in `templates/chat.html`, and `static/css/chat.css` separately imports `static/css/components/multimodal.css`. Both files style the same multimodal UI surface, so the active design is distributed across two parallel stylesheets.
- **Why it matters:** This is avoidable duplication. It increases the chance of drift, makes it harder to know which file is authoritative, and forces future fixes to be duplicated in two places.
- **Impact:** Medium
- **Simplest practical fix:** Pick one multimodal stylesheet as the canonical source, remove the other import path, and collapse the duplicated rules into the surviving file.

---

## Template audit findings

### 33. MEDIUM: `templates/multimodal_chat.html` is an orphaned legacy surface

- **File:** `templates/multimodal_chat.html`
- **What's wrong:** Nothing in `main.py` or the Jinja templates includes or routes to this page. It is a full alternate chat UI with its own inline CSS and markup, but it is not part of the live page set.
- **Why it matters:** Orphaned templates are dead maintenance surface. They drift independently, they can fool future work into editing the wrong page, and they waste attention during audits.
- **Impact:** Medium
- **Simplest practical fix:** Delete the template unless a route is intentionally meant to serve it.

### 34. LOW: `templates/chat.html` loads Tailwind CDN without using Tailwind utilities

- **File:** `templates/chat.html`
- **What's wrong:** The page includes `https://cdn.tailwindcss.com`, but the template itself uses project-specific class names and local stylesheets instead of Tailwind utility classes. The CDN script is not doing useful work.
- **Why it matters:** This adds a runtime network dependency for no behavior gain and makes the styling stack look more complex than it is.
- **Impact:** Low
- **Simplest practical fix:** Remove the Tailwind CDN `<script>` tag from `templates/chat.html`.

### 35. LOW: Footer markup is duplicated across the main HTML templates

- **Files:** `templates/index.html`, `templates/about.html`, `templates/config.html`
- **What's wrong:** The same footer content (`©2026 hkkm project | built with love`) is copied into three pages with only trivial wrapper differences.
- **Why it matters:** Duplicate template chrome is easy to forget when changing wording, years, or links. It is low-risk debt, but still unnecessary debt.
- **Impact:** Low
- **Simplest practical fix:** Extract the footer into a shared partial or macro and include it from the three pages.

---

## Priority Summary

| Priority | Count | Est. Lines to Remove |
|----------|-------|---------------------|
| Critical | 2 | ~1,200 |
| High | 5 | ~350 |
| Medium | 10 | ~430 |
| Low | 11 | ~70 |
| **Total** | **28** | **~2,080** |

## Recommended Order of Attack

1. **Dead/orphan cleanup** (issues 3, 4, 5, 6, 7, 31, 32, 33, 34, 35) — trivial, zero risk, immediate clarity
2. **Remove sync `models.py`** (issue 1) — biggest single win, need to verify no CLI dependency
3. **Unify tool protocol** (issue 2) — highest architectural impact
4. **Fix sync-in-async providers** (issue 8) — correctness fix
5. **Remove redundant aliases** (issues 10, 11, 12, 13, 36) — incremental simplification
6. **Clean up SQL/query issues** (issues 15, 17, 19, 20) — polish