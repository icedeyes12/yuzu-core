# 蛇足 (Snake Feet) Audit — Yuzu Companion

> **Updated:** 2026-06-29
> **Scope:** Full codebase audit for unnecessary complexity
> **Goal:** Simplify, make robust, future-proof
>
> **Status:** Consolidated current state. This document is the single source of truth and does not record history.

---

## Executive Summary

The codebase still carries a lot of redundant surface area in the database layer, provider layer, service layer, frontend modules, templates/styles, and maintenance scripts. The highest-value simplifications are:

1. remove dead sync DB surfaces and misleading aliases
2. collapse the split tool-protocol path into one protocol
3. delete legacy sync wrappers and dead helper branches in services and tools
4. remove orphaned frontend/template/style files
5. simplify or delete one-off maintenance scripts that now outgrew their purpose

### Current audit status

- **Production surface:** audited
- **Non-production test suite:** partially audited
- **Unaudited production areas:** none

---

## Consolidated findings

### 1. The database layer still carries a dead sync mirror and extra facade boilerplate

- **Files:** `app/db/models.py`, `app/db/models_async.py`, `app/db/facade.py`, `app/db/__init__.py`
- **What’s wrong:** The sync model layer is a near-duplicate of the async one, and the facade still exposes a large sync surface even though the live app paths are async-first. The codebase also re-exports a lot of compatibility wrappers that are not needed in the runtime path.
- **Why it matters:** This makes the DB layer look more authoritative and more complicated than it is. Every duplicate method increases the chance that future fixes land in the wrong place.
- **Impact:** High
- **Simplest practical fix:** Remove the sync mirror where it is not used, trim the facade to the active async surface, and delete the obsolete exports.

### 2. Database helper naming still mixes up current state, note history, and aliases

- **Files:** `app/db/queries.py`, `app/db/models.py`, `app/db/models_async.py`, `app/db/facade.py`
- **What’s wrong:** Several helpers are either thin aliases or misleadingly named: `get_recent_messages`, `add_memory_note`, `add_tool_result`, `update_session_memory`, `get_session_memory`, `get_recent_sessions`, and `get_recent_sessions_for_session`. Some of these are just historical shims; others query different data than the name suggests.
- **Why it matters:** The database API should be boring and precise. Right now it has multiple names for the same thing and at least one function whose name implies one data source while it reads another.
- **Impact:** Medium
- **Simplest practical fix:** Keep one canonical helper per behavior, rename the misleading ones to match what they actually read, and delete the aliases once callers are moved.

### 3. The tool protocol is still split across two paths

- **Files:** `app/orchestrator.py`, `app/commands.py`, `app/prompts.py`
- **What’s wrong:** The runtime still supports both native function calling and `<command>...</command>` parsing. That doubles the parsing, prompt instructions, and execution flow. There are also dead or redundant helpers around tool observation formatting and ephemeral context reconstruction.
- **Why it matters:** Two tool protocols means two places to drift, two sets of assumptions for the model, and more fragile streaming behavior.
- **Impact:** High
- **Simplest practical fix:** Pick one tool protocol and remove the other. Then delete the dead observation/ephemeral-context helpers and keep the prompt instructions aligned with the single active path.

### 4. Provider calls still mix async and blocking I/O

- **Files:** `app/providers/base.py`, `app/providers/openrouter.py`, `app/providers/ollama.py`, `app/providers/cerebras.py`, `app/llm_client.py`
- **What’s wrong:** The base `send_message_raw()` contract is async, but the provider implementations still rely on blocking `requests.post()` in multiple places. Separately, `chutes_chat()` bypasses the provider registry entirely and duplicates provider logic.
- **Why it matters:** Blocking network calls in an async request path are avoidable latency debt. Parallel provider paths are worse: they create two architectures for the same behavior.
- **Impact:** High
- **Simplest practical fix:** Make the provider I/O model consistent, move blocking calls off the event loop or convert them to async HTTP, and route Chutes through the provider manager instead of a standalone helper.

### 5. The service layer still exposes legacy sync wrappers and stale constants

- **Files:** `app/services/session_service.py`, `app/services/config_service.py`, `app/services/memory_service.py`
- **What’s wrong:** `SessionService` still keeps a pile of legacy sync helpers and bootstrap methods that no current route uses. `ConfigService` still exposes sync setters alongside the live async versions. `MemoryService` has a stale throttle constant that conflicts with the active pipeline cadence elsewhere.
- **Why it matters:** The service layer should be the clean boundary between routes and business logic. Instead it still contains compatibility ballast from older behavior.
- **Impact:** Medium
- **Simplest practical fix:** Delete the unused sync wrappers and bootstrap helpers, keep the async service paths only, and centralize the memory throttle in one place.

### 6. The API surface still has stubs, aliases, and duplicate identity logic

- **Files:** `app/api/endpoints/profile.py`, `app/api/endpoints/auth.py`, `app/api/utils.py`, `main.py`, `app/auth/session.py`
- **What’s wrong:** There is a fake vision test endpoint, a weather-location alias that adds no behavior, a display-name persistence helper that wraps a single DB call, a salted `hash()`-based client-id helper in `main.py`, and a one-line token wrapper in session auth.
- **Why it matters:** API surfaces should either do real work or disappear. Fake tests and dead aliases create a false sense of capability. Duplicate identity helpers are a maintenance trap.
- **Impact:** Medium
- **Simplest practical fix:** Remove the aliases and wrapper helpers, replace the fake vision test with a real check or delete it, and keep client identity generation in one canonical place.

### 7. Several tool modules keep unused legacy branches or dead helpers

- **Files:** `app/tools/shell_exec.py`, `app/tools/db_query.py`, `app/tools/python_exec.py`, `app/tools/multimodal.py`
- **What’s wrong:** `shell_exec.py` still contains a persistent-session subsystem that the active path does not use. `db_query.py` keeps an unused parser helper and redundant partner-name plumbing. `python_exec.py` has an unreachable logging branch and a redundant profile helper. `multimodal.py` still includes a legacy image formatter that is not part of the active flow.
- **Why it matters:** These tools are already security-sensitive and stateful enough. Dead branches make them harder to audit and easier to misuse.
- **Impact:** Medium
- **Simplest practical fix:** Delete the unused helpers and keep each tool focused on one active execution path.

### 8. The frontend still exports dead state and keeps an unused finalization path

- **Files:** `static/js/modules/state.js`, `static/js/modules/history.js`, `static/js/modules/multimodal.js`, `static/js/modules/index.js`
- **What’s wrong:** `_currentPage` is exported but unused. `isHistoryLoading()` and `getPendingSessionId()` are exported but have no consumers. `finalizeStreamMessage()` is still present even though the live stream flow finalizes through the active render path.
- **Why it matters:** Dead exports make the module surface look more intentional than it is. Multiple finalization concepts in the same streaming module are a maintenance hazard.
- **Impact:** Medium
- **Simplest practical fix:** Remove the dead exports and keep a single stream finalization path.

### 9. The TUI client still carries ceremonial state and thin no-op UX hooks

- **Files:** `cli/app.py`, `cli/widgets/chat_log.py`, `cli/widgets/input_box.py`, `cli/widgets/session_list.py`, `cli/client.py`
- **What’s wrong:** The TUI has some useful behavior, but it still carries a few ceremonial hooks: a help binding that only rings the bell, a hidden-tag filtering path that is never used, and state variables that could be simplified further if the UI stopped pretending to be more interactive than it is.
- **Why it matters:** Small UX stubs are cheap individually and expensive collectively. The TUI reads cleaner if each control actually does something or gets deleted.
- **Impact:** Low
- **Simplest practical fix:** Replace the no-op help binding with a real help surface or remove it, and delete the dead hidden-tag path.

### 10. The stylesheet and template surface still contains orphaned or duplicated assets

- **Files:** `static/css/index.css`, `static/css/multimodal.css`, `static/css/components/multimodal.css`, `templates/chat.html`, `templates/multimodal_chat.html`, `templates/index.html`, `templates/about.html`, `templates/config.html`
- **What’s wrong:** `index.css` is orphaned. Multimodal styles are split across overlapping sources of truth. `chat.html` still loads Tailwind CDN even though the page does not actually use Tailwind utilities. `multimodal_chat.html` is an orphaned legacy template. The footer markup is duplicated across multiple pages.
- **Why it matters:** Dead styles and orphan templates are maintenance debt. Split style sources and duplicated chrome make future visual changes more annoying than they should be.
- **Impact:** Medium
- **Simplest practical fix:** Delete or wire up orphaned assets, pick one multimodal stylesheet as canonical, remove the unnecessary Tailwind CDN include, and consolidate the shared footer into one partial.

### 11. The maintenance scripts have outgrown their original purpose

- **Files:** `scripts/cleanup_memory`, `scripts/cleanup_memory.sql`, `scripts/reembed_all.py`, `scripts/show_memory_context.py`, `scripts/yuzu_cli.py`, `scripts/migrate_memory_state.py`, `scripts/migrate_to_message_id_tracking.py`
- **What’s wrong:** One script is empty, one performs hard deletes against `semantic_facts`, one has become a mini-framework for re-embedding, and the others are narrow debugging or convenience utilities with hardcoded defaults or low safeguards.
- **Why it matters:** Maintenance scripts should be blunt instruments, not surprise architectures. The more one-off logic they accumulate, the more likely someone will run the wrong thing at the wrong time.
- **Impact:** Medium
- **Simplest practical fix:** Delete empty artifacts, convert hard deletes to soft deletes, simplify the re-embed flow, and either quarantine or clearly label the debug-only utilities.

### 12. The shell and SQL tooling could be simpler and safer

- **Files:** `app/tools/shell_exec.py`, `app/tools/db_query.py`
- **What’s wrong:** `shell_exec.py` keeps a dead persistent-session model alongside the live stateless command path. `db_query.py` shells out to `psql` and keeps helper code that is not actually used.
- **Why it matters:** These tools are already sharp enough. Extra layers do not make them safer; they just make them harder to reason about.
- **Impact:** Medium
- **Simplest practical fix:** Keep the tools stateless and strip out the unused helper paths.

### 13. The memory pipeline has one real source of truth now; the leftover constant should go

- **Files:** `app/orchestrator.py`, `app/services/memory_service.py`
- **What’s wrong:** The orchestration layer still carries a stale pipeline interval constant even though the active throttle now lives in `MemoryService`.
- **Why it matters:** Duplicate cadence constants are how bugs become folklore.
- **Impact:** Low
- **Simplest practical fix:** Delete the stale constant and keep the cadence in the service layer that actually owns it.

---

## Consolidated repository coverage

| Top-level directory/package | Status | Notes |
| --- | --- | --- |
| `.gemini/` | Out of scope | Tooling scratch space, not part of production runtime. |
| `.github/` | Out of scope | CI/automation only. |
| `.hermes/` | Out of scope | Local metadata/tooling area. |
| `.pytest_cache/` | Out of scope | Cache only. |
| `.ruff_cache/` | Out of scope | Cache only. |
| `__pycache__/` | Out of scope | Cache only. |
| `app/` | Audited | Core runtime audited across auth, api, db, memory, providers, services, tools, and orchestrator. |
| `archive/` | Out of scope | Historical material only. |
| `cli/` | Audited | TUI client, widgets, and styles reviewed. |
| `docs/` | Out of scope | Documentation/history, not production code. |
| `migrations/` | Audited | Migration SQL reviewed for safety and relevance. |
| `scripts/` | Audited | Maintenance scripts reviewed. |
| `static/` | Audited | JS/CSS runtime surface reviewed. |
| `templates/` | Audited | Live templates reviewed. |
| `tests/` | Partially audited | Reviewed at inventory level; not fully line-audited. |
| `yuzu_companion.egg-info/` | Out of scope | Packaging metadata only. |

### Coverage conclusion

- **Production surface:** complete enough for this audit goal
- **Unaudited production directories/modules:** none
- **Remaining partial area:** `tests/` only

---

## Recommended order of attack

1. **Remove dead sync DB surfaces and aliases**
2. **Collapse the tool protocol to one path**
3. **Delete legacy sync wrappers in services**
4. **Strip unused stateful helpers from tools**
5. **Delete orphaned frontend assets and templates**
6. **Simplify or delete the one-off maintenance scripts**

---

## Notes for future updates

When new information changes an existing section, update that section in place and keep only the latest accurate state. Do not append contradictory status rows or duplicate findings later in the document.
