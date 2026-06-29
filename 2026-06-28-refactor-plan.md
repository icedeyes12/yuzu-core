# Yuzu Companion — Refactor Implementation Master Plan

> **Based on:** `file 2026-06-28-snake-feet-audit.md`
****Purpose:** turn the audit into an execution roadmap
****Authority:** this plan is the only document implementation agents should update
****Audit report:** immutable
****Plan status:** living document
****Allowed updates by implementation agents:** Status, Commit hash, Notes, Completion date

---

## Planning rules

1. **Implement foundational changes first.**
2. **Do not schedule redundant work.** If one parent change naturally resolves a smaller finding, mark the smaller finding as expected to be resolved.
3. **Prefer low-risk cleanup before deeper refactors.**
4. **Minimize merge conflicts.** Keep each phase tightly scoped to one subsystem.
5. **Do not rewrite phase order or dependencies** unless the audit report is contradicted by new evidence.

---

## Phase 1 — Core database consolidation

Focus: remove the dead sync mirror and trim the DB API surface before touching higher-level code.

### F1 — Dead sync mirror and extra facade boilerplate

| Field | Value |
| --- | --- |
| Finding ID | F1 |
| Title | The database layer still carries a dead sync mirror and extra facade boilerplate |
| Priority | High |
| Estimated difficulty | Medium |
| Files affected | `file app/db/models.py`, `file app/db/models_async.py`, `file app/db/facade.py`, `file app/db/__init__.py` |
| Dependencies | None |
| Status | Not Started |
| Master plan status | Scheduled |

### F2 — Misleading DB helper names and aliases

| Field | Value |
| --- | --- |
| Finding ID | F2 |
| Title | Database helper naming still mixes up current state, note history, and aliases |
| Priority | Medium |
| Estimated difficulty | Low |
| Files affected | `file app/db/queries.py`, `file app/db/models.py`, `file app/db/models_async.py`, `file app/db/facade.py` |
| Dependencies | Recommended after F1 |
| Status | Not Started |
| Master plan status | Scheduled |

**Phase dependency note:** F2 should follow F1 to reduce DB-layer churn and keep the rename/delete sweep in one branch.

---

## Phase 2 — Tool protocol and provider consistency

Focus: collapse the dual tool protocol, then normalize provider I/O so the orchestration path has one coherent shape.

### F3 — Split tool protocol

| Field | Value |
| --- | --- |
| Finding ID | F3 |
| Title | The tool protocol is still split across two paths |
| Priority | High |
| Estimated difficulty | High |
| Files affected | `file app/orchestrator.py`, `file app/commands.py`, `file app/prompts.py` |
| Dependencies | None |
| Status | Not Started |
| Master plan status | Scheduled |

### F4 — Mixed async and blocking provider I/O

| Field | Value |
| --- | --- |
| Finding ID | F4 |
| Title | Provider calls still mix async and blocking I/O |
| Priority | High |
| Estimated difficulty | Medium |
| Files affected | `file app/providers/base.py`, `file app/providers/openrouter.py`, `file app/providers/ollama.py`, `file app/providers/cerebras.py`, `file app/llm_client.py` |
| Dependencies | Recommended after F3 |
| Status | Not Started |
| Master plan status | Scheduled |

**Phase dependency note:** F4 is independent in principle, but it should land after F3 so provider changes are not merged against a moving orchestration contract.

---

## Phase 3 — Service and API cleanup

Focus: remove legacy sync wrappers, dead stubs, and duplicate identity logic from the public surface.

### F5 — Legacy sync wrappers and stale constants in services

| Field | Value |
| --- | --- |
| Finding ID | F5 |
| Title | The service layer still exposes legacy sync wrappers and stale constants |
| Priority | Medium |
| Estimated difficulty | Medium |
| Files affected | `file app/services/session_service.py`, `file app/services/config_service.py`, `file app/services/memory_service.py` |
| Dependencies | None |
| Status | Not Started |
| Master plan status | Scheduled |

### F6 — API stubs, aliases, and duplicate identity logic

| Field | Value |
| --- | --- |
| Finding ID | F6 |
| Title | The API surface still has stubs, aliases, and duplicate identity logic |
| Priority | Medium |
| Estimated difficulty | Medium |
| Files affected | `file app/api/endpoints/profile.py`, `file app/api/endpoints/auth.py`, `file app/api/utils.py`, `file main.py`, `file app/auth/session.py` |
| Dependencies | Recommended after F5 |
| Status | Not Started |
| Master plan status | Scheduled |

### F13 — Stale pipeline constant in orchestrator

| Field | Value |
| --- | --- |
| Finding ID | F13 |
| Title | The memory pipeline has one real source of truth now; the leftover constant should go |
| Priority | Low |
| Estimated difficulty | Trivial |
| Files affected | `file app/orchestrator.py`, `file app/services/memory_service.py` |
| Dependencies | Expected to be resolved by F5 |
| Status | Expected to be resolved by F5 |
| Master plan status | Not scheduled separately |

**Phase dependency note:** F13 is folded into F5 because the service-layer throttle is the actual source of truth and the stale orchestrator constant should disappear as part of that cleanup.

---

## Phase 4 — Tool implementation simplification

Focus: strip dead helper branches from the security-sensitive tool modules after the orchestration contract is settled.

### F7 — Legacy branches and dead helpers in tools

| Field | Value |
| --- | --- |
| Finding ID | F7 |
| Title | Several tool modules keep unused legacy branches or dead helpers |
| Priority | Medium |
| Estimated difficulty | Medium |
| Files affected | `file app/tools/shell_exec.py`, `file app/tools/db_query.py`, `file app/tools/python_exec.py`, `file app/tools/multimodal.py` |
| Dependencies | Recommended after F3 |
| Status | Not Started |
| Master plan status | Scheduled |

### F12 — Shell and SQL tooling could be simpler and safer

| Field | Value |
| --- | --- |
| Finding ID | F12 |
| Title | The shell and SQL tooling could be simpler and safer |
| Priority | Medium |
| Estimated difficulty | Low |
| Files affected | `file app/tools/shell_exec.py`, `file app/tools/db_query.py` |
| Dependencies | Expected to be resolved by F7 |
| Status | Expected to be resolved by F7 |
| Master plan status | Not scheduled separately |

**Phase dependency note:** F12 is a narrower view of F7 and should not be implemented separately.

---

## Phase 5 — Frontend, TUI, and asset cleanup

Focus: delete dead exports, kill unused finalization paths, and clean up duplicated presentation assets.

### F8 — Dead frontend state and unused finalization path

| Field | Value |
| --- | --- |
| Finding ID | F8 |
| Title | The frontend still exports dead state and keeps an unused finalization path |
| Priority | Medium |
| Estimated difficulty | Medium |
| Files affected | `file static/js/modules/state.js`, `file static/js/modules/history.js`, `file static/js/modules/multimodal.js`, `file static/js/modules/index.js` |
| Dependencies | Recommended after F3 and F7 |
| Status | Not Started |
| Master plan status | Scheduled |

### F9 — Ceremonial state and no-op UX hooks in the TUI client

| Field | Value |
| --- | --- |
| Finding ID | F9 |
| Title | The TUI client still carries ceremonial state and thin no-op UX hooks |
| Priority | Low |
| Estimated difficulty | Low |
| Files affected | `file cli/app.py`, `file cli/widgets/chat_log.py`, `file cli/widgets/input_box.py`, `file cli/widgets/session_list.py`, `file cli/client.py` |
| Dependencies | None |
| Status | Not Started |
| Master plan status | Scheduled |

### F10 — Orphaned and duplicated styles/templates

| Field | Value |
| --- | --- |
| Finding ID | F10 |
| Title | The stylesheet and template surface still contains orphaned or duplicated assets |
| Priority | Medium |
| Estimated difficulty | Medium |
| Files affected | `file static/css/index.css`, `file static/css/multimodal.css`, `file static/css/components/multimodal.css`, `file templates/chat.html`, `file templates/multimodal_chat.html`, `file templates/index.html`, `file templates/about.html`, `file templates/config.html` |
| Dependencies | Recommended after F8 |
| Status | Not Started |
| Master plan status | Scheduled |

**Phase dependency note:** F10 should come after the JS cleanup so the visual templates and the live frontend stay in sync while the module surface changes.

---

## Phase 6 — Maintenance script cleanup

Focus: simplify or quarantine one-off scripts after the production runtime is stabilized.

### F11 — Maintenance scripts outgrew their original purpose

| Field | Value |
| --- | --- |
| Finding ID | F11 |
| Title | The maintenance scripts have outgrown their original purpose |
| Priority | Medium |
| Estimated difficulty | Medium |
| Files affected | `scripts/cleanup_memory`, `file scripts/cleanup_memory.sql`, `file scripts/reembed_all.py`, `file scripts/show_memory_context.py`, `file scripts/yuzu_cli.py`, `file scripts/migrate_memory_state.py`, `file scripts/migrate_to_message_id_tracking.py` |
| Dependencies | Recommended after F5 and F7 |
| Status | Not Started |
| Master plan status | Scheduled |

---

## Phase 7 — Final verification

Focus: verify the repo is still coherent after the cleanup passes.

### Verification checklist

- Run Python lint and compile checks on modified files.
- Run JS/CSS validation for the frontend files that changed.
- Run the targeted test subset that covers the touched surfaces.
- Confirm no new duplicate helper paths were introduced while removing the old ones.
- Confirm the audit report remains unchanged.

---

## Dependency summary

- **F1** is the first DB cleanup and should go first.
- **F2** follows **F1**.
- **F3** is the architectural pivot for tool dispatch.
- **F4** should follow **F3**.
- **F5** is the service-layer cleanup anchor.
- **F6** follows **F5**.
- **F13** is expected to disappear as part of **F5**.
- **F7** removes dead tool branches.
- **F12** is expected to disappear as part of **F7**.
- **F8** should land after the tool/protocol work is settled.
- **F9** is independent and safe to do early.
- **F10** follows the frontend JS cleanup.
- **F11** should wait until the runtime surface is stable.

---

## Update contract for implementation agents

Implementation agents may update only these fields in this document:

- Status
- Commit hash
- Notes
- Completion date

They must not rewrite priorities, dependencies, or phase organization unless explicitly instructed.