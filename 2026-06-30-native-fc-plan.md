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
| Finding ID | FC1 |
| Title | Establish a single canonical tool-event schema and registry contract |
| Objective | Turn the existing `ToolDefinition` shape into the authoritative contract for native tool calling, tool capability metadata, and event serialization |
| Affected components | `file app/tools/schemas.py`, `file app/tools/registry.py`, `file app/tools/__init__.py`, `file app/llm_client.py` |
| Dependencies | None |
| Implementation scope | Define the canonical tool-event envelope, ensure registry output is the one source of truth for LLM tool schemas, and expose capability metadata needed by providers and orchestration |
| Completion criteria | Tool schemas are produced from one canonical source; no layer needs to infer tool shape from legacy command markup; registry exports a stable tool-event description usable by both request types |
| Estimated migration risk | Medium |

### FC2 — Provider capability matrix and raw response normalization

| Field | Value |
| --- | --- |
| Finding ID | FC2 |
| Title | Normalize provider capabilities and raw response parsing around native tool calls |
| Objective | Make each provider declare whether it supports native tool calls, streaming tool events, and raw `tool_calls` parsing so the client/orchestrator can route consistently |
| Affected components | `file app/providers/base.py`, `file app/providers/openrouter.py`, `file app/providers/chutes.py`, `file app/providers/ollama.py`, `file app/providers/cerebras.py`, `file app/providers/__init__.py`, `file app/llm_client.py` |
| Dependencies | FC1 |
| Implementation scope | Add provider capability metadata, normalize raw tool-call parsing into a canonical shape, and make unsupported capabilities explicit instead of silently collapsing them into text-only behavior |
| Completion criteria | Provider adapters advertise consistent tool-call capabilities; non-streaming tool calls can be parsed through one provider-facing abstraction; the client can decide whether to request tools without hardcoding provider quirks |
| Estimated migration risk | High |

**Phase dependency note:** FC2 should land after FC1 so the provider layer can consume a stable canonical tool schema instead of a moving shape.

---

## Phase 2 — Orchestration unification

Focus: remove the dual grammar from the execution path and make tool dispatch event-driven.

### FC3 — Unify orchestration around structured tool events

| Field | Value |
| --- | --- |
| Finding ID | FC3 |
| Title | Collapse the orchestrator into one structured tool-event execution path |
| Objective | Replace the split native-vs-`<command>` orchestration branches with one executor that consumes structured tool events regardless of source |
| Affected components | `file app/orchestrator.py`, `file app/commands.py`, `file app/services/chat_service.py`, `file app/llm_client.py` |
| Dependencies | FC1, FC2 |
| Implementation scope | Move tool-call parsing to the provider/client boundary, centralize execution in the orchestrator, preserve continuation-loop semantics, and keep temporary compatibility handling only where the runtime still needs it |
| Completion criteria | One orchestrator path handles tool calls for both streaming and non-streaming turns; legacy text parsing is no longer the primary execution branch; tool execution, continuation, and persistence all consume the same structured event model |
| Estimated migration risk | Very high |

### FC4 — Persist tool events as canonical conversation state

| Field | Value |
| --- | --- |
| Finding ID | FC4 |
| Title | Make structured tool events the canonical persistence model |
| Objective | Ensure persistence, replay, and context reconstruction operate on structured tool-call records rather than markdown contracts or command text |
| Affected components | `file app/db/queries.py`, `file app/db/facade.py`, `file app/db/models_async.py`, `file app/orchestrator.py`, `file app/tools/schemas.py` |
| Dependencies | FC3 |
| Implementation scope | Use `tool_calls` and `tool_call_id` as the authoritative persisted shape, keep markdown strictly as presentation output, and update history reconstruction to prefer structured records over legacy contract parsing |
| Completion criteria | Tool-call history can be reconstructed without parsing `<command>` blocks; assistant/tool persistence preserves a complete tool lifecycle; replay from DB matches the structured event stream |
| Estimated migration risk | High |

**Phase dependency note:** FC4 should follow FC3 so the persistence model can be aligned to the new orchestration event flow rather than the reverse.

---

## Phase 3 — Streaming, API, and frontend event migration

Focus: expose the structured tool lifecycle across SSE and the browser instead of reconstructing behavior from text.

### FC5 — Stream structured events through SSE and API boundaries

| Field | Value |
| --- | --- |
| Finding ID | FC5 |
| Title | Move SSE and REST chat responses to a structured event envelope |
| Objective | Emit tokens, tool-call events, tool-result events, and completion events explicitly from the API layer so the browser no longer has to infer structure from raw text |
| Affected components | `file app/api/endpoints/chat.py`, `file app/api/endpoints/stream.py`, `file app/stream_manager.py`, `file app/services/chat_service.py`, `file app/orchestrator.py` |
| Dependencies | FC3, FC4 |
| Implementation scope | Define the API event schema, preserve stream reattachment behavior, keep session recovery runnable, and phase the transport from plain chunk text to typed events without breaking the live chat endpoint |
| Completion criteria | The API can carry structured tool-call lifecycle events end-to-end; stream reattachment still works; current chat functionality remains runnable during the transition |
| Estimated migration risk | Very high |

### FC6 — Replace command-aware frontend rendering with event-aware rendering

| Field | Value |
| --- | --- |
| Finding ID | FC6 |
| Title | Render native tool events directly in the browser |
| Objective | Remove the browser’s dependence on `<command>` parsing and make the UI render tool calls, tool results, and completion state from explicit event data |
| Affected components | `file static/js/modules/multimodal.js`, `file static/js/modules/stream-manager.js`, `file static/js/modules/history.js`, `file static/js/renderer.js`, `file static/js/chat.js`, `file static/js/modules/state.js` |
| Dependencies | FC5 |
| Implementation scope | Update stream buffering and rendering to consume the new event envelope, preserve incremental markdown rendering where needed, and remove command-block-specific recovery paths only after event rendering is stable |
| Completion criteria | The browser no longer needs to detect or re-render `<command>` blocks to understand tool execution; streamed tool lifecycles render cleanly; history rebinding uses structured state |
| Estimated migration risk | Very high |

**Phase dependency note:** FC6 must follow FC5 so the browser can render the same structured event stream that the API is emitting.

---

## Phase 4 — Legacy protocol removal and operating model cleanup

Focus: delete the compatibility surface only after the new architecture is fully runnable.

### FC7 — Remove legacy `<command>` protocol and update tests/docs

| Field | Value |
| --- | --- |
| Finding ID | FC7 |
| Title | Retire the legacy textual command protocol and align tests/documentation |
| Objective | Remove `<command>` from the canonical runtime path, then update tests and docs so the repository only teaches and verifies native function calling |
| Affected components | `file app/commands.py`, `file app/prompts.py`, `file tests/test_commands.py`, `file tests/*`, `file README.md`, `file app/README.md`, `file app/api/README.md`, `file AGENTS.md`, `file CHANGELOG.md`, `file CONTRIBUTING.md`, `file INSTALL.md` |
| Dependencies | FC1 through FC6 |
| Implementation scope | Delete or quarantine legacy parser behavior, replace protocol-centric tests with native tool-call coverage, and rewrite documentation to reflect the final architecture |
| Completion criteria | The repository no longer treats `<command>` as a production protocol; tests validate native tool calling; docs and operational guidance match the new contract |
| Estimated migration risk | High |

### FC8 — Correlation, telemetry, and migration hardening

| Field | Value |
| --- | --- |
| Finding ID | FC8 |
| Title | Add lifecycle correlation and migration hardening across the new event model |
| Objective | Make the tool-call lifecycle easy to trace and diagnose once the structured event contract is live |
| Affected components | `file app/logging_config.py`, `file app/orchestrator.py`, `file app/providers/*.py`, `file app/stream_manager.py`, `file app/api/endpoints/chat.py`, `file static/js/modules/multimodal.js`, `file tests/*` |
| Dependencies | FC3, FC4, FC5, FC6 |
| Implementation scope | Introduce correlation identifiers or equivalent trace tokens through provider parsing, orchestration, persistence, stream emission, and browser replay; add targeted migration checks where they reduce ambiguity |
| Completion criteria | A single tool-call lifecycle can be traced across provider, orchestrator, DB, SSE, and UI logs; migration failures are diagnosable without reintroducing legacy protocol assumptions |
| Estimated migration risk | Medium |

**Phase dependency note:** FC8 is intentionally last so it can observe the final event model rather than a transitional one.

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

---

## Rollout Notes

- Every phase should leave the repository runnable.
- If a phase requires temporary compatibility handling, it must be explicitly confined to that phase and removed in a later phase.
- Do not widen scope to unrelated service or memory rewrites.
- Do not rename the migration objective: this is a Native Function Calling migration, not a general refactor.

---

## Maintenance Rule

When implementation updates this plan, only change the status fields, commit hashes, notes, and completion dates. Do not rewrite the phase logic unless the audit itself changes.