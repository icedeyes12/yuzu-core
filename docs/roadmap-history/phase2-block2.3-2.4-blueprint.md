# Phase 2 — Block 2.3 + 2.4 Blueprint

## Auth Dependency Injection + user_id Threading

> **Status:** PLANNING ONLY — no patches until approved.
> **Branch:** `dev`
> **Date:** 2026-06-22

---

## Current State (Pre-Block 2.3)

### Single-tenant assumption — 3 root causes

1. **`SQL_PROFILE_SELECT_FIRST = "SELECT * FROM profiles LIMIT 1"`**
   Grabs the first profile row regardless of who's asking. Every `get_profile_async()` call resolves to this.

2. **`SQL_SESSION_SELECT_ACTIVE = "SELECT * FROM chat_sessions WHERE is_active = TRUE AND deleted_at IS NULL LIMIT 1"`**
   Gets THE active session globally — no `user_id` scoping. If two tenants both have `is_active = TRUE`, the first one wins (race).

3. **Orchestrator calls `Database.get_profile_async()` / `Database.get_active_session_async()` with zero arguments** — they never receive a `user_id`. The auth system exists (Block 2.2) but nothing feeds it into the data layer.

### Affected call sites (audit-complete)

| File | Line | Call | Current signature |
| --- | --- | --- | --- |
| `app/orchestrator.py` | 626 | `get_profile_async()` | no user_id |
| `app/orchestrator.py` | 630 | `get_active_session_async()` | no user_id |
| `app/orchestrator.py` | 890 | `get_profile_async()` | no user_id |
| `app/orchestrator.py` | 899 | `get_active_session_async()` | no user_id |
| `app/llm_client.py` | 303 | `get_active_session_async()` | no user_id |
| `app/llm_client.py` | 433 | `get_active_session_async()` | no user_id |
| `app/db/models_async.py` | 153 | `get_active_session_async()` → calls `get_profile_async()` internally | no user_id |
| `app/db/models_async.py` | 170 | `create_session_async()` → calls `get_profile_async()` for user_id | no user_id |
| `app/db/models_async.py` | 357 | `add_message_async()` → calls `get_profile_async()` for user_id | no user_id |

---

## Block 2.3 — Router-level Auth Gate

### Goal
Every router except `auth` and `static` requires a valid session cookie. Unauthenticated requests get 401.

### Step 2.3.1 — Mount auth router in `app/api/main.py`

Add `auth` to imports and `include_router`. The auth router stays **public** (no dependency on itself).

```python
from app.api.endpoints import auth, chat, memory, profile, sessions, stream
# ...
router.include_router(auth.router)        # public — login/callback/logout/me
```

### Step 2.3.2 — Apply `Depends(get_current_user)` to protected routers

Two strategies considered:

**Strategy A (router-level `dependencies=`):**
```python
router.include_router(chat.router, dependencies=[Depends(get_current_user)])
```
- Pros: one line per router, no handler changes needed
- Cons: `user_id` doesn't flow into handlers — can't thread it downstream

**Strategy B (handler-level `user_id: str = Depends(get_current_user)`):**
```python
async def api_send_message(request: MessageRequest, user_id: str = Depends(get_current_user)):
```
- Pros: `user_id` available in every handler, threads into services
- Cons: touches every handler signature (36 handlers)

**Decision: Strategy B.** We need `user_id` in the handlers to pass it to the orchestrator/DB layer. Router-level deps alone would only gate access without enabling multi-tenancy. The 36 signature changes are mechanical and necessary.

### Step 2.3.3 — Handler-by-handler change list

For each handler, add `user_id: str = Depends(get_current_user)` as a parameter and pass it downstream.

**`chat.py` (5 handlers):**
- `api_send_message(request)` → `api_send_message(request, user_id)`
- `api_send_message_stream(request)` → `api_send_message_stream(request, user_id)`
- `api_generate_image(request)` → `api_generate_image(request, user_id)`
- `api_browser_unload(request)` → `api_browser_unload(request, user_id)`

**`sessions.py` (8 handlers):**
- `api_get_chat_history(session_id)` → `api_get_chat_history(session_id, user_id)`
- `api_list_sessions()` → `api_list_sessions(user_id)`
- `api_create_session(http_request, request)` → `api_create_session(http_request, request, user_id)`
- `api_switch_session(request, http_request)` → `api_switch_session(request, http_request, user_id)`
- `api_rename_session(request)` → `api_rename_session(request, user_id)`
- `api_delete_session(request)` → `api_delete_session(request, user_id)`
- `api_clear_chat(request, session_id)` → `api_clear_chat(request, session_id, user_id)`
- `api_end_session(request)` → `api_end_session(request, user_id)`
- `api_get_session_memory(session_id)` → `api_get_session_memory(session_id, user_id)`

**`profile.py` (14 handlers):** — all get `user_id` param, pass to `Database.get_profile_async(user_id)` / `Database.update_profile_async(updates, user_id)` etc.

**`memory.py` (5 handlers):** — all get `user_id` param, pass to memory service calls.

**`stream.py` (2 handlers):** — `get_stream_status(session_id)` → add `user_id`, `sync_stream_buffer(session_id)` → add `user_id`.

**`auth.py`:** — stays public, no changes.

**`static`:** — stays public, no changes.

---

## Block 2.4 — Thread user_id into Orchestrator + DB Layer

### Step 2.4.1 — New SQL constants (scoped variants)

Add to `app/db/queries.py`:

```python
SQL_PROFILE_SELECT_BY_ID = "SELECT * FROM profiles WHERE id = %s"

SQL_SESSION_SELECT_ACTIVE_FOR_USER = """
SELECT * FROM chat_sessions
WHERE user_id = %s AND is_active = TRUE AND deleted_at IS NULL
LIMIT 1
"""

SQL_SESSIONS_DEACTIVATE_FOR_USER = """
UPDATE chat_sessions SET is_active = FALSE
WHERE user_id = %s AND deleted_at IS NULL
"""
```

### Step 2.4.2 — Change DB function signatures (async models)

**`get_profile_async(user_id: str) -> dict`**
- Was: `SQL_PROFILE_SELECT_FIRST` (LIMIT 1)
- Now: `SQL_PROFILE_SELECT_BY_ID` with `(user_id,)`
- If no profile exists for user_id → raise (shouldn't happen post-auth, profile is provisioned at login)

**`get_active_session_async(user_id: str) -> dict`**
- Was: `SQL_SESSION_SELECT_ACTIVE` (global LIMIT 1)
- Now: `SQL_SESSION_SELECT_ACTIVE_FOR_USER` with `(user_id,)`
- If none active → create one scoped to user_id (use existing `create_session_async(name, user_id)`)

**`get_all_sessions_async(user_id: str) -> list[dict]`**
- Was: `SQL_SESSION_SELECT_ALL` (all sessions)
- Now: scoped by `WHERE user_id = %s AND deleted_at IS NULL`

**`switch_session_async(session_id: str, user_id: str) -> bool`**
- Was: deactivate ALL sessions, activate one
- Now: deactivate only user's sessions (`SQL_SESSIONS_DEACTIVATE_FOR_USER`), activate one **with ownership check** (verify the session belongs to this user_id before activating — prevents cross-tenant session hijacking)

**`delete_session_async(session_id: str, user_id: str) -> bool`**
- Add ownership check: `WHERE id = %s AND user_id = %s`

**`rename_session_async(session_id: str, new_name: str, user_id: str) -> bool`**
- Add ownership check: `WHERE id = %s AND user_id = %s`

**`get_session_memory_async(session_id: str, user_id: str) -> dict`**
- Add ownership check before fetching

**`add_message_async(session_id, role, content, ..., user_id) -> int | None`**
- Already accepts `user_id` (Block 1.7 change), but currently defaults to `get_profile_async()` if None
- Change: make `user_id` **required** (no fallback) — it must come from auth

**`get_chat_history_async(session_id, ..., user_id) -> list`**
- Add ownership check: verify session belongs to user_id

### Step 2.4.3 — Mirror changes in sync models (`app/db/models.py`)

Same signature changes for the sync versions. The CLI path (`app/cli.py`) uses sync models — it will need a `user_id` source too. For the CLI, since it's local-only and single-user, it can use the first profile's id as a temporary fallback (or a `--user` flag in future). **Decision: CLI gets user_id from `get_profile()` first-row fallback for now; full CLI auth is out of scope for Phase 2.**

### Step 2.4.4 — Change orchestrator signatures

**`handle_user_message(user_message, interface="terminal", user_id: str | None = None)`**
- If `user_id` is None (CLI path) → fall back to first-profile id
- Pass `user_id` to `Database.get_profile_async(user_id)` and `Database.get_active_session_async(user_id)`

**`handle_user_message_streaming(user_message, interface="web", user_id: str | None = None, ...)`**
- Same pattern

### Step 2.4.5 — Thread user_id through `llm_client.py`

Two call sites (`llm_client.py:303`, `llm_client.py:433`) call `get_active_session_async()`. These functions need to receive `user_id` as a parameter from their callers (orchestrator) and pass it through.

### Step 2.4.6 — Thread user_id through `prompts.py` + memory pipeline

`prompts.py` calls `Database.get_profile_async()` and retrieval functions. These need `user_id` threaded from the orchestrator.

The memory pipeline (`app/memory/`) calls `get_profile_async()` for user context. Thread `user_id` through:
- `app/memory/memory.py` → extraction/retrieval functions
- `app/memory/db_memory.py` → `save_fact` / `save_fact_async` already accept `user_id` (Block 1.7)
- `app/memory/retrieval.py` → needs user_id for scoped retrieval

### Step 2.4.7 — SessionService ownership scoping

`app/api/endpoints/sessions.py` uses `SessionService` (from `app/services/session_service.py`). The session service manages client connection state — it needs to be aware of `user_id` to scope stream buffers and connection events.

---

## Execution Order (within Block 2.3+2.4)

1. **2.3.1** — Mount auth router (1 file, 2 lines)
2. **2.4.1** — Add scoped SQL constants (1 file, ~20 lines)
3. **2.4.2** — Change async DB function signatures (1 file, ~60 lines changed)
4. **2.4.3** — Mirror in sync DB models (1 file, ~40 lines changed)
5. **2.4.4** — Change orchestrator signatures (1 file, ~10 lines changed)
6. **2.4.5** — Thread user_id through llm_client (1 file, ~6 lines changed)
7. **2.4.6** — Thread user_id through prompts + memory (3-4 files, ~20 lines changed)
8. **2.3.3** — Add `Depends(get_current_user)` to all 36 handlers (5 files, ~72 lines changed)
9. **2.4.7** — SessionService scoping (1 file, ~10 lines changed)
10. **Test + lint gate** — ruff + py_compile + pytest

---

## Risk Assessment

| Risk | Mitigation |
| --- | --- |
| CLI breaks (no auth) | user_id=None fallback to first-profile in orchestrator |
| Session hijacking (cross-tenant) | Ownership checks on switch/delete/rename/get_history |
| Stream buffer cross-contamination | SessionService keyed by user_id + session_id |
| Large blast radius (36 handlers) | Mechanical changes, commit after each step group |
| Existing tests break | Update mocks to pass user_id; CLI fallback keeps most tests passing |

---

## Out of Scope (explicitly deferred)

- CLI authentication (Phase 3+)
- Frontend login UI (separate frontend workstream)
- Token refresh / sliding expiration (Phase 2.5+)
- Rate limiting per tenant (Phase 3)
