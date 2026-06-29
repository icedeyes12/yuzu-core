# Native Function Calling Audit — Yuzu Companion

> **Updated:** 2026-06-30
> **Scope:** Full tool execution architecture for the Native Function Calling migration
> **Goal:** Replace the legacy `<command>...</command>` protocol with a single native function-calling architecture across prompt construction, provider I/O, orchestration, persistence, streaming, and UI rendering
> **Status:** Architecture audit only. No implementation.

---

## Executive Summary

The repository already contains the beginnings of native function calling, but it is not yet the authoritative architecture.

What already exists and can be reused:

- `ToolDefinition.to_llm_schema()` already emits OpenAI-style function schemas.
- `app/tools/registry.py` already acts as the central tool registry and dispatch point.
- `app/orchestrator.py` already has a native `tool_calls` execution branch.
- `app/db/queries.py` and `app/db/facade.py` already persist `tool_calls` and `tool_call_id`.
- `app/providers/openrouter.py` already parses native `tool_calls` from provider responses.
- `app/providers/base.py` already exposes a provider abstraction that can carry tool schemas.

What is still split:

- The system prompt still teaches `<command>` as the primary tool protocol.
- The streaming path still parses and executes textual command blocks.
- The frontend still renders command blocks and command-block-style tool output.
- Several persistence helpers still normalize legacy text contracts instead of treating structured tool calls as the primary event stream.
- Tests and documentation still validate the legacy protocol as if it were canonical.

The migration is therefore not just a parser swap. It is a full architecture move from **textual tool markup** to **structured tool-call events**.

The highest-risk boundary is streaming, because it currently serializes tool behavior as raw text chunks and reconstructs state from that text in the frontend. The second-highest-risk boundary is persistence, because the DB layer currently stores both structured tool-call metadata and legacy markdown contracts, which makes the canonical event model ambiguous.

---

## Consolidated Findings

### FC-A1 — Native function-calling already exists, but it is still a sidecar instead of the primary contract

- **Affected components:** `app/tools/schemas.py`, `app/tools/registry.py`, `app/llm_client.py`, `app/providers/base.py`, `app/providers/openrouter.py`, `app/orchestrator.py`, `app/db/facade.py`, `app/db/queries.py`
- **Current behavior:**
  - Tool schemas are already generated in OpenAI function-calling shape.
  - Native `tool_calls` are already parsed in the non-streaming path when providers return them.
  - Tool-call metadata is already persisted in `messages.tool_calls` and `messages.tool_call_id`.
  - But the architecture still treats these pieces as a parallel track to the legacy command protocol, not as the single source of truth.
- **Desired behavior:**
  - Native function-calling becomes the only authoritative tool-call contract.
  - Tool schema generation, provider capabilities, execution, persistence, and replay all use the same canonical event model.
  - Legacy text protocols stop defining the runtime shape of tool execution.
- **Architectural impact:** High. This changes the meaning of the entire tool pipeline.
- **Migration complexity:** Medium. The foundation is already present, but it is fragmented.
- **Dependencies:** None.
- **Recommendation:** Reuse the existing `ToolDefinition` schema, `tool_calls` persistence columns, and provider parsing hooks as the base of the migration. Do not invent a second canonical tool description format.

### FC-A2 — System prompt construction still teaches the model to emit `<command>` blocks

- **Affected components:** `app/prompts.py`, `app/llm_client.py`, `app/orchestrator.py`
- **Current behavior:**
  - The system prompt contains detailed `<command>` syntax instructions, examples, and output rules.
  - The prompt still describes a max-3 textual block protocol.
  - The prompt also teaches tool aliases and legacy tool usage patterns.
- **Desired behavior:**
  - The prompt should describe native function calling as the primary contract.
  - Tool instructions should be provider-agnostic and schema-driven, not markup-driven.
  - Streaming and non-streaming passes should receive the same tool semantics.
- **Architectural impact:** High. Prompt shape directly drives model behavior and downstream parser requirements.
- **Migration complexity:** Medium. This is conceptually simple, but prompt drift will break the runtime if done too early.
- **Dependencies:** FC-A1, FC-A3.
- **Recommendation:** Move prompt generation to a single schema-backed tool description block and remove `<command>` examples only after the provider and orchestrator paths can fully consume native tool calls.

### FC-A3 — `llm_client.py` still splits request construction from response semantics in a way that favors legacy behavior

- **Affected components:** `app/llm_client.py`, `app/providers/base.py`, `app/providers/__init__.py`, `app/providers/openrouter.py`, `app/providers/chutes.py`, `app/providers/ollama.py`, `app/providers/cerebras.py`
- **Current behavior:**
  - `llm_client.py` always gathers tool schemas, but the way they are consumed still depends on provider-specific behavior.
  - Non-streaming requests can return raw responses that are later parsed for tool calls.
  - Streaming requests yield text chunks only, so the orchestration layer has no structured tool-call channel there.
  - `suppress_tools` is used to strip tool definitions for synthesis passes, but the resulting behavior is still split between “tool-enabled” and “tool-hidden” text generation.
- **Desired behavior:**
  - The client layer should speak a single event-oriented contract for both request types.
  - Tool-call enablement should be capability-aware rather than assumed.
  - Streaming and non-streaming responses should share the same downstream event envelope.
- **Architectural impact:** High. This is the bridge between provider behavior and orchestration.
- **Migration complexity:** High. The client layer currently sits on top of several provider-specific quirks.
- **Dependencies:** FC-A1.
- **Recommendation:** Make `llm_client.py` the adapter that emits canonical request/response envelopes, not a text-stream wrapper with special cases. Keep tool schema generation centralized and move capability decisions into provider metadata.

### FC-A4 — Provider adapters are inconsistent: native tool-call support is partial, asymmetric, and mostly non-streaming

- **Affected components:** `app/providers/base.py`, `app/providers/openrouter.py`, `app/providers/chutes.py`, `app/providers/ollama.py`, `app/providers/cerebras.py`
- **Current behavior:**
  - `OpenRouterProvider` already attaches `tools` and `tool_choice`, and parses `tool_calls` from raw responses.
  - `ChutesProvider`, `OllamaProvider`, and `CerebrasProvider` are primarily content-streaming adapters and do not expose a uniform tool-call event stream.
  - `AIProvider.send_message_raw()` can synthesize a raw response with empty `tool_calls`, which hides adapter differences instead of resolving them.
  - Streaming methods still emit plain text chunks, not structured tool events.
- **Desired behavior:**
  - Each provider declares its actual tool-call capabilities explicitly.
  - Providers that support native function calling expose raw tool-call events in a canonical shape.
  - Providers that do not support native function calling are treated as capability-limited, not silently normalized into the same behavior.
- **Architectural impact:** High. The provider layer defines what the rest of the system can assume.
- **Migration complexity:** High. Each adapter currently has its own request and streaming conventions.
- **Dependencies:** FC-A1, FC-A3.
- **Recommendation:** Add a capability matrix to the provider layer and normalize tool-call parsing there, not in the orchestrator. Treat streaming tool-call support as a first-class capability decision.

### FC-A5 — The orchestrator still has two tool grammars and duplicate execution logic

- **Affected components:** `app/orchestrator.py`, `app/commands.py`, `app/tools/registry.py`, `app/services/chat_service.py`
- **Current behavior:**
  - The non-streaming path parses native `tool_calls` from raw provider responses.
  - The streaming path still parses `<command>` blocks from text.
  - There are separate execution flows for parsed command strings and native tool-call dictionaries.
  - Tool persistence is split across multiple helper functions that differ mainly by which protocol produced the tool action.
- **Desired behavior:**
  - One orchestration path should execute tool calls regardless of how they arrived.
  - Tool call parsing should live in provider adapters and the canonical event envelope, not in two separate orchestrator branches.
  - Continuation loops should operate on structured tool-call events instead of reconstructing intent from text blocks.
- **Architectural impact:** Very high. This is the core migration target.
- **Migration complexity:** Very high. The current architecture is built around the dual path.
- **Dependencies:** FC-A1, FC-A2, FC-A3, FC-A4.
- **Recommendation:** Collapse execution into one canonical tool-event path and leave the legacy command parser only as a temporary compatibility bridge if a provider or stream path still cannot emit native tool calls during the transition.

### FC-A6 — Persistence already stores tool-call metadata, but replay still depends on markdown contracts and legacy normalization

- **Affected components:** `app/db/queries.py`, `app/db/facade.py`, `app/db/models_async.py`, `app/tools/schemas.py`, `app/orchestrator.py`
- **Current behavior:**
  - The messages table stores `tool_calls` and `tool_call_id`.
  - The DB formatting layer still has helpers that extract raw results from markdown contracts and normalize legacy tool-result shapes.
  - Tool output is still wrapped in a text contract for display and replay.
  - Historical playback and AI-context reconstruction still treat markdown as an important protocol artifact, not just a render artifact.
- **Desired behavior:**
  - Persistence should store canonical structured events first, with markdown as a presentation layer only.
  - Replay should reconstruct the conversation from structured data, not from re-parsed contract text.
  - Tool outputs should be representable without depending on command-style or contract-style markup.
- **Architectural impact:** High. Persistence is the source of truth for replay and stream recovery.
- **Migration complexity:** High. The DB layer currently supports both old and new shapes.
- **Dependencies:** FC-A1, FC-A5.
- **Recommendation:** Treat structured tool-call metadata as the canonical persistence model and demote markdown contracts to presentation output. Only keep compatibility transforms if the streaming/UI transition proves they are unavoidable.

### FC-A7 — Streaming, SSE, and frontend rendering still assume textual command blocks

- **Affected components:** `app/api/endpoints/chat.py`, `app/api/endpoints/stream.py`, `app/stream_manager.py`, `static/js/modules/multimodal.js`, `static/js/modules/stream-manager.js`, `static/js/modules/history.js`, `static/js/renderer.js`, `static/js/chat.js`
- **Current behavior:**
  - SSE streams still carry plain text chunks that the client reconstructs incrementally.
  - The frontend streaming renderer recognizes unclosed command blocks and command-style tool markup.
  - The history/rebind logic knows how to resurrect an active stream from textual buffer state.
  - The frontend does not have a native representation for tool-call events, tool-result events, or provider events.
- **Desired behavior:**
  - The stream should emit structured event types, not only text chunks.
  - The frontend should render tool calls and tool results from event data, not from regex scanning of the content stream.
  - Stream rebind/replay should recover from canonical structured state.
- **Architectural impact:** Very high. This is the user-visible migration boundary.
- **Migration complexity:** Very high. Streaming is the most stateful path in the codebase.
- **Dependencies:** FC-A5, FC-A6.
- **Recommendation:** Treat the streaming event envelope as a new contract surface. Keep the current buffer/rebind mechanism until the event model is stable, then remove command-block-specific rendering.

### FC-A8 — REST API and service boundaries are still coupled to legacy message-shape assumptions

- **Affected components:** `app/api/endpoints/chat.py`, `app/api/endpoints/profile.py`, `app/services/chat_service.py`, `app/services/session_service.py`, `app/api/main.py`
- **Current behavior:**
  - The API layer exposes message and stream endpoints that are optimized around the existing text-stream behavior.
  - `/api/send_message_stream` passes through the current orchestration semantics without an explicit event schema.
  - Special cases such as `/imagine` still flow through the same message-based path as tool execution.
- **Desired behavior:**
  - The API should expose a structured event stream contract that cleanly separates tokens, tool calls, tool results, and final completion.
  - Image generation and other tool invocations should be just tool calls, not message-path exceptions.
- **Architectural impact:** Medium to high. The API is stable but currently encodes old assumptions.
- **Migration complexity:** Medium. The API is thin, but it sits on top of several coupled services.
- **Dependencies:** FC-A5, FC-A7.
- **Recommendation:** Keep the API surface stable while the underlying event format changes, then remove message-shape special cases once the new stream contract is fully adopted.

### FC-A9 — Logging and telemetry are not yet correlated across the tool-call lifecycle

- **Affected components:** `app/logging_config.py`, `app/orchestrator.py`, `app/tools/registry.py`, `app/providers/*.py`, `app/stream_manager.py`, `app/api/endpoints/chat.py`, `static/js/modules/multimodal.js`
- **Current behavior:**
  - Logs exist at the provider, orchestrator, stream, and UI layers.
  - Tool call logs are split between native tool-call logging and command-parser logging.
  - There is no obvious shared correlation ID that ties provider response, parsed tool call, execution, persistence, SSE emission, and UI replay together.
- **Desired behavior:**
  - Every tool-call lifecycle should have one correlation identifier that flows through provider parse, orchestration, persistence, and streaming.
  - Logging should describe the same event sequence regardless of whether the provider used native function calling or a fallback path.
- **Architectural impact:** Medium. This does not define behavior, but it is critical for operating the migration safely.
- **Migration complexity:** Medium.
- **Dependencies:** FC-A5, FC-A6, FC-A7.
- **Recommendation:** Add lifecycle correlation at the event-envelope level, not as ad hoc log strings.

### FC-A10 — The test suite is still command-protocol centric and does not fully exercise native function calling

- **Affected components:** `tests/test_commands.py`, `tests/test_database_facade.py`, `tests/test_db_queries.py`, `tests/test_profile_analysis.py`, `tests/test_python_exec.py`, `tests/test_shell_exec.py`, `tests/test_fs_operations.py`, `tests/test_vision_pipeline.py`
- **Current behavior:**
  - The most direct protocol tests validate `<command>` parsing and command execution.
  - There is no comparable test matrix for native tool-call parsing, tool-call persistence, provider capability negotiation, or streaming tool-call events.
  - Existing tests do cover many tools and DB helpers, but not the native migration as a system.
- **Desired behavior:**
  - The tests should validate the canonical native function-calling path first.
  - Legacy protocol tests should either disappear or become narrow compatibility tests.
  - Provider, orchestrator, persistence, and frontend event behavior should all have coverage.
- **Architectural impact:** High. The test suite is the migration safety net.
- **Migration complexity:** Medium to high.
- **Dependencies:** FC-A1 through FC-A7.
- **Recommendation:** Build tests around the event envelope and tool-call lifecycle, not around string parsing of `<command>` blocks.

### FC-A11 — Documentation and operational guidance still teach the legacy protocol as canonical

- **Affected components:** `AGENTS.md`, `README.md`, `app/README.md`, `app/api/README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `INSTALL.md`, `tests/` documentation comments
- **Current behavior:**
  - The documentation still presents `<command>` as the primary tool protocol.
  - Operational guidance still reinforces the dual path.
  - Reader-facing docs and code comments still reflect the old contract.
- **Desired behavior:**
  - Documentation should describe native function calling as the only canonical runtime contract.
  - Any legacy compatibility should be explicitly marked as transitional and non-authoritative.
  - Developer guidance should align with the migrated event model and replay semantics.
- **Architectural impact:** Medium. Docs do not run the code, but they train future changes.
- **Migration complexity:** Low to medium.
- **Dependencies:** FC-A2, FC-A5, FC-A7, FC-A10.
- **Recommendation:** Update docs only after the runtime contract is stable enough that the docs will not immediately go stale.

---

## Migration Surface Summary

| Layer | Current state | Migration pressure |
| --- | --- | --- |
| Prompt construction | Legacy `<command>`-first | High |
| Tool schema generation | Native schema already exists | Medium |
| Provider manager/adapters | Partial native support, inconsistent streaming | High |
| LLM client | Tool-aware but not event-unified | High |
| Orchestration | Dual grammar, duplicate dispatch | Very high |
| Persistence | Structured metadata plus markdown contracts | High |
| Streaming / SSE | Text chunks only, command-aware frontend | Very high |
| Frontend rendering | Command-block oriented | Very high |
| REST API | Message-shape coupled | Medium to high |
| Logging / telemetry | Fragmented lifecycle tracing | Medium |
| Tests | Command-protocol centric | High |
| Documentation | Legacy protocol still canonical | High |

---

## Recommended Order of Attack

1. **Canonize the tool contract** — registry, tool schema, capability flags, and prompt shape.
2. **Normalize provider adapters** — make native tool-call behavior explicit and capability-aware.
3. **Unify orchestration and persistence** — one event model for execution, storage, and replay.
4. **Migrate streaming and frontend rendering** — emit and render structured tool events.
5. **Remove the legacy protocol** — delete `<command>` parsing, legacy docs, and protocol-specific tests after the new path is stable.

---

## Coverage Note

This audit intentionally treats the whole tool execution architecture as the migration target, not only the synthesis loop.

That includes:

- prompt construction
- system prompt generation
- tool specification generation
- tool registry
- provider manager
- provider adapters
- LLM client
- streaming requests
- non-streaming requests
- provider response parsing
- tool call parsing
- tool dispatch
- tool execution
- continuation loop
- orchestration
- frontend rendering
- SSE events
- REST API
- persistence
- logging
- telemetry
- tests
- documentation

The repository is already partially native-function-call aware. The migration is about making that path canonical and deleting the text-protocol split, not inventing native support from scratch.
