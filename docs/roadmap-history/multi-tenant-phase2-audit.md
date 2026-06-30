# Multi-Tenant Refactor — Post-Phase 2 Diagnostic Audit

> **Audited at:** `dev` @ `2f6e04d` (clean working tree, `ruff check .` green)
****Reference plan:** `file docs/multi-tenant-refactor-plan.md`
****Mode:** Read-only audit. No code patches written or submitted.
****Scope:** Profile data lifecycle · Template surface area · Plan reconciliation.

## Executive Summary

Phases 1 and 2 are **structurally complete and verified**: UUID migration landed (post-cutover `SCHEMA_DDL`), OAuth2 (Google + GitHub) + server-side sessions are wired, and every `/api/*` handler carries `Depends(get_current_user)` (35/35).

The rot is concentrated in two places:

1. **The server-rendered HTML page layer was never brought into the multi-tenant model.** `file main.py`'s four page routes are *unauthenticated* and call `Database.get_profile_async()` with **no** `user_id`, silently falling back to `SELECT * FROM profiles LIMIT 1`. This leaks the first tenant's `display_name` / `partner_name` / `affection` into every visitor's page, including other authenticated tenants.
2. **Phase 4 isolation is opt-in, not enforced.** `user_id` is `str | None = None` everywhere (facade, `models_async`, orchestrator). Scoped SQL exists, but every tenant method keeps an **unscoped fallback** to the old `LIMIT 1` / global queries. Forgetting to pass `user_id` produces a silent cross-tenant read, not a `TypeError`. The plan's 4.1 "required parameter" and 4.4 "anti-regression guardrail" are both unimplemented.

Phase 3 (BYOK) is **half done**: the *additive* path works (ContextVar + frontend interceptor + chat-endpoint keyring binding), but the *decommission* half is entirely missing — `api_keys` is not purged, `file base.py` still falls back to DB keys, and three orphaned key-write endpoints remain live.

---

## Vector 1 — Profile Data Lifecycle

### 1.1 CRITICAL — Page routes leak the first tenant's profile (unauthenticated + unscoped)

`file main.py` lines 189–225:

```python
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    profile = await Database.get_profile_async()   # no user_id, no Depends
    return templates.TemplateResponse(..., context={"profile": profile})
# /chat, /config, /about identical
```

- No `Depends(get_current_user)`. Routes are **public**.
- `get_profile_async(None)` → `SQL_PROFILE_SELECT_FIRST` = `SELECT * FROM profiles LIMIT 1` (`file app/db/models_async.py` L113–117, `file app/db/queries.py` L285).
- Effect: `{{ profile.display_name }}`, `{{ profile.partner_name }}`, `{{ profile.affection }}` in `file index.html` / `file chat.html` / `file config.html` always render **User #1's** companion identity to every visitor. `/chat` header shows User #1's partner name; `/config` pre-fills User #1's profile fields.
- `chat_page` also runs legacy single-tenant bootstrapping: `SessionService.start_session(interface="web")` + `_get_session_id()` (host+UA hash — the dedup-only identifier the plan A.3 explicitly flags as "not auth"), and contains `print()` statements (violates AGENTS.md §2 rule 6).
- Git history confirms the page routes were **never touched** by the refactor — last `file main.py` change was the `web.py → main.py` rename, pre-Phase-1.

### 1.2 HIGH — `ConfigService` ignores `user_id` entirely

`file app/services/config_service.py`: every method calls `Database.get_profile_async()` / `Database.get_profile()` with **no** `user_id`, even though the endpoints that invoke them accept `user_id` via `Depends` and drop it:

- `get_frontend_config()` → `get_profile_async()` (called by `GET /api/config`, `file app/api/endpoints/profile.py` L74 — `user_id` accepted, not forwarded)
- `get_ai_providers_payload(profile=None)` → `get_profile_async()` when profile is None
- `get_vision_payload(profile=None)` → **sync** `Database.get_profile()` (no async, no user_id)
- `set_preferred_provider` / `set_vision_model` (sync) and `set_preferred_provider_async` / `set_vision_model_async` → `get_profile_async()` / `update_profile_async()` with **no user_id**

Net: `POST /api/providers/set_preferred` and `/providers/set_vision_model` mutate `profiles LIMIT 1` (User #1), not the authenticated caller's profile. A user "saving" their provider preference silently writes to the first tenant.

### 1.3 HIGH — `get_chat_history_async` called without `user_id` in two endpoints

- `file app/api/endpoints/profile.py` L98 (`api_get_profile`): `get_chat_history_async(session_id=session_id, limit=None)` — no `user_id`. Plan 4.2 requires `WHERE session_id=%s AND user_id=%s`.
- `file app/api/endpoints/memory.py` L25 (`api_update_session_context`): same omission.

`session_id` is now UUID (hard to guess), so this is defense-in-depth rather than an open leak — but it is precisely the "stray session_id reuse can't cross tenants" guarantee the plan 4.2 demands, and it is missing.

### 1.4 MEDIUM — Memory rebuild/decay not user-scoped

`file app/api/endpoints/memory.py`:

- `api_rebuild_structured_memory` (L84) → `MemoryService.rebuild_structured_memory_async(session_id)` — signature has **no** `user_id` (`file app/services/memory_service.py` L133).
- `api_run_memory_decay` (L106) → `run_decay_async(session_id)` — **no** `user_id` (`file app/memory/review.py` L80). Plan 4.3 explicitly requires `UPDATE semantic_facts … WHERE id=%s AND user_id=%s`.

Inconsistent within the same file: `api_memory_stats` (L127) and `api_update_global_profile` (L65) **are** correctly user-scoped. This is the textbook 4.4 "forget to scope" footgun, and there is no guardrail catching it.

### 1.5 Data-contract note (verified OK)

`ConfigService.format_profile_dict` accesses `profile["image_model"]` / `profile["vision_model"]` as required keys. Verified against `SCHEMA_DDL` (`file app/db/queries.py` L141–142): both columns exist with defaults, and `parse_profile_row` (L401–402) maps them. No `KeyError` risk. The `memory_state`→`memory` aliasing is consistent. This contract is sound.

### 1.6 Infrastructure/permission gaps

- **Static asset routes are unauthenticated** (`file app/api/static.py`): `/static/uploads/{filename}` and `/static/generated_images/{filename}` have no `Depends(get_current_user)`. Path-traversal protection is present, but in a multi-tenant deployment any tenant can fetch another's uploaded/generated images by filename. Not addressed by the plan.
- **No DB connectivity was tested in this audit** (out of scope, no live DB). Schema state is inferred from `SCHEMA_DDL` + plan live-run notes, which agree.

---

## Vector 2 — Template Surface Area

### 2.1 CRITICAL — `file about.html` is a legacy single-tenant museum with false tech claims

`file templates/about.html` "Tech Stack" section asserts:

- **"Flask — Simple web framework"** — false. AGENTS.md: "No Flask — FastAPI only."
- **"SQLite — Lightweight database"** — false. AGENTS.md: "No SQLite — PostgreSQL only, with pgvector." The entire refactor is PostgreSQL-bound.
- **"Tailwind CSS — Modern utility-first CSS"** — false. Frontend is vanilla CSS, no framework.
- "Hikikimo Life initiative", "second project… abandoned", "©2025" — stale personal narrative + wrong year.

This page is served unauthenticated (see 1.1) and actively misrepresents the stack to every visitor.

### 2.2 HIGH — `file chat.html` loads Tailwind via CDN

`file templates/chat.html` L9: `<script src="https://cdn.tailwindcss.com"></script>`. AGENTS.md §9 rule 1: "No build step — Vanilla JS/ESM only. No bundlers, no npm, no framework." The Tailwind CDN is a runtime framework injection that violates the buildless constraint — and it contradicts `file about.html`'s *claim* that Tailwind is used (about.html is wrong, chat.html is the actual violation). Inconsistent and non-compliant.

### 2.3 MEDIUM — Hardcoded legacy UI blocks across all four templates

- **Duplicated sidebar ×4**: `file index.html`, `file chat.html`, `file config.html`, `file about.html` each carry an inline copy of the full sidebar (Navigation + 9-option Theme dropdown + Sessions section). \~120 lines duplicated four times. The `serve_sidebar` route (`file main.py` L229) tries to load a `file templates/sidebar.html` that **does not exist** → always falls back to a hardcoded inline string. Dead route + duplicated surface.
- **Hardcoded image-model options** (`file config.html`): `<option value="z_turbo">` / `<option value="qwen_image">` — not driven by config, drifts from the DB default `hunyuan` (`SCHEMA_DDL` L141) and `file config.js`'s `data.image_model || "qwen_image"` fallback.
- **Single-tenant Jinja binding**: `{{ profile.display_name|capitalize }}` (index), `{{ profile.partner_name }}` / `{{ profile.affection }}` (chat, config) — all rely on the leaking page-route injection (1.1).
- **Legacy "All Sessions" wording** (`file config.html`): "Comprehensive profile from ALL sessions", "persist across all sessions", "analyze ALL sessions" — single-tenant framing that is now ambiguous (should mean "all of *this user's* sessions"). Backend is per-user via `profiles.memory` / `global_knowledge`, but the labels read as global.
- **Stale copyright**: `©2025 hkkm project` in `file index.html`, `file about.html`, `file config.html` footers (now 2026).
- **Inconsistent** `lang`: `file chat.html` is `lang="id"`, the other three are `lang="en"`.

### 2.4 The auth widget is NOT in the templates (by design) — verified present

The login/logout/identity widget is **JS-injected** by `file static/js/sidebar.js` (createElement `authSection`, calls `/api/auth/me`, renders Google/GitHub login or avatar+Sign Out). So the four static sidebars correctly omit it. This is the one part of the frontend that *is* multi-tenant-correct. (Caveat: it only renders if `file sidebar.js` runs and the sidebar DOM node exists — true on all four pages.)

### 2.5 Orphaned/secondary templates (out of named scope, noted for completeness)

- `file multimodal_chat.html` and `file offline.html` are referenced by `file main.py` (offline.html = DB-offline fallback handler; multimodal_chat.html = served by a route outside the four audited). Not orphaned, but not audited here. `file templates/sidebar.html` (referenced by `serve_sidebar`) **is** orphaned — does not exist on disk.

---

## Vector 3 — Plan Reconciliation

| Plan item | Status | Evidence |
| --- | --- | --- |
| **Phase 1 — UUID migration** | ✅ DONE | Post-cutover `SCHEMA_DDL` (`file queries.py` L103–249): UUIDv7 PKs, `user_id` FKs on `chat_sessions`/`messages`/`semantic_facts`, `user_identities` + `user_sessions` tables, `generate_uuidv7()` fn. Matches plan 1.7 completion notes. |
| **Phase 2.1–2.3 — OAuth + session tables** | ✅ DONE | `file app/auth/oauth.py` (Google OIDC + GitHub, PKCE state cookie, JWKS), `file app/auth/session.py` (`yuzu_session` cookie, `create_session`/`validate_session`/revoke), `file auth.py` (`/login` `/callback` `/logout` `/me` + `_map_identity_to_profile` provisioning). Both providers day-one per plan. |
| **Phase 2.4 — Protect every router** | ✅ DONE (per-handler) | 35/35 handlers carry `Depends(get_current_user)`. **Deviation:** done per-handler, not via router-level `dependencies=[...]` — easier to miss on a new handler. |
| **Phase 2.5 — Verify gate** | ⚠️ Not re-verified here | No live DB; runtime login loop not tested in this audit. |
| **Phase 3.1 — Purge** `api_keys` | ❌ NOT DONE | No `UPDATE api_keys SET key_value=NULL` anywhere. `api_keys` table still holds encrypted keys. |
| **Phase 3.2 — Backend per-request key (ContextVar)** | 🟡 PARTIAL | `file app/core/context.py` RequestKeyring + `resolve_api_key` ✅; `file chat.py` reads `X-Provider-Key`/`X-Provider-Name` and `set_request_keyring` on all 3 LLM endpoints (streaming scoped inside generator ✅); providers consult ContextVar ✅. **BUT** `base.py:226` still falls back to `get_api_key_async` (DB) — "No DB key read remains" gate **not met**. Done as per-endpoint code, not the plan's middleware. `test_connection`/`test_vision` do **not** honor BYOK. |
| **Phase 3.2 — Remove key endpoints** | ❌ NOT DONE | `POST /api/add_api_key`, `/add_chutes_key`, `/remove_api_key` still live (`file profile.py` L145/158/175), still write to DB. Frontend UI removed (config.js L257 "DECOMMISSIONED" comment) → endpoints are **orphaned but writable**. |
| **Phase 3.2 — Remove** `get_api_keys()` **calls** | ❌ NOT DONE | `ConfigService.get_vision_capabilities` still calls `get_api_keys()` to derive image-gen availability (`file config_service.py`). |
| **Phase 3.3 — Frontend BYOK (LocalStorage + interceptor)** | ✅ DONE | `file config.js` `yuzu_byok_config` localStorage save/load; `file sidebar.js` fetch interceptor injects `X-Provider-Key` on `/send_message`, `/send_message_stream`, `/generate_image`. |
| **Phase 3.4 — Verify gate** | ❌ FAILS | DB holds keys, DB key-read path remains, key endpoints remain. Zero-trust not achieved; BYOK is additive, not replacing. |
| **Phase 4.1 —** `user_id` **required first param** | ❌ NOT DONE | `user_id: str | None = None` (optional) on every facade method, `models_async` function, and orchestrator entrypoint. Forgetting it is a silent leak, not a `TypeError`. |
| **Phase 4.2 — Per-table scoping** | 🟡 PARTIAL | Scoped SQL exists (`SQL_PROFILE_SELECT_BY_ID`, `SQL_SESSION_SELECT_ACTIVE_FOR_USER`, `SQL_SESSION_*_SCOPED`). **But** `SQL_PROFILE_SELECT_FIRST` (L285) still exists + exported + used as fallback (plan says DELETE). Unscoped fallbacks remain in `get_profile_async`/`get_active_session_async`/`get_all_sessions_async`/`switch`/`rename`/`delete`/`create_session_async`. `get_chat_history_async` not scoped at 2 call sites (1.3). |
| **Phase 4.3 — Memory-guardian per-user** | ❌ NOT DONE | `run_decay_async(session_id)` and `rebuild_structured_memory_async(session_id)` have no `user_id`. Weekly Memory Review automation not updated to per-user iteration (decay primitive itself unscoped). |
| **Phase 4.4 — Anti-regression guardrails** | ❌ NOT DONE | No `file tests/test_tenant_isolation.py`. No runtime `TenantScopeError` in facade. |
| **Phase 4.5 — Verify gate** | ❌ FAILS | No isolation tests; unscoped fallbacks present; page routes leak. |

### Doc drift (bonus)

- AGENTS.md §1 key-files table lists `file app/web.py` as the entry point. **Actual:** `file main.py` at repo root (renamed in `4487a7e`). `file app/web.py` does not exist.
- AGENTS.md header says "raw psycopg2". **Actual:** `psycopg[binary,pool]>=3.1` (v3). Already flagged by plan A.1; still unfixed in AGENTS.md.

---

## Roadmap — Next Logical Steps (ordered, no code yet)

The plan's prescribed critical path is `0 → 1 → 2 → 4 → 3`. Phases 1–2 are done. Phase 4 is the gate that makes the app actually multi-tenant; Phase 3's decommission half is cleanup that becomes *safe* only after 4 stops the fallbacks. Recommended sequence:

### Step 1 — Close the page-route leak (highest urgency, smallest blast radius)

Make `/`, `/chat`, `/config`, `/about` require `Depends(get_current_user)` and pass `user_id` into `get_profile_async(user_id)`. This is the only finding that leaks tenant data to *unauthenticated* visitors today. Decide policy: redirect unauthenticated users to login, or render a public shell. Either way, `LIMIT 1` must go from the render path.

### Step 2 — Make `user_id` required (Phase 4.1)

Flip `user_id: str | None = None` → `user_id: str` (required, no default) on: `Database` facade tenant methods, `models_async` tenant functions, `MemoryService`/`orchestrator` entrypoints. Delete the unscoped `else:` fallback branches in `get_profile_async` / `get_active_session_async` / `get_all_sessions_async` / `switch` / `rename` / `delete` / `create_session_async`. Remove `SQL_PROFILE_SELECT_FIRST` + its export. Run `ruff` + `py_compile` + `pytest` — every missed call site becomes a loud `TypeError`, which is the point.

### Step 3 — Thread `user_id` through the gaps surfaced by Step 2

Step 2 will hard-fail on exactly the call sites that are currently leaking: `ConfigService` (all methods), `get_chat_history_async` in `file profile.py` + `file memory.py`, `rebuild_structured_memory_async` + `run_decay_async`, the page routes. Fix each by forwarding the authenticated `user_id`. This is mechanical once Step 2 makes silence impossible.

### Step 4 — Add the Phase 4.4 guardrails (so it stays fixed)

- `file tests/test_tenant_isolation.py`: static parse of `file queries.py` + `file db_memory_queries.py` asserting every tenant-scoped statement binds `user_id`; integration test seeding two users and asserting no cross-user reads.
- Runtime `TenantScopeError` in the facade for falsy `user_id` (defense-in-depth behind the type change).

### Step 5 — Finish Phase 3 decommission (now safe)

- Purge `api_keys` (`UPDATE … SET key_value=NULL, key_encrypted=FALSE`) — after confirming no live caller depends on DB keys.
- Remove the DB fallback in `base.py._load_api_key`; raise `MissingProviderKeyError` when the ContextVar is empty → endpoint maps to 401/424.
- Delete `/add_api_key`, `/add_chutes_key`, `/remove_api_key` endpoints + their facade methods.
- Replace `get_api_keys()` in `ConfigService.get_vision_capabilities` with request-plane availability.
- Extend BYOK header binding to `test_connection` / `test_vision` (or document them as non-BYOK).

### Step 6 — Template cleanup (low risk, do last)

- Rewrite/replace `file about.html` tech stack (remove Flask/SQLite/Tailwind falsehoods).
- Remove Tailwind CDN from `file chat.html`.
- Extract the duplicated sidebar into a single shared partial (or make `serve_sidebar` + `file templates/sidebar.html` real) and drop the 4 inline copies.
- Drive image-model options from config; fix "All Sessions" wording to "all of your sessions"; bump `©2025` → current year; align `lang`.

### Verification gates (per step)

- Steps 1–4: `ruff check .` · `py_compile` changed files · `pytest tests/` (incl. new isolation tests) · manual two-user cross-read check.
- Step 5: `SELECT key_value FROM api_keys` all NULL · `grep -r get_api_key app/` only inert refs · request without `X-Provider-Key` → 401/424.
- Step 6: `npx @biomejs/biome check static/js/` · visual pass on all four pages as two different users.

### Out-of-scope flags (do not block the above)

- Static-asset auth (`/static/uploads`, `/static/generated_images`) — real multi-tenant gap, not in the plan; schedule separately.
- AGENTS.md doc drift (`file web.py`→`file main.py`, psycopg2→v3) — fix alongside Step 6.
- Memory-guardian Weekly Memory Review automation — must move to per-user iteration before re-enabling (plan 4.3); coordinate with Step 4.