# Phase 1.7 Audit — UUID Cutover Code Change List

> **Status:** AUDIT ONLY — no code modified yet. For review before implementation.
> **Pre-condition:** DB cutover 1.4–1.6 committed (live DB: profiles/chat_sessions PK = UUIDv7,
> messages.session_id = UUID nullable, tenant user_id FKs on chat_sessions/messages/semantic_facts).
> **Scope:** Trace every integer-touching site related to `id` (profiles, chat_sessions) and
> `session_id` (messages, semantic_facts.metadata). Message-row `id` stays INTEGER — out of scope.

---

## Runtime type decision (READ FIRST — governs every annotation below)

After cutover, `active_session["id"]` and `profile["id"]` return **`uuid.UUID`** objects
(psycopg3 maps UUID columns → `uuid.UUID`). So `session_id` at runtime is `uuid.UUID`, not int.

**Recommended:** annotate as `uuid.UUID | None`, convert to `str` only at (a) API request
boundaries and (b) metadata-JSON construction. psycopg3 binds `uuid.UUID` natively to UUID
columns. FastAPI `jsonable_encoder` serializes `uuid.UUID` natively in JSON responses.

> If you prefer `str` everywhere instead, say so — it simplifies JSON but loses type safety and
> requires explicit `::uuid` casts in some SQL. The change list below assumes `uuid.UUID`.

---

## A. SCHEMA_DDL rewrite — `app/db/queries.py` (lines 94–145)

The code-side schema tuple is now a **lie**: declares SERIAL PKs and
`messages.session_id INTEGER NOT NULL` + FK, but the live DB is UUID. If `init_pg_tables` ever
runs on a fresh DB, it would create the OLD shape. Rewrite to match post-cutover state:

| Table | Current (code) | Required (post-cutover) |
|---|---|---|
| `profiles` | `id SERIAL PRIMARY KEY` | `id UUID PRIMARY KEY DEFAULT generate_uuidv7()` |
| `chat_sessions` | `id SERIAL PRIMARY KEY` | `id UUID PRIMARY KEY DEFAULT generate_uuidv7()` + `user_id UUID REFERENCES profiles(id) ON DELETE CASCADE` + `legacy_int_id INTEGER` |
| `messages` | `session_id INTEGER NOT NULL` + `FK → chat_sessions(id)` | `session_id UUID` (nullable) + `legacy_session_id INTEGER` + `user_id UUID REFERENCES profiles(id) ON DELETE CASCADE` + `FK(session_id) → chat_sessions(id) ON DELETE CASCADE` |
| `api_keys` | `id SERIAL PRIMARY KEY` | **UNCHANGED** (still SERIAL — not part of cutover) |

**Note on `semantic_facts`:** there is **no** `CREATE TABLE semantic_facts` anywhere in `app/`
(grep confirmed). It's a pre-existing table created outside the app (earlier migration / manual).
The live table now has `user_id UUID` (added by cutover 1.6). No code DDL to update, but this is a
pre-existing idempotency gap — flagging, not fixing in 1.7.

---

## B. `metadata->>'session_id'` cast fix — `app/memory/db_memory_queries.py` (2 sites + 1 annotation)

| Line | Current | Required |
|---|---|---|
| 101 | `AND (metadata->>'session_id')::int = %s` (in `SQL_FACT_DECAY_FETCH_FOR_SESSION`) | text comparison |
| 120 | `session_id: int \| None = None` (in `build_metadata_conditions` signature) | `uuid.UUID \| str \| None` |
| 136 | `conditions.append("(metadata->>'session_id')::int = %s")` | text comparison |

**The `::int` cast will throw** `invalid input syntax for type integer` once the app passes a UUID
session_id, because `(metadata->>'session_id')::int` tries to parse a UUID string as int.

### ⚠️ Semantic gap — DECISION REQUIRED

The cast fix alone is not enough. Legacy facts (all 2362 pre-cutover rows) store the **old integer
session id** in `metadata->>'session_id'` (e.g. `"5"`). After 1.7, the app passes a **UUID**
session_id. A pure text comparison `(metadata->>'session_id') = %s::text` makes legacy facts
**invisible** to per-session queries (`"5" ≠ "019283a4-..."`).

| Option | What it does | Trade-off |
|---|---|---|
| **A (recommended)** | One-time SQL migration: rewrite `semantic_facts.metadata->>'session_id'` from legacy int → UUID via `JOIN chat_sessions ON (sf.metadata->>'session_id')::int = cs.legacy_int_id`. Then text comparison is uniform. | Clean. ~2362 rows. Reversible (legacy_int_id preserved on chat_sessions). Extra migration step. |
| B | Text comparison only. Accept legacy-fact invisibility for per-session scoping. | Minimal. Legacy facts still reachable via global/cross-session + `user_id` queries. |
| C | Dual-condition: `(metadata->>'session_id') = %s::text OR (metadata->>'session_id') = (SELECT legacy_int_id::text FROM chat_sessions WHERE id=%s)` | Handles both. Per-row subquery. More complex SQL. |

---

## C. Metadata serialization — NEW breakage (`json.dumps(uuid.UUID)` TypeError)

`extractor.py` builds `{"session_id": session_id, ...}` and `db_memory.py` wraps it in
`Json(meta)`. psycopg's `Json` adapter serializes via `json.dumps` **without `default=str`**, so a
`uuid.UUID` value throws `TypeError: Object of type UUID is not JSON serializable` on every fact
save.

| File | Line | Current | Required |
|---|---|---|---|
| `app/memory/extractor.py` | 226 | `"session_id": session_id,` | `"session_id": str(session_id),` |
| `app/memory/extractor.py` | 310 | `"session_id": session_id,` | `"session_id": str(session_id),` |
| `app/memory/extractor.py` | 356 | `"session_id": session_id,` | `"session_id": str(session_id),` |
| `app/memory/extractor.py` | 384 | `"session_id": session_id,` | `"session_id": str(session_id),` |
| `app/memory/memory.py` | 819 | `"session_id": session_id,` | `"session_id": str(session_id),` |

`db_memory.py` `Json(meta)` (lines 151, 378, 446) needs **no change** once the dict values are str.
(Don't add `default=str` to `Json()` globally — that masks unrelated serialization bugs.)

**Verify (low risk):** `memory.py:194,217` `json.dumps(ms)` for `memory_state` — `session_id` here
is a WHERE param (bound to UUID column), not inside the JSON, so it's safe unless `ms` itself holds
a UUID. Confirm `ms` (fence/count state) contains no UUIDs.

---

## D. API endpoints — Pydantic/FastAPI integer validators (CRITICAL — reject UUIDs)

`Field(..., gt=0)` and `Path(..., ge=1)` reject non-integers and values ≤ 0. A UUID string fails
both validation rules → 422 on every switch/rename/delete/stream call.

| File | Line | Current | Required |
|---|---|---|---|
| `app/api/endpoints/sessions.py` | 34 | `session_id: int = Field(..., gt=0, ...)` (`SessionSwitchRequest`) | `uuid.UUID` (Pydantic validates UUID strings natively) |
| `app/api/endpoints/sessions.py` | 38 | `session_id: int = Field(..., gt=0, ...)` (`SessionRenameRequest`) | `uuid.UUID` |
| `app/api/endpoints/sessions.py` | 43 | `session_id: int = Field(..., gt=0, ...)` (`SessionDeleteRequest`) | `uuid.UUID` |
| `app/api/endpoints/sessions.py` | 47 | `api_get_chat_history(session_id: int \| None = None)` | `uuid.UUID \| None` |
| `app/api/endpoints/sessions.py` | 170 | `api_clear_chat(session_id: int \| None = None)` | `uuid.UUID \| None` |
| `app/api/endpoints/sessions.py` | 202 | `api_get_session_memory(session_id: int)` | `uuid.UUID` |
| `app/api/endpoints/stream.py` | 18 | `session_id: int = Path(..., ge=1, ...)` (`get_stream_status`) | `uuid.UUID` (drop `ge=1`) |
| `app/api/endpoints/stream.py` | 49 | `session_id: int = Path(..., ge=1, ...)` (`sync_stream_buffer`) | `uuid.UUID` (drop `ge=1`) |
| `app/api/endpoints/profile.py` | 82 | `api_get_profile(session_id: int \| None = None)` | `uuid.UUID \| None` |

`if not session_id:` guards at sessions.py:48,173,205 — still valid for UUID (UUID is truthy).
BUT sessions.py:174 `if not session_id:` followed by `session_id = active_session["id"]` — fine.

---

## E. Frontend — `parseInt` mangling (CRITICAL — mangles UUIDs)

`parseInt("019283a4-ec1b-7abc-...")` returns `19` (parses leading digits, stops at first
non-digit). This breaks URL-based session routing immediately after cutover.

| File | Line | Current | Required |
|---|---|---|---|
| `static/js/modules/router.js` | 23 | `this.currentSessionId = parseInt(sessionId, 10);` | `this.currentSessionId = sessionId;` (opaque string) |
| `static/js/modules/router.js` | 67 | `if (sessionId && parseInt(sessionId, 10) !== this.currentSessionId)` | `if (sessionId && sessionId !== this.currentSessionId)` |
| `static/js/modules/router.js` | 69 | `this.currentSessionId = parseInt(sessionId, 10);` | `this.currentSessionId = sessionId;` |

Stale JSDoc `@param {number} sessionId` → `{string}` in: `router.js:36`, `chat.js:49`,
`stream-manager.js` (×10), `sidebar.js:423`. Doc-only, but fix for consistency.

Frontend fetch bodies already send `session_id: sessionId` as-is (`sidebar.js:251,301`) — JS is
dynamically typed, so the **string** UUID passes through fine once `parseInt` is removed. No fetch
logic change needed.

---

## F. Type annotations — `session_id: int` → `uuid.UUID | None` (mechanical, ~90 sites)

Pure annotation changes. No runtime logic change (psycopg binds uuid.UUID natively). Grouped by
file with site count. Add `import uuid` where missing.

| File | Sites | Notes |
|---|---|---|
| `app/memory/db_memory.py` | 10 | incl. `save_fact`, `count_facts`, decay fns |
| `app/db/models.py` | 15 | incl. `create_session -> int \| None` (see H) |
| `app/db/models_async.py` | 20 | incl. `create_session_async -> int \| None` (see H) |
| `app/memory/memory.py` | 10 | incl. fence + pipeline triggers |
| `app/memory/retrieval.py` | 10 | `retrieve_dynamic_memories`, `retrieve_segments`, etc. |
| `app/db/facade.py` | 15 | **incl. `_resolve_session_id(...) -> int` → `-> uuid.UUID`** (line 110, 118) |
| `app/memory/summarization.py` | 3 | |
| `app/memory/memory_review.py` | 3 | |
| `app/memory/pcl.py` | 4 | |
| `app/visual_context.py` | 2 | |
| `app/services/session_service.py` | 5 | |
| `app/stream_manager.py` | 4 | `StreamBuffer` ctor + `get_stream` |
| `app/services/memory_service.py` | 5 | |
| `app/llm_client.py` | 3 | |
| `app/prompts.py` | 5 | |
| `app/orchestrator.py` | 15 | incl. fence `acquire`/`complete`/`is_completed` (771,805,836) |
| `app/commands.py` | 1 | |
| `app/tools/db_query.py` | 1 | passthrough signature |
| `app/tools/fs_operations.py` | 6 | passthrough signatures (6 execute_* fns) |
| `app/tools/python_exec.py` | 1 | passthrough signature |
| `app/tools/shell_exec.py` | 1 | passthrough signature |

**Out of scope (stay int):** `message_id: int`, `after_message_id: int`, `user_msg_id: int`,
`last_message_id: int`, `processed_count: int`, `fact_ids: list[int]`, `limit: int` —
message-row ids are still SERIAL INTEGER. Do NOT touch these.

---

## G. Profile id handling

| File | Line | Current | Action |
|---|---|---|---|
| `app/db/queries.py` | 230 | `"id": row.get("id")` in `parse_profile_row` | No change — now returns `uuid.UUID`. Callers must not assume int. |
| `app/services/config_service.py` | 91 | `"id": profile["id"]` | Verify JSON-serializable. FastAPI `jsonable_encoder` handles `uuid.UUID` natively → likely OK. Verify in response. |
| `app/db/queries.py` | 168 | `DEFAULT_PROFILE_PARAMS` | **No change** — id is auto-generated, not in insert params. |
| `app/db/queries.py` | 198 | `build_profile_update` | **No change** — no id field. |
| `app/db/queries.py` | 156 | `SQL_PROFILE_INSERT_DEFAULT` | **No change** — no id column. |

---

## H. create_session return type

| File | Line | Current | Required |
|---|---|---|---|
| `app/db/models.py` | 206 | `def create_session(...) -> int \| None:` | `-> uuid.UUID \| None` |
| `app/db/models_async.py` | 169 | `async def create_session_async(...) -> int \| None:` | `-> uuid.UUID \| None` |

Both `return row.get("id")` (lines 213, 176) — returns `uuid.UUID` now. Annotation-only.

---

## Decision points for your sign-off

1. **session_id runtime type**: `uuid.UUID` (recommended, type-safe, psycopg-native) vs `str`
   everywhere (simpler JSON, needs `::uuid` casts in some SQL)?
2. **metadata->>'session_id' legacy gap**: Option A (one-time metadata migration int→UUID,
   recommended) vs B (text comparison only, accept legacy invisibility) vs C (dual-condition)?
3. **Scope of this pass**: backend Python only (A–D, F–H) or include frontend (E)? The `parseInt`
   mangling is a hard blocker for URL session routing — recommend including E.

## Suggested execution order (after sign-off)

1. A (SCHEMA_DDL) + H (create_session annotations) — DB layer truth
2. B + Option-A migration (metadata cast + legacy data fix) — memory query correctness
3. C (extractor str() — prevents TypeError on first fact save)
4. D (API validators — unblocks all session endpoints)
5. E (frontend parseInt — unblocks URL routing)
6. F (bulk annotation sweep — mechanical, lint-gated)
7. G verify only
8. Lint: `ruff check .` + `python3 -m py_compile` on changed files + `npx @biomejs/biome check static/js/`
9. Commit per logical group on `dev` (git co-author)
there is a WHERE param, not inside the JSON — OK unless `ms` itself contains a UUID (verify).

---

## D. API endpoints — Pydantic/FastAPI integer validators (CRITICAL — reject UUIDs)

`gt=0` / `ge=1` validators reject UUID strings (not int, not > 0). These endpoints 500 on every
call after cutover.

| File | Lines | Current | Required |
|---|---|---|---|
| `app/api/endpoints/sessions.py` | 34, 38, 43 | `session_id: int = Field(..., gt=0, ...)` (SessionSwitch/Rename/DeleteRequest) | `uuid.UUID` (drop `gt=0`) or `str` |
| `app/api/endpoints/sessions.py` | 47 | `api_get_chat_history(session_id: int \| None = None)` | `uuid.UUID \| str \| None` |
| `app/api/endpoints/sessions.py` | 170 | `api_clear_chat(session_id: int \| None = None)` | same |
| `app/api/endpoints/sessions.py` | 202 | `api_get_session_memory(session_id: int)` | `uuid.UUID` |
| `app/api/endpoints/stream.py` | 18, 49 | `session_id: int = Path(..., ge=1, ...)` | `uuid.UUID` (drop `ge=1`) or `str` |
| `app/api/endpoints/profile.py` | 82 | `api_get_profile(session_id: int \| None = None)` | `uuid.UUID \| str \| None` |

Also: `sessions.py` `if not session_id:` guards (lines ~75, 132, 174) — a UUID is always
truthy, so these are fine, but the `if not request.session_id:` checks are now dead (UUID never
falsy) — leave or simplify.

---

## E. Frontend — `parseInt` mangling (CRITICAL — mangles UUIDs)

`parseInt("019283a4-...", 10)` returns `19` (parses leading digits, stops at first non-digit).
URL-based session routing breaks immediately.

| File | Lines | Current | Required |
|---|---|---|---|
| `static/js/modules/router.js` | 23 | `this.currentSessionId = parseInt(sessionId, 10);` | `this.currentSessionId = sessionId;` (opaque string) |
| `static/js/modules/router.js` | 67 | `parseInt(sessionId, 10) !== this.currentSessionId` | `sessionId !== this.currentSessionId` |
| `static/js/modules/router.js` | 69 | `this.currentSessionId = parseInt(sessionId, 10);` | `this.currentSessionId = sessionId;` |

**Stale JSDoc** `@param {number} sessionId` → `{string}` in: `router.js:36`, `stream-manager.js`
(×10), `chat.js:49`, `sidebar.js:423`. Cosmetic but should be corrected for accuracy.

`sidebar.js` sends `session_id: sessionId` in JSON bodies (lines 251, 301) — JS passes the string
as-is, so the **transport** is fine once router.js stops parseInt-ing. No body-serialization change
needed.

---

## F. Type annotations — `session_id: int` → `uuid.UUID | None` (mechanical, ~90 sites)

No logic change — annotations only. Listed by file with site count. All confirmed via grep.

| File | Sites | Notes |
|---|---|---|
| `app/memory/db_memory.py` | 10 | `save_fact`, `search_similar`, `get_facts_by_session`, `count_facts`, decay fetchers |
| `app/db/models.py` | 15 | `get_memory_state`, `switch/rename/delete_session`, `get_chat_history`, `add_message`, etc. |
| `app/db/models_async.py` | 20 | async mirrors of models.py |
| `app/memory/memory.py` | 10 | fence mechanism, pipeline triggers, review |
| `app/memory/retrieval.py` | 10 | `retrieve_dynamic_memories`, `retrieve_segments`, `retrieve_memory` (+async) |
| `app/db/facade.py` | 15 | **incl. `_resolve_session_id(...) -> int` → `-> uuid.UUID`** (lines 110, 118) |
| `app/memory/summarization.py` | 3 | |
| `app/memory/memory_review.py` | 3 | |
| `app/memory/pcl.py` | 4 | |
| `app/visual_context.py` | 2 | |
| `app/services/session_service.py` | 5 | `_bootstrap_memory`, `_auto_name_from_history` |
| `app/stream_manager.py` | 4 | `StreamBuffer` ctor, `get_stream`, `_cleanup_stream` |
| `app/services/memory_service.py` | 5 | |
| `app/llm_client.py` | 3 | `generate_ai_response(_streaming)` |
| `app/prompts.py` | 5 | `_mark_facts_pending_async`, `_session_events_block_async`, `build_*_context` |
| `app/orchestrator.py` | 15 | incl. fence `acquire(session_id, user_msg_id)`, `complete`, `is_completed` (lines 771, 805, 836) |
| `app/commands.py` | 1 | |
| `app/tools/db_query.py` | 1 | passthrough signature |
| `app/tools/fs_operations.py` | 6 | passthrough signatures (mostly unused for DB) |
| `app/tools/python_exec.py` | 1 | passthrough |
| `app/tools/shell_exec.py` | 1 | passthrough |

**`after_message_id: int` / `message_id: int` / `user_msg_id: int` stay INTEGER** — message-row
ids are still SERIAL. Do NOT change these (models.py:350, models_async.py:368/394, facade.py:230/236,
orchestrator.py:771 `user_msg_id`, memory.py:326 `last_message_id`).

---

## G. Profile id handling

| File | Line | Current | Required |
|---|---|---|---|
| `app/db/queries.py` | 230 | `parse_profile_row`: `"id": row.get("id")` | No code change — now returns `uuid.UUID`. Callers must not assume int. |
| `app/services/config_service.py` | 91 | `"id": profile["id"]` | Verify JSON-serializable in response. FastAPI `jsonable_encoder` handles `uuid.UUID` natively — likely OK, verify. |
| `DEFAULT_PROFILE_PARAMS` / `build_profile_update` / `SQL_PROFILE_INSERT_DEFAULT` | — | — | **UNCHANGED** (id is auto-generated, not in params). |

---

## H. `create_session` return type

| File | Line | Current | Required |
|---|---|---|---|
| `app/db/models.py` | 206 | `def create_session(...) -> int \| None` | `-> uuid.UUID \| None` |
| `app/db/models_async.py` | 169 | `async def create_session_async(...) -> int \| None` | `-> uuid.UUID \| None` |

Both `return row.get("id")` — now returns `uuid.UUID` (logic unchanged, annotation only).

---

## Decision points for review

1. **Runtime type**: `uuid.UUID` (recommended, type-safe, psycopg-native) vs `str` everywhere
   (simpler JSON, needs `::uuid` casts in some SQL)?
2. **metadata legacy gap** (§B): Option A (one-time metadata migration int→UUID + text comparison,
   recommended) vs B (text comparison only, accept legacy invisibility) vs C (dual-condition query)?
3. **Frontend scope** (§E): include `router.js` parseInt fix in this pass? It's a hard blocker for
   URL session routing — recommend YES.
4. **Implementation order**: propose (1) SCHEMA_DDL, (2) metadata cast + serialization, (3)
   annotations + return types, (4) API validators, (5) frontend parseInt — commit after each
   for rollback safety. Confirm or reorder.

---

## Verification plan (post-implementation, pre-push)

```bash
ruff check .                                    # Python lint
python3 -m py_compile $(git diff --name-only HEAD~1 | grep '\.py$')   # compile changed
npx @biomejs/biome check static/js/modules/router.js static/js/sidebar.js  # JS lint
python3 -m pytest tests/ -v                     # test suite
```

Plus a live smoke test: create a session via the web UI, send a message, confirm the SSE stream +
history render with a UUID session_id in the URL.
