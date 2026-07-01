# Native Function Calling Migration Master Plan — Yuzu Companion

> **Based on:** `file 2026-06-30-native-fc-audit.md`
****Purpose:** canonical implementation roadmap for the Native Function Calling migration
****Authority:** this plan is the only document implementation agents should update
****Audit report:** immutable
****Plan status:** living document
****Allowed updates by implementation agents:** Status, Commit hash, Notes, Completion date

---

## Planning rules

1. **Stabilize the canonical contract before removing the legacy one.**
2. **Keep every step runnable.** Avoid package-wide rewrites that leave the runtime half-converted.
3. **Prefer event-envelope migrations over parser rewrites.**
4. **Do not duplicate canonical logic across layers.** If a work package needs a bridge, it must be temporary and explicitly retired in a later package.
5. **Keep streaming and non-streaming aligned.** A change that only fixes one path is not enough unless it is explicitly transitional.
6. **Defer documentation cleanup until the runtime contract is stable.**

---

## Phase 1 — Canonical tool contract and capability metadata

Focus: make native function calling the explicit contract that every downstream layer can rely on.

### FC1 — Canonical tool-event schema and registry contract

| Field | Value |
| --- | --- |
|| Finding ID | FC1 |
|| Title | Establish a single canonical tool-event schema and registry contract |
|| Status | **COMPLETE** |
|| Commit | 19ff254 |
|| Completion date | 2026-06-30 |
|| Objective | Turn the existing `ToolDefinition` shape into the authoritative contract for native tool calling, tool capability metadata, and event serialization |
|| Affected components | `file app/tools/schemas.py`, `file app/tools/registry.py`, `file app/tools/__init__.py`, `file app/llm_client.py` |
|| Dependencies | None |
|| Implementation scope | Define the canonical tool-event envelope, ensure registry output is the one source of truth for LLM tool schemas, and expose capability metadata needed by providers and orchestration |
|| Completion criteria | Tool schemas are produced from one canonical source; no layer needs to infer tool shape from legacy command markup; registry exports a stable tool-event description usable by both request types |
|| Estimated migration risk | Medium |
|| Notes | Added `ToolCallEvent`, `ToolResultEvent`, `StreamToolEvent` dataclasses. Added `supports_native_fc`/`supports_streaming_fc` to `ToolDefinition`. Registry now exposes `get_tool_schemas()`, `get_tool_capabilities()`, `get_all_capabilities()`, `execute_tool_event()`. `llm_client._unique_tool_schemas()` delegates to canonical `get_tool_schemas()`. Legacy markdown helpers retained for FC7 removal. |

### FC2 — Provider capability matrix and raw response normalization

| Field | Value |
| --- | --- |
|| Finding ID | FC2 |
|| Title | Normalize provider capabilities and raw response parsing around native tool calls |
|| Status | **COMPLETE** |
|| Commit | 97b6a80 |
|| Completion date | 2026-06-30 |
|| Objective | Make each provider declare whether it supports native tool calls, streaming tool events, and raw `tool_calls` parsing so the client/orchestrator can route consistently |
|| Affected components | `file app/providers/base.py`, `file app/providers/openrouter.py`, `file app/providers/chutes.py`, `file app/providers/ollama.py`, `file app/providers/cerebras.py`, `file app/providers/__init__.py`, `file app/llm_client.py` |
|| Dependencies | FC1 |
|| Implementation scope | Add provider capability metadata, normalize raw tool-call parsing into a canonical shape, and make unsupported capabilities explicit instead of silently collapsing them into text-only behavior |
|| Completion criteria | Provider adapters advertise consistent tool-call capabilities; non-streaming tool calls can be parsed through one provider-facing abstraction; the client can decide whether to request tools without hardcoding provider quirks |
|| Estimated migration risk | High |
|| Notes | Added `ProviderCapabilities` dataclass. Each provider declares capabilities in __init__. AIProviderManager exposes `provider_supports_tools()`, `provider_supports_streaming_tools()`, `get_provider_capabilities()`, `get_all_provider_capabilities()`, `parse_tool_calls()`. OpenRouter supports native FC + parsing. Chutes/Ollama/Cerebras explicitly report no FC support. |

**Phase dependency note:** FC2 should land after FC1 so the provider layer can consume a stable canonical tool schema instead of a moving shape.

---

## Phase 2 — Orchestration unification

Focus: remove the dual grammar from the execution path and make tool dispatch event-driven.

### FC3 — Unify orchestration around structured tool events

| Field | Value |
| --- | --- |
|| Finding ID | FC3 |
|| Title | Collapse the orchestrator into one structured tool-event execution path |
|| Status | **COMPLETE** |
|| Commit | 3b879e3 |
|| Completion date | 2026-06-30 |
|| Objective | Replace the split native-vs-`<command>` orchestration branches with one executor that consumes structured tool events regardless of source |
|| Affected components | `file app/orchestrator.py`, `file app/commands.py`, `file app/services/chat_service.py`, `file app/llm_client.py` |
|| Dependencies | FC1, FC2 |
|| Implementation scope | Move tool-call parsing to the provider/client boundary, centralize execution in the orchestrator, preserve continuation-loop semantics, and keep temporary compatibility handling only where the runtime still needs it |
|| Completion criteria | One orchestrator path handles tool calls for both streaming and non-streaming turns; legacy text parsing is no longer the primary execution branch; tool execution, continuation, and persistence all consume the same structured event model |
|| Estimated migration risk | Very high |
|| Notes | `_parse_raw_tool_calls_async` uses AIProviderManager.parse_tool_calls() (FC2). `_execute_tool_calls_async` uses execute_tool_event() (FC1). Both accept turn_id. `handle_user_message` and `handle_user_message_streaming` generate turn_id via new_turn_id(). Legacy `<command>` parsing retained only in streaming synthesis loop fallback (FC7 removes it). |

### FC4 — Persist tool events as canonical conversation state

| Field | Value |
| --- | --- |
|| Finding ID | FC4 |
|| Title | Make structured tool events the canonical persistence model |
|| Status | **COMPLETE** |
|| Commit | 98e9b7c |
|| Completion date | 2026-06-30 |
|| Objective | Ensure persistence, replay, and context reconstruction operate on structured tool-call records rather than markdown contracts or command text |
|| Affected components | `file app/db/queries.py`, `file app/db/facade.py`, `file app/db/models_async.py`, `file app/orchestrator.py`, `file app/tools/schemas.py` |
|| Dependencies | FC3 |
|| Implementation scope | Use `tool_calls` and `tool_call_id` as the authoritative persisted shape, keep markdown strictly as presentation output, and update history reconstruction to prefer structured records over legacy contract parsing |
|| Completion criteria | Tool-call history can be reconstructed without parsing `<command>` blocks; assistant/tool persistence preserves a complete tool lifecycle; replay from DB matches the structured event stream |
|| Notes | Added turn_id VARCHAR column to messages. All SELECT queries return turn_id. parse_message_row includes turn_id. Database.add_message accepts turn_id. All _persist_* helpers forward it. format_ai_history_rows includes turn_id in native FC entries. Legacy path marked for FC7. |
| Estimated migration risk | High |

**Phase dependency note:** FC4 should follow FC3 so the persistence model can be aligned to the new orchestration event flow rather than the reverse.

---

## Phase 3 — Streaming, API, and frontend event migration

Focus: expose the structured tool lifecycle across SSE and the browser instead of reconstructing behavior from text.

### FC5 — Stream structured events through SSE and API boundaries

| Field | Value |
| --- | --- |
|| Finding ID | FC5 |
|| Title | Move SSE and REST chat responses to a structured event envelope |
|| Status | **COMPLETE** |
|| Commit | 40858d0 |
|| Completion date | 2026-06-30 |
|| Objective | Emit tokens, tool-call events, tool-result events, and completion events explicitly from the API layer so the browser no longer has to infer structure from raw text |
|| Affected components | `file app/api/endpoints/chat.py`, `file app/api/endpoints/stream.py`, `file app/stream_manager.py`, `file app/services/chat_service.py`, `file app/orchestrator.py` |
|| Dependencies | FC3, FC4 |
|| Implementation scope | Define the API event schema, preserve stream reattachment behavior, keep session recovery runnable, and phase the transport from plain chunk text to typed events without breaking the live chat endpoint |
|| Completion criteria | The API can carry structured tool-call lifecycle events end-to-end; stream reattachment still works; current chat functionality remains runnable during the transition |
|| Notes | SSE format: type=token (chunk+turn_id), type=tool_call/result (data), type=done (turn_id). StreamBuffer handles StreamToolEvent + plain str. Frontend handles all types, logs tool events for FC6. Stream reattach preserved. |

### FC6 — Replace command-aware frontend rendering with event-aware rendering

| Field | Value |
| --- | --- |
|| Finding ID | FC6 |
|| Title | Render native tool events directly in the browser |
|| Status | **COMPLETE** |
|| Commit | cbe9628 |
|| Completion date | 2026-06-30 |
|| Objective | Remove the browser's dependence on `<command>` parsing and make the UI render tool calls, tool results, and completion state from explicit event data |
|| Affected components | `file static/js/modules/multimodal.js`, `file static/js/modules/stream-manager.js`, `file static/js/modules/history.js`, `file static/js/renderer.js`, `file static/js/chat.js`, `file static/js/modules/state.js` |
|| Dependencies | FC5 |
|| Implementation scope | Update stream buffering and rendering to consume the new event envelope, preserve incremental markdown rendering where needed, and remove command-block-specific recovery paths only after event rendering is stable |
|| Completion criteria | The browser no longer needs to detect or re-render `<command>` blocks to understand tool execution; streamed tool lifecycles render cleanly; history rebinding uses structured state |
|| Notes | tool_call renders collapsible 'Calling X...' indicator. tool_result renders collapsible result with status icon + markdown. CSS added for .tool-call-indicator, .tool-result, .tool-result-content. Legacy <command> blocks still handled for pre-existing data (FC7 removes). |

**Phase dependency note:** FC6 must follow FC5 so the browser can render the same structured event stream that the API is emitting.

---

## Phase 4 — Legacy protocol removal and operating model cleanup

Focus: delete the compatibility surface only after the new architecture is fully runnable.

### FC7 — Remove legacy `<command>` protocol and update tests/docs

| Field | Value |
| --- | --- |
|| Finding ID | FC7 |
|| Title | Retire the legacy textual command protocol and align tests/documentation |
|| Status | **COMPLETE** |
|| Commit | 38f9d0e |
|| Completion date | 2026-06-30 |
|| Objective | Remove `<command>` from the canonical runtime path, then update tests and docs so the repository only teaches and verifies native function calling |
|| Affected components | `file app/commands.py`, `file app/prompts.py`, `file tests/test_commands.py`, `file tests/*`, `file README.md`, `file app/README.md`, `file app/api/README.md`, `file AGENTS.md`, `file CHANGELOG.md`, `file CONTRIBUTING.md`, `file INSTALL.md` |
|| Dependencies | FC1 through FC6 |
|| Implementation scope | Delete or quarantine legacy parser behavior, replace protocol-centric tests with native tool-call coverage, and rewrite documentation to reflect the final architecture |
|| Completion criteria | The repository no longer treats `<command>` as a production protocol; tests validate native tool calling; docs and operational guidance match the new contract |
|| Notes | <command> blocks stripped from synthesis without execution. execute_commands removed from orchestrator imports. Parsing utilities retained for text cleanup. System prompt marks native FC preferred, <command> as deprecated fallback. 60 lines of dead loop code removed. All 18 tests pass. |

### FC8 — Correlation, telemetry, and migration hardening

| Field | Value |
| --- | --- |
|| Finding ID | FC8 |
|| Title | Add lifecycle correlation and migration hardening across the new event model |
|| Status | **COMPLETE** |
|| Commit | 475a96a |
|| Completion date | 2026-06-30 |
|| Objective | Make the tool-call lifecycle easy to trace and diagnose once the structured event contract is live |
|| Affected components | `file app/logging_config.py`, `file app/orchestrator.py`, `file app/providers/*.py`, `file app/stream_manager.py`, `file app/api/endpoints/chat.py`, `file static/js/modules/multimodal.js`, `file tests/*` |
|| Dependencies | FC3, FC4, FC5, FC6 |
|| Implementation scope | Introduce correlation identifiers or equivalent trace tokens through provider parsing, orchestration, persistence, stream emission, and browser replay; add targeted migration checks where they reduce ambiguity |
|| Completion criteria | A single tool-call lifecycle can be traced across provider, orchestrator, DB, SSE, and UI logs; migration failures are diagnosable without reintroducing legacy protocol assumptions |
|| Notes | turn_id flows through all log points (orchestrator, stream, API). Stream status/sync endpoints expose turn_id. Frontend console logs include call_id + turn_id. Full lifecycle tracing: provider → orchestrator → DB → SSE → browser. |

**Phase dependency note:** FC8 is intentionally last so it can observe the final event model rather than a transitional one.

---

## Post-Implementation Findings

> **Source:** `file 2026-06-30-native-fc-review.md` (independent architecture review)
> **Date:** 2026-06-30
> **Verdict:** PASS WITH MAJOR FOLLOW-UP REQUIRED

The review identified 10 findings (R1–R10). Critical and major findings are addressed by FC9 below. Minor findings (R4, R5, R9) are accepted as justified retention.

### Findings Addressed by FC9

| Review ID | Severity | Description | FC9 Sub-task |
|-----------|----------|-------------|--------------|
| R1 | CRITICAL | Streaming tool-call production path missing — no code emits `StreamToolEvent` | FC9-A |
| R2 | MAJOR | `__TOOL_CALLS__:` marker is dead code (consumed but never produced) | FC9-B |
| R3 | MAJOR | System prompt teaches `<command>` to all providers; non-FC providers silently lose tool ability | FC9-C |
| R6 | MAJOR | `StreamToolEvent` defined but never instantiated (consequence of R1) | FC9-A |
| R8 | CRITICAL | Streaming and non-streaming execution models diverge (consequence of R1) | FC9-A |
| R10 | CRITICAL | `supports_streaming_fc=True` was false declaration for OpenRouter | FC9-D |

### Findings Accepted (Justified Retention)

| Review ID | Severity | Description | Rationale |
|-----------|----------|-------------|-----------|
| R4 | MINOR | Legacy `ALL_TOOL_ROLES` normalization retained in `format_ai_history_rows` | Pre-migration DB rows need normalization for AI context replay |
| R5 | MINOR | `execute_commands` retained in `commands.py` | Backward compat test coverage; quarantined from runtime |
| R9 | MINOR | `commands.py` parsing utilities imported by orchestrator | Strip-and-warn logic needs `parse_tool_blocks`; shared utilities |

### Findings Deferred (Require Separate Work)

| Review ID | Severity | Description | Recommendation |
|-----------|----------|-------------|----------------|
| R7 | MAJOR | Zero test coverage for new architecture | Deferred to FC10 (test coverage work package) |

---

## Phase 5 — Post-implementation remediation

Focus: close the critical gaps identified by the independent architecture review.

### FC9 — Streaming tool-call production and prompt-conditioning

| Field | Value |
| --- | --- |
|| Finding ID | FC9 |
|| Title | Fix streaming tool-call production, remove dead code, condition system prompt |
|| Status | **COMPLETE** |
|| Commit | 89a7bda |
|| Completion date | 2026-06-30 |
|| Objective | Close the critical gaps (R1, R2, R3, R6, R8, R10) identified in the post-implementation review |
|| Affected components | `file app/providers/openrouter.py`, `file app/providers/base.py`, `file app/llm_client.py`, `file app/orchestrator.py`, `file app/prompts.py` |
|| Dependencies | FC1 through FC8 |
|| Implementation scope | Parse tool_calls from OpenRouter SSE delta chunks, emit StreamToolEvent through the streaming pipeline, remove __TOOL_CALLS__ dead code, condition <command> syntax docs on provider FC capability |
|| Completion criteria | Streaming path can execute tool calls end-to-end; no dead code remains in streaming path; non-FC providers get <command> docs, FC providers get native FC preference |
|| Notes | FC9-A: OpenRouter streaming parses tool_call deltas, accumulates fragments, yields StreamToolEvent(type="tool_call"). FC9-B: Removed __TOOL_CALLS__ marker detection. FC9-C: build_system_message_async accepts provider_supports_fc; <command> docs only for non-FC. FC9-D: supports_streaming_fc=True for OpenRouter (now accurate). |

---

## Execution Order Summary

| Order | Work package | Why it lands there |
| --- | --- | --- |
| 1 | FC1 | Establish the canonical contract first |
| 2 | FC2 | Teach providers the canonical contract |
| 3 | FC3 | Unify orchestration on structured events |
| 4 | FC4 | Persist structured events as the source of truth |
| 5 | FC5 | Expose the structured event stream over API/SSE |
| 6 | FC6 | Render the structured event stream in the browser |
| 7 | FC7 | Remove legacy protocol and align docs/tests |
| 8 | FC8 | Harden observability and traceability after the model is stable |
| 9 | FC9 | Close critical gaps found by independent review |

---

## Phase 6 — Test coverage and regression hardening

Focus: establish regression coverage to protect the new architecture from future changes.

### FC10 — Native Function Calling Test Coverage

| Field | Value |
| --- | --- |
|| Finding ID | FC10 |
|| Title | Establish regression coverage for the new Native Function Calling architecture |
|| Status | **COMPLETE** |
|| Commit | deae19a |
|| Completion date | 2026-06-30 |
|| Objective | Protect the architecture from future regressions, not merely increase test count |
|| Affected components | `tests/test_fc_registry.py`, `tests/test_fc_provider.py`, `tests/test_fc_orchestrator.py`, `tests/test_fc_streaming.py`, `tests/test_commands.py`, `tests/test_db_queries.py` |
|| Dependencies | FC1 through FC9 |
|| Implementation scope | Audit existing tests, write regression tests for all FC layers, verify legacy isolation |
|| Completion criteria | 122+ new tests covering registry, provider, orchestrator, streaming, persistence; legacy execution path verified as isolated |
|| Notes | Phase A: Audit (tests/FC10_AUDIT.md). Phase B: 5 new test files. Phase C: Legacy regression (AST-level check). Phase D: 137 tests pass. |

---

## Rollout Notes

- Every phase should leave the repository runnable.
- If a phase requires temporary compatibility handling, it must be explicitly confined to that phase and removed in a later phase.
- Do not widen scope to unrelated service or memory rewrites.
- Do not rename the migration objective: this is a Native Function Calling migration, not a general refactor.

---

## Maintenance Rule

When implementation updates this plan, only change the status fields, commit hashes, notes, and completion dates. Do not rewrite the phase logic unless the audit itself changes.