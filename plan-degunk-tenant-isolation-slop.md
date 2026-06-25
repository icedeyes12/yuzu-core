# Plan: Degunk `origin/master...dev` — Tenant-Isolation Slop Removal

Base: `origin/master...dev` (39 commits, 74 files). Scope: Tier 1 (auth + orchestrator), Tier 2 (db/memory/core), Tier 3 (templates/CSS/JS + test_tenant_isolation). No other branches.

---

## Open Questions

1. **`get_session_memory` false scoping** — `SQL_SESSION_MEMORY_NOTES` queries `messages` (which has a `user_id` column) but filters by `session_id` only. The `user_id` param is accepted but ignored. Proposal below adds `AND user_id = %s`. Alternative: drop the param entirely (honest minimal). **Which do you prefer — proper scoping or honest param removal?** Plan assumes proper scoping.

2. **`invalidate_fact` (sync) is dead** — zero call sites; only the async variant is called (`pcl.py`). The facade still proxies the sync version. Plan adds a `ValueError` guard for contract consistency. Alternative: remove the sync function + its facade proxy entirely. **Keep-and-guard, or remove?** Plan assumes keep-and-guard.

3. **`retrieve_memory` swallowed enforcement** — its try/except catches the `ValueError` from sub-functions, returning empty memory on `user_id=None` instead of failing. `retrieve_memory` has zero direct callers (only `retrieve_for_context` / `retrieve_memories_combined` are used, both from `prompts.py` with a real `user_id`). Plan tightens it to re-raise on `None`. **Confirm this won't break a path you rely on?**

4. **`current_page` sidebar wiring** — `sidebar.html` uses `{% if current_page == 'home' %}active{% endif %}` but no route passes `current_page`, so active-link highlighting is silently dead. Plan wires it in `main.py` (routing/static-mounts change — allowed per AGENTS.md rule #8). **Confirm you want this fixed here, not deferred?**

---

## Task Checklist

### Phase 1 — Memory & data-layer tenant contract
- [x] 1.1 Unify `user_id` None-handling in `app/memory/db_memory.py` to a single `_require_user_id` guard (raise `ValueError`) across all fact functions
- [x] 1.2 Add `ValueError` guard to sync `invalidate_fact` (line 500) — match async variant
- [x] 1.3 Add `ValueError` guards to sync `search_similar` / `search_trgm` / `search_tsv` — match their async counterparts
- [x] 1.4 Add `ValueError` guard to `retrieve_segments` in `app/memory/retrieval.py` — match `retrieve_static_memories`
- [x] 1.5 Tighten `retrieve_memory` / `retrieve_memory_async` to validate `user_id` before try/except (re-raise instead of swallow)
- [x] 1.6 Scope `SQL_SESSION_MEMORY_NOTES` by `user_id` in `app/db/queries.py`; thread the param through `get_session_memory` / `get_session_memory_async` in `app/db/models.py` + `models_async.py` + `facade.py`
- [x] 1.7 Remove dead `SQL_SESSION_OWNERSHIP_CHECK` from `app/db/queries.py` (definition + `__all__` entry)
- [x] 1.8 Fix missed `user_id` in `api_delete_session` — `app/api/endpoints/sessions.py` line ~166
- [x] 1.9 Normalize f-string logging → `%s` lazy in `app/memory/db_memory.py` (diff-introduced lines only)
- [x] 1.10 Update `tests/test_tenant_isolation.py`: move `SQL_SESSION_MEMORY_NOTES` out of `MESSAGE_SESSION_EXEMPTIONS`; add test asserting `retrieve_memory(user_id=None)` raises
- [x] 1.11 Lint: `ruff check .` + `python3 -m py_compile` on all changed files; commit

### Phase 2 — Core path cleanup (orchestrator + auth endpoint)
- [x] 2.1 Remove redundant `parse_tool_blocks(synthesis)` at `app/orchestrator.py` line 619 (reuse `clean_synth` from line 602)
- [x] 2.2 Remove over-defensive `user_id` fallback in `_post_turn_async` — `app/orchestrator.py` lines 418–421
- [x] 2.3 Normalize diff-introduced f-string logging → `%s` lazy in `app/orchestrator.py` (line 589 + any others added in this diff)
- [x] 2.4 Extract duplicated display_name persistence into a single helper in `app/api/endpoints/auth.py`; move the inline `from app.db.queries import build_profile_update` to module top
- [x] 2.5 Move the `f"{q} WHERE id = %s"` SQL fragment into `app/db/queries.py` as a constant (or extend `build_profile_update` to include the WHERE clause); remove f-string SQL from `auth.py` lines 156 + 183
- [x] 2.6 Genericize `_require_env` error — log var name internally, return generic `"Configuration error"` to client
- [x] 2.7 Lint: `ruff check .` + `py_compile`; commit

### Phase 3 — Frontend security + CSS + template wiring
- [x] 3.1 Add HTML-escape helper to `static/js/sidebar.js`; apply to `display_name`, `email`, `avatar_url` in `_renderAuthenticated` (XSS fix)
- [x] 3.2 Use `json.dumps` for the SSE error payload in `_keyring_scoped_stream` — `app/api/endpoints/chat.py`
- [x] 3.3 Remove dead CSS in `static/css/sidebar.css` — first `.auth-user` block, `.auth-user-id`, first `.auth-logout-btn` definition
- [x] 3.4 Wire `current_page` context var in `main.py` route handlers (home/chat/config/about)
- [x] 3.5 Lint: `npx @biomejs/biome check static/js/`; commit

---

## Phase 1 — Memory & data-layer tenant contract

### Affected files
- `app/memory/db_memory.py` — unify `user_id` guard strategy; add guards to sync functions missing them
- `app/memory/retrieval.py` — guard `retrieve_segments`; tighten `retrieve_memory` entry points
- `app/db/queries.py` — scope `SQL_SESSION_MEMORY_NOTES` by `user_id`; remove dead `SQL_SESSION_OWNERSHIP_CHECK`
- `app/db/models.py` — thread `user_id` into `get_session_memory`
- `app/db/models_async.py` — thread `user_id` into `get_session_memory_async`
- `app/db/facade.py` — forward `user_id` to `get_session_memory(_async)`
- `app/api/endpoints/sessions.py` — fix missed `user_id` in `api_delete_session`
- `tests/test_tenant_isolation.py` — update exemptions + add entry-point guard test

### Changes

**1.1–1.3 Unify the `user_id` contract in `db_memory.py`.** The module currently has three None-handling strategies: `save_fact` logs+returns-None, ~8 functions `raise ValueError`, and `invalidate_fact`/`search_similar`/`search_trgm`/`search_tsv` (sync) have no guard at all. Introduce a module-private `_require_user_id(func_name: str, user_id: str | None) -> None` helper (mirrors the facade's `_require_user_id` but raises `ValueError` to match the existing memory-layer convention) and call it at the top of every public fact function. Replace the ad-hoc `if not user_id: raise ValueError(...)` blocks with calls to it. Convert `save_fact`/`save_fact_async` from log+return-None to the same `ValueError` — a missing `user_id` is a programming error, not a recoverable condition.

**1.4–1.5 Retrieval layer.** Add `_require_user_id` guard to `retrieve_segments`. In `retrieve_memory` / `retrieve_memory_async`, validate `user_id` *before* the try/except block so a `None` raises immediately instead of being caught and swallowed into empty memory. The existing try/except around the sub-retrievals stays (it guards against DB errors during retrieval), but it no longer masks the contract violation.

**1.6 Scope `SQL_SESSION_MEMORY_NOTES`.** The query currently is:
```sql
SELECT content, role, timestamp
FROM messages
WHERE session_id = %s AND role IN ('system', 'memory')
ORDER BY timestamp DESC LIMIT 50
```
Add `AND user_id = %s` and reorder params to `(session_id, user_id)`. Update `get_session_memory` / `get_session_memory_async` signatures to `(*, user_id: str)` keyword-only (matching the facade pattern) and pass `user_id` into the query. The `get_session_memory` callers in `endpoints/sessions.py`, `endpoints/profile.py`, `endpoints/memory.py`, and `prompts.py` already pass `user_id` — verify each call site matches the new keyword-only signature.

**1.7 Remove `SQL_SESSION_OWNERSHIP_CHECK`.** Defined at `queries.py:429`, exported in `__all__:911`, zero usages anywhere. Delete both.

**1.8 Fix `api_delete_session`.** At `sessions.py` ~line 166, the post-delete refresh calls `get_session_memory_async(active_session["id"])` without `user_id` while the sibling `get_chat_history_async` call does pass it. Add `user_id=user_id`.

**1.9 Logging.** Convert diff-introduced `logger.error(f"...")` / `logger.debug(f"...")` / `logger.exception(f"...")` calls in `db_memory.py` to `%s` lazy formatting to match the module's existing `logger.error("save_fact failed: %s", e)` style.

### Unit tests
- **Update `test_tenant_isolation.py`**: Remove `"SQL_SESSION_MEMORY_NOTES"` from `MESSAGE_SESSION_EXEMPTIONS` (it's now scoped). The static guardrail test (`test_guardrail_new_constants_need_user_id_or_exemption`) will then enforce it automatically.
- **Add `test_retrieve_memory_rejects_none_user_id`**: `with pytest.raises(ValueError): retrieve_memory(SESSION_A, user_id=None)` and the async variant. This closes the false-confidence gap — the existing `test_memory_functions_reject_missing_user_id` only tests sub-functions, not the entry point that previously swallowed the error.
- **Add `test_invalidate_fact_sync_rejects_none_user_id`**: `with pytest.raises(ValueError): invalidate_fact(1, None)`.

---

## Phase 2 — Core path cleanup (orchestrator + auth endpoint)

### Affected files
- `app/orchestrator.py` — remove redundant parse, dead defensive guard, normalize logging
- `app/api/endpoints/auth.py` — dedup display_name persistence, remove inline imports + f-string SQL, genericize env error
- `app/db/queries.py` — add SQL constant for the profile-update-by-id query

### Changes

**2.1 Redundant `parse_tool_blocks`.** At `orchestrator.py:602`, the loop body calls `next_commands, clean_synth = parse_tool_blocks(synthesis)`. At line 619, `_, clean_synth = parse_tool_blocks(synthesis)` re-parses the same string — `clean_synth` is already bound from line 602. Delete line 619; the `if clean_synth and clean_synth.strip():` block at 620 already uses the variable from 602. (Line 658 is a separate tail-cleanup path after the loop exits — leave it; it needs its own parse since `synthesis` may have changed across iterations.)

**2.2 Dead defensive guard.** `_post_turn_async` signature is `(*, user_id: str)` — keyword-only, non-optional. Lines 418–421 do `if not user_id: user_id = profile.get("id")` + `if not user_id: log.warning(...); return`. All callers (`handle_user_message`, `handle_user_message_streaming`, `_run_orchestration_loop_async`, `_finalize_and_persist_async`) pass a real `user_id`. Delete the fallback; if a caller ever passes empty, the type contract is violated and should fail loud, not silently degrade.

**2.3 Logging.** Convert diff-introduced f-string logs in `orchestrator.py` to `%s` lazy. Primary target: line 589 `log.info(f"[stream] fence {fence_id} completed (final synthesis)")` → `log.info("[stream] fence %s completed (final synthesis)", fence_id)`. Sweep any other f-string logs added in this diff (not pre-existing ones).

**2.4–2.5 Auth endpoint dedup + SQL invariant.** `_map_identity_to_profile` has two near-identical blocks (lines 148–157 for existing profiles, 175–184 for new profiles) that each do: inline-import `build_profile_update`, build query, f-string-append `WHERE id = %s`, execute. Extract a private `_persist_display_name(user_id, display_name)` helper that encapsulates the whole operation. Move `from app.db.queries import build_profile_update` to the module-top import block. Move the `f"{q} WHERE id = %s"` construction into `queries.py` — either extend `build_profile_update` to return the full statement including `WHERE id = %s`, or add a `SQL_PROFILE_UPDATE_BY_ID` wrapper constant. The endpoint must not construct SQL strings.

**2.6 `_require_env` exception exposure.** Currently raises `HTTPException(500, detail=f"Missing env var: {name}")` — leaks the env var name to the client. Change to: `log.error("Missing required env var: %s", name)` then `raise HTTPException(500, detail="Server configuration error")`.

### Unit tests
- **No new test file needed.** The orchestrator changes are pure deletion of redundant/dead code — existing behavior is preserved. Verify with `python3 -m py_compile app/orchestrator.py` and the existing `tests/test_commands.py` (tool-block parsing).
- **Add to `tests/test_tenant_isolation.py`** (or a new `tests/test_auth_helpers.py`): `test_require_env_generic_error` — monkeypatch `os.environ` to omit a var, call `_require_env`, assert the `HTTPException.detail` does not contain the var name.

---

## Phase 3 — Frontend security + CSS + template wiring

### Affected files
- `static/js/sidebar.js` — XSS escape in `_renderAuthenticated`
- `app/api/endpoints/chat.py` — `json.dumps` for SSE error payload
- `static/css/sidebar.css` — remove dead `.auth-user` / `.auth-user-id` / first `.auth-logout-btn`
- `main.py` — wire `current_page` context var

### Changes

**3.1 XSS escape.** `_renderAuthenticated` injects `data.display_name`, `data.email`, and `data.avatar_url` (from `/api/auth/me`, sourced from OAuth provider data) directly into `innerHTML` via template string. A malicious IdP returning `display_name: '<img src=x onerror=alert(1)>'` achieves script injection. Add a `_escapeHtml(str)` helper at the top of `sidebar.js`:
```js
function _escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = String(s ?? "");
  return d.innerHTML;
}
```
Wrap `showName`, `email` in `_escapeHtml()` wherever they appear in innerHTML (the text nodes and the `title=` attributes). For `avatarUrl`, validate it's an `https://` (or `http://`) URL before injecting into `src=` — reject anything with `javascript:` scheme. This is elevated priority because BYOK API keys live in `localStorage` and an XSS could exfiltrate them.

**3.2 SSE error JSON.** In `_keyring_scoped_stream` (`chat.py`), the error path hand-builds JSON via f-string: `f'data: {{"error": "missing_key", "provider": "{e.provider}", ...}}\n\n'`. Replace with `json.dumps`:
```python
import json
payload = json.dumps({"error": "missing_key", "provider": e.provider, "message": f"No API key for {e.provider}. Set your key in Settings → Provider Keys."})
yield f"data: {payload}\n\n"
```

**3.3 Dead CSS.** `sidebar.css` defines `.auth-user` twice. The first block (~line 700, with `.auth-user-id`, `justify-content: space-between`) is superseded by the second block (~line 880, with `.auth-user-info` / `.auth-user-meta`). The JS renders the second variant's classes — `.auth-user-id` is never used. Delete the first `.auth-user` block, `.auth-user-id`, and the first `.auth-logout-btn` definition.

**3.4 `current_page` wiring.** `sidebar.html` uses `{% if current_page == 'home' %}active{% endif %}` etc., but no route passes `current_page`, so active highlighting is dead. In `main.py`, add `"current_page": "home"` (resp. `"chat"`, `"config"`, `"about"`) to the context dict of each `TemplateResponse` call (lines 193, 203, 213, 223). This is a routing/static-mounts change — allowed per AGENTS.md rule #8.

### Unit tests
- Frontend changes are not unit-testable per AGENTS.md (no UI test framework). Verify with `npx @biomejs/biome check static/js/sidebar.js` and manual browser inspection of the auth widget.
- The `chat.py` SSE change: verify `json.dumps` output is valid by adding a focused assertion in an existing test or a new `tests/test_chat_sse.py` that imports the error-payload construction and asserts `json.loads(payload)` succeeds with expected keys.

---

## Notes

- `app/auth/oauth.py` and `app/core/context.py` were audited and found clean — no changes.
- `tests/test_tenant_isolation.py` is a legitimate anti-regression suite (static SQL inspection + mock multi-tenant integration). Kept and extended, not degunked.
- The `prompts.py` tool-documentation rewrite (CATEGORY 1/2 split) is a prompt change, not code slop — out of scope.
- Commit per phase with co-author trailer. Lint before each push (`ruff` for Python, `biome` for JS). Rollback if any phase introduces a regression.

### Changes

**1.1–1.3 Unify `user_id` guard in `db_memory.py`:** The module currently uses three incompatible None-strategies: `save_fact` logs+returns-None, ~8 functions `raise ValueError`, and `invalidate_fact` (sync) + `search_similar`/`search_trgm`/`search_tsv` (sync) have no guard at all. Introduce a module-private `_require_user_id(method: str, user_id: str | None) -> None` that raises `ValueError(f"{method}: user_id is required")` — mirroring the facade's `TenantScopeError` pattern. Apply it as the first line of every fact function that currently lacks a guard. Leave `save_fact`/`save_fact_async` as log+return-None (they're write paths where a soft skip is the documented behavior — changing to raise would alter the orchestrator's error contract).

**1.4 Guard `retrieve_segments`:** Add `if not user_id: raise ValueError("retrieve_segments: user_id is required")` as the first line, matching `retrieve_static_memories` / `retrieve_dynamic_memories`.

**1.5 Tighten `retrieve_memory` / `retrieve_memory_async`:** Currently the `try/except Exception` around `retrieve_static_memories` / `retrieve_dynamic_memories` catches the `ValueError` guard and silently returns empty memory. Add `if not user_id: raise ValueError("retrieve_memory: user_id is required")` *before* the try blocks so the guard is not swallowed. The try/except stays for genuine retrieval failures (DB errors), but the contract violation now propagates.

**1.6 Scope `SQL_SESSION_MEMORY_NOTES`:** Add `AND user_id = %s` to the WHERE clause. Update the call sites in `get_session_memory` (models.py) and `get_session_memory_async` (models_async.py) to pass `(session_id, user_id)`. The facade already accepts `user_id` and forwards it — no facade signature change needed, just ensure the param reaches the SQL. This closes the false-scoping gap that `test_tenant_isolation.py` currently exempts with a TODO.

**1.7 Remove `SQL_SESSION_OWNERSHIP_CHECK`:** Defined at `queries.py:429`, exported in `__all__` at line 911, never referenced anywhere in `app/`. Delete both the definition and the `__all__` entry.

**1.8 Fix `api_delete_session`:** At `sessions.py` ~line 166, `get_session_memory_async(active_session["id"])` is missing `user_id` while its sibling `get_chat_history_async(active_session["id"], user_id=user_id)` passes it. Add `user_id=user_id`.

**1.9 Logging:** Convert diff-introduced `logger.error(f"...")` / `logger.debug(f"...")` / `logger.exception(f"...")` to `%s` lazy format to match the module's dominant style. Only touch lines added/modified in this diff.

### Unit tests (Phase 1)

Update `tests/test_tenant_isolation.py`:
- **Remove `SQL_SESSION_MEMORY_NOTES` from `MESSAGE_SESSION_EXEMPTIONS`** — it's now scoped by `user_id`, so the static guardrail test will enforce it. If the scoping fix is applied, this exemption is no longer needed.
- **Add `test_retrieve_memory_rejects_missing_user_id`**: `with pytest.raises(ValueError): retrieve_memory(SESSION_A, user_id=None)` and the async variant. This closes the false-confidence gap — the existing `test_memory_functions_reject_missing_user_id` only tests sub-functions in isolation.
- **Add `test_get_session_memory_is_tenant_scoped`** (integration, uses `tenant_db` fixture): seed a memory note for Tenant_B's session, assert Tenant_A calling `get_session_memory_async(SESSION_B, TENANT_A)` returns empty (cross-tenant read blocked).
- **Add `test_sync_invalidate_fact_requires_user_id`**: `with pytest.raises(ValueError): invalidate_fact(1, user_id=None)` — mirrors the existing async test.
- Existing `TestStaticSQLScoping` tests should pass unchanged after removing the exemption (the guardrail test will now *enforce* that `SQL_SESSION_MEMORY_NOTES` contains `user_id`).

---

## Phase 2 — Core path cleanup (orchestrator + auth endpoint)

### Affected files
- `app/orchestrator.py` — remove redundant parse, dead defensive guard, normalize logging
- `app/api/endpoints/auth.py` — dedup display_name persistence, move SQL to queries.py, genericize env error
- `app/db/queries.py` — add scoped profile-update-by-id SQL constant

### Changes

**2.1 Remove redundant `parse_tool_blocks(synthesis)` at orchestrator.py:619:** The loop body already calls `next_commands, clean_synth = parse_tool_blocks(synthesis)` at line 602. Line 619 (`_, clean_synth = parse_tool_blocks(synthesis)`) re-parses the identical string to recover `clean_synth` that's already in scope. Delete line 619; the subsequent `if clean_synth and clean_synth.strip():` uses the value from line 602. (Line 658 is a separate tail-cleanup path after the loop exits — leave it, but it can reuse the last iteration's `clean_synth` if you want to optimize further; not required.)

**2.2 Remove over-defensive `user_id` fallback in `_post_turn_async` (lines 418–421):** The signature is `*, user_id: str` (required keyword-only). The body does `if not user_id: user_id = profile.get("id")` then `if not user_id: log.warning(...); return`. Since every caller (`handle_user_message`, `handle_user_message_streaming`, `_finalize_and_persist_async`, `_run_orchestration_loop_async`) now passes a real `user_id`, this fallback is dead defensive code that contradicts the type contract. Delete lines 418–421.

**2.3 Logging:** Convert diff-introduced `log.info(f"[stream] fence {fence_id} completed (final synthesis)")` (line 589) and any other f-string logs added in this diff to `%s` lazy format: `log.info("[stream] fence %s completed (final synthesis)", fence_id)`. Pre-existing f-string logs (lines 490, 688, 1042, etc.) are out of scope — don't touch unchanged code.

**2.4 Dedup display_name persistence in `auth.py`:** The block `from app.db.queries import build_profile_update; q, params = build_profile_update({"display_name": display_name}) or ("", []); if q: params.append(user_id); await pg_execute_async(f"{q} WHERE id = %s", params)` is duplicated at lines 151–156 (existing-profile branch) and 178–183 (new-profile branch). Extract to a module-private `async def _persist_display_name(user_id: str, display_name: str) -> None`. Move the `build_profile_update` import to the module top (anti-pattern #27 — misplaced inline import). Call the helper from both branches.

**2.5 Move SQL to `queries.py`:** The `f"{q} WHERE id = %s"` construction at auth.py:156 + 183 violates AGENTS.md invariant #4 ("db_queries.py owns all SQL"). Add a constant to `queries.py`: `SQL_PROFILE_UPDATE_DISPLAY_NAME = "UPDATE profiles SET display_name = %s, updated_at = %s WHERE id = %s"`. Use it directly in the helper from 2.4 — this eliminates both the `build_profile_update` call and the f-string SQL. (If you prefer the generic `build_profile_update` path, extend it to optionally append a WHERE clause in `queries.py` instead of `auth.py`.)

**2.6 Genericize `_require_env`:** Currently `raise HTTPException(status_code=500, detail=f"Missing env var: {name}")` leaks the env var name to the client. Change to: `log.error("Missing required env var: %s", name); raise HTTPException(status_code=500, detail="Server configuration error")`.

### Unit tests (Phase 2)

- **`tests/test_orchestrator.py` (new or existing):** Add `test_post_turn_async_rejects_no_user_id` — mock dependencies, call `_post_turn_async(profile, "msg", "resp", session_id, active_session, user_id="")`, assert it raises (not silently returns). This locks in the removal of the defensive fallback — a falsy user_id must fail loud, not silently skip the memory pipeline.
- **`tests/test_auth.py` (new):** Add `test_require_env_generic_error` — call `_require_env("NONEXISTENT_VAR")`, assert `HTTPException` with `detail == "Server configuration error"` (not the var name). Add `test_persist_display_name_uses_scoped_sql` — mock `pg_execute_async`, call `_persist_display_name`, assert the SQL constant passed is `SQL_PROFILE_UPDATE_DISPLAY_NAME` (no f-string construction).

---

## Phase 3 — Frontend security + CSS + template wiring

### Affected files
- `static/js/sidebar.js` — XSS escape in `_renderAuthenticated`
- `app/api/endpoints/chat.py` — `json.dumps` for SSE error payload
- `static/css/sidebar.css` — remove dead/duplicated CSS
- `main.py` — wire `current_page` context var

### Changes

**3.1 XSS fix in `sidebar.js`:** `_renderAuthenticated` injects `data.display_name`, `data.email`, `data.avatar_url` into `innerHTML` via template string without escaping. These come from OAuth provider data via `/api/auth/me`. Add a module-private escape helper:
```js
function _esc(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}
```
Apply `_esc()` to `showName` and `email` in the template string. For `avatarUrl`, validate it's an `http(s)` URL before injecting into `src=` (reject `javascript:` scheme). This is elevated priority because BYOK API keys live in `localStorage` — an XSS could exfil them.

**3.2 `json.dumps` for SSE error in `chat.py`:** `_keyring_scoped_stream` builds the error SSE with `f'data: {{"error": "missing_key", "provider": "{e.provider}", ...}}\n\n'`. If `e.provider` contains a quote, the JSON breaks. Replace with:
```python
import json
payload = json.dumps({"error": "missing_key", "provider": e.provider,
                      "message": f"No API key for {e.provider}. Set your key in Settings → Provider Keys."})
yield f"data: {payload}\n\n"
```

**3.3 Remove dead CSS in `sidebar.css`:** The first `.auth-user` block (with `justify-content: space-between` + `.auth-user-id`), the `.auth-user-id` rule, and the first `.auth-logout-btn` definition are all superseded by the later `.auth-user` block (with `.auth-user-info`, `.auth-user-meta`, etc.). The JS renders the second variant's classes — `.auth-user-id` is never emitted. Delete the first `.auth-user` + `.auth-user-id` + first `.auth-logout-btn` block.

**3.4 Wire `current_page` in `main.py`:** The four page routes (`home`, `chat_page`, `config_page`, `about_page`) call `templates.TemplateResponse(request=request, name=..., context={...})`. Add `"current_page": "home"` / `"chat"` / `"config"` / `"about"` to each context dict. This is a routing/static-mount change — allowed by AGENTS.md rule #8.

### Unit tests (Phase 3)

Frontend (vanilla JS, no test runner) and template wiring are not unit-tested per AGENTS.md frontend constraints. Verification is manual + lint:
- `npx @biomejs/biome check static/js/sidebar.js` — must pass.
- Manual: navigate to each page, confirm the sidebar highlights the active nav link (was silently broken).
- Manual: with a BYOK key in localStorage, inspect `/api/auth/me` response rendering — confirm no raw HTML executes if `display_name` contains `<script>`.

---

## Execution discipline (per your constraint #2)

- Each phase: lint → `py_compile` / `biome` → commit via `git co-author` → push only if lint passes clean.
- If a phase introduces a regression: `git revert` that phase's commit, re-approach narrower.
- Phase 1 is the foundation (tenant contract); Phase 2 (core path) stacks on it; Phase 3 (frontend) is independent.
