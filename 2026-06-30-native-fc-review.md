# Native Function Calling Migration — Post-Implementation Architecture Review

> **Date:** 2026-06-30
> **Reviewer:** Reina (independent review, treating implementation as written by another engineer)
> **Scope:** End-to-end verification of FC1–FC8 against audit + plan
> **Method:** Static code trace across every layer; no code modifications made

---

## End-to-End Lifecycle Trace

### Non-Streaming Path (functional)

1. **Prompt construction** → `prompts.py` builds system prompt with `<command>` syntax docs (29 occurrences). Also emits `"Preferred: Use native function calling"` deprecation note (FC7).
2. **Tool schema generation** → `llm_client.py` calls `_unique_tool_schemas()` which delegates to `registry.get_tool_schemas()` (FC1). ✅ Canonical source.
3. **Provider request** → `generate_ai_response()` calls `send_message_raw()` with `tools=` param. OpenRouter attaches `tools` + `tool_choice: "auto"`. Other providers ignore it (no error). ✅
4. **Provider response parsing** → `_parse_raw_tool_calls_async()` uses `AIProviderManager.parse_tool_calls()` (FC2). Only OpenRouter parses `tool_calls` from `raw_response["choices"][0]["message"]["tool_calls"]`. Other providers return `[]`. ✅
5. **Tool dispatch** → If `tool_calls` found, `_execute_tool_calls_async()` creates `ToolCallEvent` via `make_tool_call_event()`, calls `execute_tool_event()` (FC1). ✅ Canonical path.
6. **Tool execution** → `execute_tool_event()` delegates to `execute_tool()` in registry. ✅ Single dispatch.
7. **Persistence** → Assistant message saved with `tool_calls` JSONB + `turn_id`. Tool results saved with `tool_call_id` + `turn_id`. History reconstruction in `format_ai_history_rows` uses structured data first, legacy `ALL_TOOL_ROLES` as fallback. ✅
8. **Synthesis** → 2nd LLM call with `suppress_tools=True`. ✅
9. **Orchestration loop** → No continuation loop in non-streaming path. Single pass.

### Streaming Path (partial)

1. **Prompt construction** → Same as non-streaming. ✅
2. **Tool schema generation** → `_stream_from_provider()` calls `_unique_tool_schemas()`, passes `tools=` to provider. ✅
3. **Provider streaming request** → `ai_manager.send_message_streaming()` with `tools=`. OpenRouter may emit `tool_calls` in SSE delta chunks, but no provider adapter parses streaming tool-call deltas. **Providers yield plain text chunks only.** ⚠️
4. **`__TOOL_CALLS__:` marker** → Orchestrator checks for `\n__TOOL_CALLS__:` in chunks (line 943). **No code in the entire repository emits this marker.** This branch is unreachable dead code. 🔴
5. **Streaming tool-call execution** → If `tool_calls_data` were populated (it cannot be), it would call `_execute_tool_calls_async()`. ✅ Logic exists but path unreachable.
6. **Synthesis loop** → `_run_orchestration_loop_async()` now strips `<command>` blocks with warning (FC7) and does NOT execute them. ✅ Correct behavior per plan.
7. **StreamBuffer** → Handles `StreamToolEvent` objects (FC5). Text accumulation only from token events. Passes `turn_id` to DB. ✅ But: **no code ever yields a `StreamToolEvent` into the stream.**
8. **ChatService** → Serializes `StreamToolEvent` via `to_sse()` (FC5), plain strings as `{"type": "token", "chunk": ..., "turn_id": ...}`. ✅ Wire format correct. But: **event emission is theoretical only.**

### Frontend (SSE consumer)

1. **SSE parsing** → Checks `json.type`. Handles `done`, `tool_call`, `tool_result`, and falls through to `json.chunk` for text. ✅ Backward compatible.
2. **Tool event rendering** → `tool_call` renders collapsible "Calling X…" indicator. `tool_result` renders collapsible result block with status icon. ✅ (FC6)
3. **History rendering** → Still renders legacy `<command>` / `<tools>` blocks from DB history via markdown renderer. No migration. ⚠️
4. **Rebind/reconnect** → Still text-buffer-based. No structural event state for resume. ⚠️

---

## Architectural Goal Verification

| Goal | Status | Evidence |
|------|--------|----------|
| No production path depends on `<command>` execution | ✅ MET | Orchestrator strips `<command>` blocks with warning; `execute_commands` not imported |
| No regex-based command execution remains | ✅ MET | `execute_commands` isolated in `commands.py`, not called from orchestrator |
| Native FC is canonical execution protocol | ⚠️ PARTIAL | Non-streaming: ✅. Streaming: no provider emits `tool_calls` in SSE; streaming FC is theoretical |
| Provider abstractions remain provider-agnostic | ✅ MET | `ProviderCapabilities` + `parse_tool_calls()` on `AIProvider`; routing via capability flags |
| Streaming and non-streaming follow same execution model | 🔴 NOT MET | Non-streaming: parses `tool_calls` from `raw_response`, executes. Streaming: text-only, no tool-call parsing |
| No duplicated execution logic | ✅ MET | Both paths use `_execute_tool_calls_async()` → `execute_tool_event()` |
| Obsolete compatibility layers removed | ⚠️ PARTIAL | `execute_commands` retained in `commands.py`, `extract_raw_result_from_markdown_contract` retained in `queries.py`, `ALL_TOOL_ROLES` fallback retained |
| Architectural boundaries clean | ✅ MET | Registry owns dispatch, providers own parsing, orchestrator owns flow |
| No unnecessary new abstractions | ✅ MET | `ProviderCapabilities`, `ToolCallEvent`, `ToolResultEvent`, `StreamToolEvent` all serve their stated purpose |
| No implementation shortcuts replaced planned architecture | ⚠️ SEE FINDINGS | `__TOOL_CALLS__:` marker is a shortcut that became dead code; `StreamToolEvent` is defined but never produced |

---

## Findings

### R1 — Streaming tool-call production path is missing

- **Severity:** CRITICAL
- **Observation:** No code in the repository emits `StreamToolEvent` objects or `__TOOL_CALLS__:` markers into the streaming pipeline. The orchestrator's streaming generator (`handle_user_message_streaming`) yields only plain `str` chunks. The `StreamToolEvent` dataclass, the `StreamBuffer` handling, and the frontend rendering code all exist but are never exercised in production.
- **Affected work packages:** FC5 (incomplete), FC6 (incomplete)
- **Affected components:** `app/orchestrator.py`, `app/llm_client.py`, `app/stream_manager.py`, `app/providers/openrouter.py`, `static/js/modules/multimodal.js`
- **Description:** FC5's completion criteria states: "The API can carry structured tool-call lifecycle events end-to-end." The plumbing exists but the producer (streaming orchestrator/provider layer) never generates typed events. When a provider like OpenRouter returns `tool_calls` in streaming mode (SSE delta chunks with `tool_calls` in the delta), the provider adapter does not parse them — it only yields text content. The orchestrator therefore never sees structured tool calls during streaming.
- **Recommendation:** Implement streaming tool-call parsing in `OpenRouterProvider.send_message_streaming()` (or `llm_client._stream_from_provider()`). When the provider emits a `tool_calls` delta, the streaming generator should yield a `StreamToolEvent(type="tool_call", ...)` instead of raw text. After all tool calls are collected, execute them and yield `StreamToolEvent(type="tool_result", ...)` events. This is the highest-priority gap.

### R2 — `__TOOL_CALLS__:` marker is dead code

- **Severity:** MAJOR
- **Observation:** The orchestrator checks for `\n__TOOL_CALLS__:` in streaming chunks (line 943) but no code anywhere in the repository produces this marker string.
- **Affected work packages:** FC3 (partial), FC5
- **Affected components:** `app/orchestrator.py`
- **Description:** This appears to be a planned integration point that was never connected. It creates a false sense of capability — the code path exists but is unreachable.
- **Recommendation:** Remove the `__TOOL_CALLS__:` detection block entirely. If streaming tool-call support is added (per R1), use the `StreamToolEvent` mechanism instead of a magic text marker.

### R3 — System prompt still teaches `<command>` as primary tool protocol

- **Severity:** MAJOR
- **Observation:** `prompts.py` contains 29 `<command>` syntax examples, usage instructions, and protocol rules. The only FC7 change is a two-line addition: "Preferred: Use native function calling" and "Legacy fallback... Deprecated." The actual tool documentation still exclusively uses `<command>` syntax.
- **Affected work packages:** FC7 (incomplete)
- **Affected components:** `app/prompts.py`
- **Description:** FC7's completion criteria states: "The repository no longer treats `<command>` as a production protocol; docs and operational guidance match the new contract." The system prompt is the most important operational document — it directly controls model behavior. When a non-FC provider (Ollama) receives this prompt, the model will attempt `<command>` blocks, which the orchestrator now strips without execution (FC7). This means **tool invocation through non-FC providers is silently broken** — the model emits `<command>` blocks which are discarded.
- **Recommendation:** Either (a) provide an alternative tool invocation path for non-FC providers (the original dual-path was there for a reason), or (b) ensure only FC-capable providers are used when tools are needed, or (c) conditionally include `<command>` instructions only when the selected provider lacks native FC. Option (c) is the architecturally correct choice.

### R4 — Legacy persistence normalization path not removed

- **Severity:** MINOR
- **Observation:** `format_ai_history_rows()` in `queries.py` still has the `elif role in ALL_TOOL_ROLES:` branch that normalizes legacy tool-result messages via `extract_raw_result_from_markdown_contract()`. The `ALL_TOOL_ROLES` dict and `extract_raw_result_from_markdown_contract` function are exported from the DB package.
- **Affected work packages:** FC4 (marked complete but legacy remains), FC7
- **Affected components:** `app/db/queries.py`, `app/db/__init__.py`
- **Description:** This is explicitly marked "FC7 will remove it" in comments. FC7 is marked complete but did not remove it. This is a justified retention — old DB rows with legacy tool roles need normalization for AI context reconstruction. Removing it would break history replay for pre-migration sessions.
- **Recommendation:** Keep but mark with a TODO tracking the data migration horizon (when all legacy sessions have expired or been migrated). Not a current regression.

### R5 — `execute_commands` retained in `commands.py` but not called from runtime

- **Severity:** MINOR
- **Observation:** `execute_commands()` exists in `commands.py` at line 342 but is not imported by any runtime module. It is only imported by `tests/test_commands.py`.
- **Affected work packages:** FC7
- **Affected components:** `app/commands.py`
- **Description:** This is dead production code. It exists solely for backward compat test coverage. Not harmful, but it inflates the maintenance surface.
- **Recommendation:** Acceptable for now. Consider quarantining in a `legacy/` subdirectory or deleting if all command-protocol tests are rewritten for native FC.

### R6 — `StreamToolEvent` is defined but never instantiated or yielded

- **Severity:** MAJOR
- **Observation:** `StreamToolEvent` is imported by `stream_manager.py` and `chat_service.py` which handle it, but no code ever creates one. It serves as a consumption schema without a producer.
- **Affected work packages:** FC5 (structure only, no production flow)
- **Affected components:** `app/tools/schemas.py`, `app/orchestrator.py`, `app/stream_manager.py`, `app/services/chat_service.py`
- **Description:** This is a direct consequence of R1. The schema and consumers exist but the producer is absent. This means the FC5 SSE typed event format for `tool_call` and `tool_result` events is untested in production.
- **Recommendation:** Will be resolved when R1 is fixed. No separate action needed.

### R7 — Test suite has no coverage for the new architecture

- **Severity:** MAJOR
- **Observation:** No tests exist for: `ToolCallEvent`/`ToolResultEvent` lifecycle, `ProviderCapabilities` negotiation, streaming tool-call events, `StreamToolEvent` wire format, `turn_id` correlation, `execute_tool_event()` through the full path, `format_ai_history_rows` with `turn_id`, structured SSE envelope, or frontend tool event rendering.
- **Affected work packages:** All FC packages
- **Affected components:** `tests/`
- **Description:** The test suite validates legacy `<command>` parsing (18 tests pass) but has zero coverage for the new native FC architecture. The migration changed 7+ production modules without adding any new tests. FC7's completion criteria states "tests validate native tool calling" — this was not met.
- **Recommendation:** Critical testing gap. New tests needed for: (1) `execute_tool_event()` → `ToolResultEvent` round-trip, (2) `_parse_raw_tool_calls_async()` with mock provider responses, (3) `ProviderCapabilities` routing, (4) `format_ai_history_rows` with `tool_calls` JSONB + `turn_id`, (5) SSE envelope shape, (6) `StreamToolEvent.to_sse()` serialization.

### R8 — Streaming and non-streaming execution models diverge

- **Severity:** CRITICAL (corollary of R1)
- **Observation:** Non-streaming: `generate_ai_response()` → `send_message_raw()` → parses `tool_calls` from `raw_response` → executes. Streaming: `generate_ai_response_streaming()` → `send_message_streaming()` → **text only, no tool_calls** → synthesis loop strips `<command>` blocks. Tool execution never happens during streaming.
- **Affected work packages:** FC3 (criteria not met), FC5
- **Affected components:** `app/llm_client.py`, `app/orchestrator.py`, `app/providers/openrouter.py`
- **Description:** FC3's completion criteria: "One orchestrator path handles tool calls for both streaming and non-streaming turns." This is not met. The streaming path cannot execute tools because the provider layer does not surface `tool_calls` from streaming responses. The only tool execution in the streaming path is the unreachable `__TOOL_CALLS__:` branch (R2).
- **Recommendation:** Same as R1 — implement streaming tool-call parsing in the provider layer. This is the single highest-priority follow-up.

### R9 — `commands.py` still imported by orchestrator for parsing utilities

- **Severity:** MINOR
- **Observation:** `orchestrator.py` imports `has_tool_blocks`, `parse_tool_blocks`, `TOL_ALIASES`, `IMAGE_SHORTCUT_WARNING`, `is_markdown_image_shortcut`, `parse_image_path` from `commands.py`. These are text-manipulation utilities, not execution. `has_tool_blocks` and `parse_tool_blocks` are used for the FC7 strip-and-warn logic.
- **Affected work packages:** FC7
- **Affected components:** `app/orchestrator.py`, `app/commands.py`
- **Description:** Justified retention — the strip-and-warn logic needs `parse_tool_blocks` to extract clean text from synthesis. The other imports (`TOL_ALIASES`, `parse_image_path`) are shared utilities.
- **Recommendation:** Consider moving the shared utilities to a separate module (e.g., `app/tools/parsing.py`) to reduce the conceptual coupling between orchestrator and the legacy command module. Low priority.

### R10 — OpenRouter streaming does not parse tool_calls from SSE deltas

- **Severity:** CRITICAL (root cause of R1, R8)
- **Observation:** `OpenRouterProvider.send_message_streaming()` yields raw text chunks only. When OpenAI-compatible streaming returns `tool_calls` in delta chunks (e.g., `{"delta": {"tool_calls": [{"function": {"name": "bash", "arguments": "..."}}]}}`), the provider adapter does not detect or surface them.
- **Affected work packages:** FC2 (streaming capability claimed but not functional), FC5
- **Affected components:** `app/providers/openrouter.py`
- **Description:** `ProviderCapabilities` declares `supports_streaming_fc=True` for OpenRouter, but the streaming implementation does not actually support it. This is a false declaration.
- **Recommendation:** Either (a) implement streaming tool-call parsing in `OpenRouterProvider._send_message_streaming_impl()`, or (b) set `supports_streaming_fc=False` until implemented. Option (b) is the honest short-term fix; option (a) is the real solution.

---

## Work Package Verification

| FC | Implementation Exists | Criteria Met | Follow-up Needed |
|----|----------------------|-------------|-----------------|
| FC1 | ✅ Yes — schemas, registry, capabilities all present | ✅ Yes | None |
| FC2 | ✅ Yes — `ProviderCapabilities`, `parse_tool_calls()` | ⚠️ Partial — `supports_streaming_fc=True` for OpenRouter is false (R10) | Fix capability declaration or implement |
| FC3 | ✅ Yes — `_execute_tool_calls_async()` uses `execute_tool_event()` | ❌ No — streaming path cannot execute tools (R8) | R1 |
| FC4 | ✅ Yes — `turn_id` column, all SELECTs, `format_ai_history_rows` updated | ✅ Yes | Remove legacy normalization when data migrated (R4) |
| FC5 | ⚠️ Structure only — schema + consumers exist, no producer | ❌ No — no tool-call events are emitted in production (R1) | R1 |
| FC6 | ⚠️ Frontend rendering code exists but never exercised | ❌ No — rendering code is unreachable without FC5 producing events | R1 |
| FC7 | ⚠️ Partial — orchestrator strips `<command>`, but prompt still teaches it | ❌ No — non-FC providers silently lose tool ability (R3) | Conditional prompt or alternative path |
| FC8 | ✅ Yes — `turn_id` in logs, API, frontend console | ✅ Yes (for the paths that work) | None |

---

## Test Audit

| Gap | Description |
|-----|-------------|
| No `ToolCallEvent`/`ToolResultEvent` lifecycle test | `make_tool_call_event()` → `execute_tool_event()` → result shape verification |
| No `ProviderCapabilities` test | Verify routing decisions based on capability flags |
| No streaming tool-call test | Verify `StreamToolEvent` production and wire format |
| No `turn_id` correlation test | Verify `turn_id` flows through persist → select → `format_ai_history_rows` |
| No SSE envelope test | Verify `{"type": "token", ...}` and `{"type": "tool_call", ...}` shapes |
| No `execute_tool_event()` integration test | End-to-end through registry dispatch |
| No provider `parse_tool_calls()` test | Mock raw OpenRouter response, verify canonical output |
| No frontend integration test | Tool event rendering in browser (understandable gap — hard to test) |
| Legacy tests outdated | `TestExecuteCommands` validates dead code path |

---

## Final Verdict

### PASS WITH MAJOR FOLLOW-UP REQUIRED

The non-streaming path is architecturally sound — native FC works end-to-end from provider parsing through execution, persistence, and history reconstruction. The canonical event schema, registry contract, provider capability matrix, turn_id correlation, and legacy strip-and-warn logic are all correct.

However, there are two critical gaps that materially break the architectural goals:

1. **Streaming tool-call production is missing** (R1/R8/R10). The entire FC5→FC6 chain is theoretical — `StreamToolEvent` is defined but never created, the `__TOOL_CALLS__:` marker is dead code, the streaming path cannot execute tools, and the frontend tool event rendering is unreachable. This means the streaming path (which is the primary user-facing path via web) silently regresses tool execution for all providers.

2. **Non-FC providers silently lose tool ability** (R3). The system prompt teaches `<command>` syntax, but the orchestrator strips `<command>` blocks without execution. Ollama and similar providers cannot use native FC, so tools are silently broken when using these providers.

---

## Remaining Technical Debt

| Item | Priority | Description |
|------|----------|-------------|
| Streaming tool-call parsing | P0 | Implement in OpenRouter provider; remove `__TOOL_CALLS__:` dead code |
| Conditional system prompt | P1 | Only include `<command>` docs when provider lacks native FC |
| `supports_streaming_fc` accuracy | P1 | Set False for OpenRouter until streaming FC actually works |
| Test coverage for new architecture | P1 | At minimum: `execute_tool_event` round-trip, `parse_tool_calls`, `format_ai_history_rows` with turn_id |
| `execute_commands` dead code | P2 | Quarantine or remove from production code |
| Shared utilities in `commands.py` | P3 | Move `parse_image_path`, `TOL_ALIASES` etc. to dedicated module |

---

## Migration Completeness Assessment

**Can the migration plan be considered complete?** No. FC3, FC5, FC6, and FC7 did not meet their stated completion criteria. The marking of these work packages as COMPLETE in the plan document is inaccurate.

**Has the legacy `<command>` architecture been fully retired?** Partially. The execution path is retired (stripped + warned), but the protocol is still taught to models via the system prompt, still validated in tests, and still used as the only tool invocation mechanism for non-FC providers.
