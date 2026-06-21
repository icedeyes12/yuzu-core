# Multi-Tenant Refactor Plan — yuzu-companion

> **Status:** DRAFT FOR REVIEW — no SQL executed, no implementation code written.
> **Scope:** UUID migration · OAuth2 · Strict client-side BYOK · Multi-tenant isolation.
> **Constraints:** raw psycopg v3 (async `AsyncConnectionPool` + sync `ConnectionPool`), FastAPI, no ORM, no new dependencies without approval, all SQL in `app/db/queries.py` + `app/memory/db_memory_queries.py`, all DB access via `Database` facade.
> **Date:** 2026-06-21

---

## Part A — Audit Findings (grounded in current code)

### A.1 DB adapter (corrects an AGENTS.md mislabel)
- `AGENTS.md` header says "raw psycopg2". **Actual:** `psycopg[binary,pool]>=3.1` (psycopg **v3**).
- `app/db/connection.py`: `from psycopg.rows import dict_row` + `AsyncConnectionPool, ConnectionPool` from `psycopg_pool`.
- Helpers: `PgSession`, `pg_fetchone`, `pg_fetchall`, `pg_execute` (sync) and `*_async` variants.
- **Implication:** migration SQL must use pgcrypto's `gen_random_uuid()` (PG13+); `pgvector` extension already present.

### A.2 Current schema (from `app/db/queries.py` `SCHEMA_DDL` + `app/memory/README.md`)
| Table | PK | Tenant column? | FKs |
|---|---|---|---|
| `profiles` | `id SERIAL` | — (is the tenant root) | none |
| `chat_sessions` | `id SERIAL` | **none** | none to profiles |
| `messages` | `id SERIAL` | **none** | `session_id INTEGER → chat_sessions(id) ON DELETE CASCADE` |
| `api_keys` | `id SERIAL` | **none** (global singleton) | none |
| `semantic_facts` | `id SERIAL` | **none** (only nullable `session_id INTEGER`, no FK constraint) | none explicit |

**Critical premise correction:** the request assumes `sessions`/`messages`/`semantic_facts` already FK to the integer `profiles.id`. They do **not**. The only existing FK in the system is `messages.session_id → chat_sessions(id)`. Therefore:
- The `profiles.id` SERIAL→UUID **PK swap has zero existing FK dependents** — it is a clean type change.
- The real multi-tenant work is **adding a new `user_id UUID → profiles(id)` FK** to every tenant-scoped table (currently none exists).

### A.3 Single-tenant assumptions baked into code
- `SQL_PROFILE_SELECT_FIRST = "SELECT * FROM profiles LIMIT 1"` — literally "the one profile".
- `SQL_SESSION_SELECT_ACTIVE` — "the active session", no owner filter.
- `get_client_id()` (`app/api/utils.py`) hashes `client.host + user-agent` — connection dedup only, **not auth**.
- **Zero** occurrences of `user_id`/`profile_id`/`tenant_id`/`owner_id` anywhere in `app/`.

### A.4 Auth status
- **None.** No `Depends`, `HTTPBearer`, OAuth, JWT, or `get_current_user` anywhere.
- All routers in `app/api/main.py` are mounted unauthenticated.

### A.5 Current BYOK posture (violates the new zero-trust rule)
- `api_keys` table: `key_value TEXT` + `key_encrypted BOOLEAN`. Keys **are stored in the DB**, encrypted at rest with a server-side `encryption.key` file via ChaCha20-Poly1305 (`app/encryption.py`).
- Write paths: `POST /api/add_api_key`, `POST /api/add_chutes_key` (`app/api/endpoints/profile.py:141,155`) → `Database.add_api_key_async` → `encrypt_api_key()`.
- Read path: providers fetch keys from DB — `app/providers/base.py:210`: `return await get_api_key_async(self.name)`.
- `profiles.providers_config JSONB` currently holds **preferences** (`preferred_provider`, `preferred_model`, `vision_model_preferences` per `app/services/config_service.py`) — **not raw keys** (keys live in `api_keys`). Must still be audited row-by-row before purge to be certain no key material leaked in.

### A.6 Memory & memory-guardian isolation gaps
- `semantic_facts.session_id INTEGER` nullable, no FK, no `user_id`.
- `db_memory.py:329` — *"Static facts are GLOBAL - no session_id filter"*. In single-tenant this is harmless; in multi-tenant it is a **cross-user data leak** (User A's "my name is Bani" visible to User B). Must become per-`user_id`.
- `memory_review.py` (the memory-guardian): every `UPDATE semantic_facts … WHERE id=%s` / `id IN (…)` is scoped **only by fact id**. `session_id` is passed solely for logging. The weekly memory-review automation will run unscoped unless refactored to iterate per-user.

### A.7 SQL ownership (the two files that own all SQL)
- `app/db/queries.py` — `SCHEMA_DDL`, profile/session/api_key SQL, `encrypt_api_key`/`decrypt_api_key*`.
- `app/memory/db_memory_queries.py` — all `semantic_facts` SQL (insert/select/update/decay).
- Every isolation change lands in these two files + the facades that wrap them.

---

## Part B — Refactoring Plan

### Dependency order
```
Phase 1 (UUID) ──▶ Phase 2 (OAuth+session) ──▶ Phase 4 (isolation)
                                            └─▶ Phase 3 (BYOK)   [can start after Phase 2]
```
Phase 4 needs the `user_id` column (Phase 1) + the authenticated user source (Phase 2). Phase 3 needs the request-context from Phase 2. **Recommended critical path: 0 → 1 → 2 → 4 → 3.**

---

### Phase 0 — Pre-flight (no schema changes)

**0.1 Branch & backup**
- Branch `refactor/multi-tenant` off `master` (never work on `master` per git rules).
- `pg_dump` full logical backup of the live DB to an off-host location; record restore command.
- Snapshot `encryption.key` (still needed for any in-flight `content_encrypted` messages until audited).

**0.2 Extension readiness**
- Verify `CREATE EXTENSION IF NOT EXISTS pgcrypto;` is idempotent and `gen_random_uuid()` resolves. (pgvector already enabled.)

**0.3 Tenant-scope query inventory (deliverable, not code)**
- Enumerate every `SELECT/INSERT/UPDATE/DELETE` in `app/db/queries.py` and `app/memory/db_memory_queries.py` against `chat_sessions`, `messages`, `semantic_facts`, `api_keys`. Tag each as **tenant-scoped** (needs `user_id`) or **global** (e.g. `api_keys` decommission). This list becomes the Phase 4 checklist.

**0.4 BYOK data audit**
- Inspect actual `profiles.providers_config` rows for any key-like values (regex for `sk-`, `Bearer`, long hex) to confirm only preferences are present before purge.

**Gate:** backup verified restorable · inventory complete · branch pushed.

---

### Phase 1 — UUID Migration (PostgreSQL)

**Design decision:** migrate `profiles.id` SERIAL→UUID **and** add `user_id UUID → profiles(id)` to `chat_sessions`, `messages`, `semantic_facts`. Also UUID-ize `chat_sessions.id` + `messages.session_id` for consistency (this is the one genuine FK-type-change in the migration: `messages.session_id INTEGER → UUID`). `api_keys` is **not** migrated — it is decommissioned in Phase 3.

All steps are **additive then cutover**, reversible until the final drop-old-columns step (which we defer/omit per "never drop" rule — old columns stay nullable and unused).

**1.1 Add UUID columns (additive, safe, reversible) — UUIDv7**

**UUIDv7 decision (locked):** all new UUID PKs use a custom `generate_uuidv7()` PL/pgSQL function (RFC 9562: 48-bit millisecond timestamp prefix + 74 bits randomness) for time-ordered index efficiency, instead of UUIDv4 `gen_random_uuid()`. Requires `pgcrypto` extension for `gen_random_bytes()`.

```sql
BEGIN;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION generate_uuidv7()
RETURNS UUID LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  unix_ts_ms BIGINT;
  rand_bytes BYTEA;
BEGIN
  unix_ts_ms := (EXTRACT(EPOCH FROM clock_timestamp()) * 1000)::BIGINT;
  rand_bytes := gen_random_bytes(10);
  RETURN (
    lpad(to_hex(unix_ts_ms), 12, '0')
    || lpad(to_hex((get_byte(rand_bytes, 0) & 15) | 112), 2, '0')
    || lpad(to_hex(get_byte(rand_bytes, 1)), 2, '0')
    || lpad(to_hex((get_byte(rand_bytes, 2) & 63) | 128), 2, '0')
    || lpad(to_hex(get_byte(rand_bytes, 3)), 2, '0')
    || lpad(to_hex(get_byte(rand_bytes, 4)), 2, '0')
    || lpad(to_hex(get_byte(rand_bytes, 5)), 2, '0')
    || lpad(to_hex(get_byte(rand_bytes, 6)), 2, '0')
    || lpad(to_hex(get_byte(rand_bytes, 7)), 2, '0')
    || lpad(to_hex(get_byte(rand_bytes, 8)), 2, '0')
    || lpad(to_hex(get_byte(rand_bytes, 9)), 2, '0')
  )::UUID;
END;
$$;

-- Verify generator produces valid UUIDv7 BEFORE adding columns
DO $$
DECLARE sample UUID;
BEGIN
  sample := generate_uuidv7();
  IF substring(sample::text, 15, 1) != '7' THEN
    RAISE EXCEPTION 'generate_uuidv7 version nibble != 7, got %', substring(sample::text, 15, 1);
  END IF;
  IF substring(sample::text, 20, 1) NOT IN ('8','9','a','b') THEN
    RAISE EXCEPTION 'generate_uuidv7 variant != 10xx, got %', substring(sample::text, 20, 1);
  END IF;
END $$;

-- profiles: new UUIDv7 PK candidate
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS new_id UUID NOT NULL DEFAULT generate_uuidv7();
CREATE UNIQUE INDEX IF NOT EXISTS profiles_new_id_uidx ON profiles(new_id);

-- tenant columns (nullable during backfill)
ALTER TABLE chat_sessions   ADD COLUMN IF NOT EXISTS user_id UUID;
ALTER TABLE chat_sessions   ADD COLUMN IF NOT EXISTS new_id  UUID NOT NULL DEFAULT generate_uuidv7();
ALTER TABLE messages        ADD COLUMN IF NOT EXISTS user_id UUID;
ALTER TABLE messages        ADD COLUMN IF NOT EXISTS new_session_id UUID;  -- replacement for session_id
ALTER TABLE semantic_facts  ADD COLUMN IF NOT EXISTS user_id UUID;
COMMIT;
```

**1.2 Backfill (single-tenant → one user; preserves all data)**
Because the current DB is single-tenant with exactly one profile (`LIMIT 1`), every existing row maps to that one profile's `new_id`.
```sql
-- 1. capture the single existing profile's UUID into a temp mapping
CREATE TEMP TABLE prof_map AS SELECT id AS old_int_id, new_id AS uuid_id FROM profiles;

-- 2. chat_sessions: owner = the one profile; new_id already defaulted
UPDATE chat_sessions cs SET user_id = pm.uuid_id FROM prof_map pm;  -- one row in prof_map

-- 3. messages: owner via session; rewire session FK to UUID
UPDATE messages m
SET user_id = cs.user_id,
    new_session_id = cs.new_id
FROM chat_sessions cs WHERE m.session_id = cs.id;

-- 4. semantic_facts: owner via metadata->>'session_id' (the REAL join key —
--    the semantic_facts.session_id column is never written by SQL_FACT_INSERT;
--    session linkage lives in metadata->>'session_id' per db_memory.py:117-119
--    and db_memory_queries.py build_metadata_conditions).
UPDATE semantic_facts sf
SET user_id = cs.user_id
FROM chat_sessions cs
WHERE (sf.metadata->>'session_id')::int = cs.id;

-- 5. static/global facts (no session_id in metadata, or unjoinable): owner = the one profile
UPDATE semantic_facts sf
SET user_id = (SELECT uuid_id FROM prof_map LIMIT 1)
WHERE user_id IS NULL;

-- 6. CATCH-ALL (added after live run): orphan messages whose session_id references
--    a session that no longer exists (pre-existing integrity issue — the FK on
--    messages.session_id was found to be absent; 494 messages reference truly
--    missing sessions, not soft-deleted ones). Single-tenant => all belong to the
--    one profile. Set user_id so they're tenant-scoped; leave new_session_id NULL
--    honestly (the session is gone, no UUID to link to).
UPDATE messages m
SET user_id = (SELECT uuid_id FROM prof_map LIMIT 1)
WHERE m.user_id IS NULL;
```

**1.3 Enforce NOT NULL after backfill**
```sql
ALTER TABLE chat_sessions  ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE messages       ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE semantic_facts ALTER COLUMN user_id SET NOT NULL;
```

**1.4 Cutover PK on profiles (no existing FK dependents — safe)**
```sql
-- drop old serial PK + sequence
ALTER TABLE profiles DROP CONSTRAINT profiles_pkey;
DROP SEQUENCE IF EXISTS profiles_id_seq;   -- only after PK drop
ALTER TABLE profiles RENAME COLUMN new_id TO id;  -- but id exists; see note
```
**Note on the rename collision:** `profiles` keeps `id` (SERIAL) column. Cleanest cutover: rename old `id`→`legacy_int_id` first, then `new_id`→`id`, then promote to PK:
```sql
ALTER TABLE profiles RENAME COLUMN id TO legacy_int_id;
ALTER TABLE profiles RENAME COLUMN new_id TO id;
ALTER TABLE profiles ADD CONSTRAINT profiles_pkey PRIMARY KEY (id);
-- keep legacy_int_id nullable for reference; do NOT drop (never-drop rule)
```

**1.5 Rewire the messages→chat_sessions FK to UUID**
```sql
ALTER TABLE messages DROP CONSTRAINT messages_session_id_fkey;  -- the ON DELETE CASCADE one
ALTER TABLE chat_sessions RENAME COLUMN id TO legacy_int_id;
ALTER TABLE chat_sessions RENAME COLUMN new_id TO id;
ALTER TABLE chat_sessions ADD CONSTRAINT chat_sessions_pkey PRIMARY KEY (id);
ALTER TABLE messages RENAME COLUMN session_id TO legacy_session_id;
ALTER TABLE messages RENAME COLUMN new_session_id TO session_id;
ALTER TABLE messages ADD CONSTRAINT messages_session_id_fkey
  FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE;
```

**1.6 Add the new tenant FKs (the real isolation constraint)**
```sql
ALTER TABLE chat_sessions  ADD CONSTRAINT chat_sessions_user_id_fkey
  FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
ALTER TABLE messages       ADD CONSTRAINT messages_user_id_fkey
  FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
ALTER TABLE semantic_facts ADD CONSTRAINT semantic_facts_user_id_fkey
  FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user   ON chat_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_user        ON messages(user_id);
CREATE INDEX IF NOT EXISTS idx_semantic_facts_user  ON semantic_facts(user_id);
```

**1.7 Code-side type changes (psycopg v3)**
- `app/db/queries.py` `SCHEMA_DDL`: rewrite the four `CREATE TABLE` blocks to UUID PKs + `user_id` cols (for fresh installs). Keep `legacy_*` columns out of new installs.
- `parse_profile_row`, `build_profile_update`, `DEFAULT_PROFILE_PARAMS`: `id` now `UUID` (str in Python via psycopg).
- All `session_id: int` annotations across `app/memory/db_memory.py`, `app/memory/memory_review.py`, orchestrator, services → `session_id: str` (UUID).
- `pgvector` `embedding VECTOR(1024)` unaffected.

**1.8 Verification gate (Phase 1)**
- `SELECT count(*) FROM profiles/chat_sessions/messages/semantic_facts` unchanged pre/post.
- `SELECT count(*) FROM messages m LEFT JOIN chat_sessions c ON m.session_id=c.id WHERE c.id IS NULL` → 0 (no orphaned FKs).
- `SELECT count(*) FROM semantic_facts WHERE user_id IS NULL` → 0.
- `ruff check .` + `python3 -m py_compile` on all changed files + `pytest tests/`.
- **Rollback:** restore from 0.1 `pg_dump` (the additive steps are reversible, but the PK/FK cutover in 1.4–1.5 is the point of no return — backup is the rollback).

**Gate:** counts match · zero orphans · lint+tests green.

**Live-run findings (2026-06-21):**
- 494 messages were orphans (session_id references truly missing sessions, not soft-deleted). Pre-existing: the FK on `messages.session_id` was found absent. Catch-all step 6 scopes them to the single tenant; `new_session_id` left NULL honestly.
- All tenant columns backfilled: profiles 1/1, chat_sessions 40/40, messages 12924/12924, semantic_facts 2362/2362. Zero NULL `user_id`. Zero orphan `user_id`. All UUIDv7 valid (v=7, var=10xx). Time-ordered prefix confirmed.

---

### Phase 2 — OAuth2 + Session Auth (FastAPI)

**2.1 New table: `user_identities` (OAuth linkage) + `user_sessions` (server-side sessions)**
Additive DDL in `app/db/queries.py` `SCHEMA_DDL`:
```sql
CREATE TABLE IF NOT EXISTS user_identities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  provider VARCHAR(32) NOT NULL,        -- 'google' | 'github' | ...
  provider_sub TEXT NOT NULL,           -- stable id from IdP (e.g. google 'sub')
  email TEXT,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE (provider, provider_sub)       -- one identity maps to exactly one user
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_identities_provider_sub
  ON user_identities(provider, provider_sub);

CREATE TABLE IF NOT EXISTS user_sessions (
  token TEXT PRIMARY KEY,               -- opaque, 32-byte urlsafe random
  user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  created_at TIMESTAMP DEFAULT NOW(),
  expires_at TIMESTAMP NOT NULL,
  revoked_at TIMESTAMP DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_expires ON user_sessions(expires_at);
```
**Dependencies — DECISION LOCKED:** `httpx` (already a direct dependency in `pyproject.toml`, used by `app/providers/*.py`, `app/llm_client.py`, `app/memory/embedder.py`, `app/tools/http_request.py`) for the OAuth2 token-exchange + userinfo HTTP calls, plus `PyJWT` 2.13.0 (already installed, verified `import jwt` works) for `id_token` signature + claims (iss/aud/exp/nonce) verification. **`authlib` and any heavy monolithic OAuth framework are explicitly rejected.** Both providers (GitHub + Google) are implemented with just `httpx` + `PyJWT` — no new dependencies to approve. PKCE `code_verifier`/`challenge` and the `_oauth_state` short-lived cookie approach remain as described.

**2.2 OAuth2 Authorization Code + PKCE flow — BOTH providers from day one**
Two providers, both wired in Phase 2 (not "Google first, GitHub later"): **Google OIDC** and **GitHub OAuth**. They share the same `user_identities` table (distinguished by the `provider` column) and the same callback/cookie machinery; only the IdP-specific endpoints, scopes, and token-exchange payloads differ.

Env vars (set in `.env`, never committed) — per provider:
- Google: `OAUTH_GOOGLE_CLIENT_ID`, `OAUTH_GOOGLE_CLIENT_SECRET`, `OAUTH_GOOGLE_REDIRECT_URI`.
- GitHub: `OAUTH_GITHUB_CLIENT_ID`, `OAUTH_GITHUB_CLIENT_SECRET`, `OAUTH_GITHUB_REDIRECT_URI`.
- Shared: `APP_BASE_URL`, `SESSION_SECRET` (HMAC key for state cookie).

Provider specifics:
- **Google OIDC:** discovery at `https://accounts.google.com/.well-known/openid-configuration`; scopes `openid email profile`; returns an `id_token` (JWT) verified via `PyJWT` against Google JWKS (`https://www.googleapis.com/oauth2/v3/certs`); stable identity = `sub`.
- **GitHub OAuth:** token endpoint `https://github.com/login/oauth/access_token`; no id_token, so identity is fetched from `GET https://api.github.com/user` (stable numeric `id` as `provider_sub`) + `GET https://api.github.com/user/emails` for primary verified email; scopes `read:user user:email`. No JWT verification needed for GitHub (no id_token), just `httpx` token exchange + userinfo.

New endpoints in a new `app/api/endpoints/auth.py` (mounted in `app/api/main.py`):
- `GET /api/auth/login` → 302 to Google consent URL with PKCE `code_verifier`/`challenge` stored in a short-lived `_oauth_state` cookie.
- `GET /api/auth/callback?code=&state=` → verify state, exchange code for tokens, verify id_token signature+aud+iss+nonce, extract `sub` + `email`.
- **Identity mapping → profile provisioning:**
  1. `SELECT user_id FROM user_identities WHERE provider='google' AND provider_sub=%s`.
  2. If found → reuse that `user_id` (UUID).
  3. If not found → `INSERT INTO profiles (…defaults…) RETURNING id` (provision new profile with UUID PK), then `INSERT INTO user_identities (user_id, provider, provider_sub, email)`.
  4. Mint opaque session token, `INSERT INTO user_sessions`, set cookie.
- `POST /api/auth/logout` → `UPDATE user_sessions SET revoked_at=NOW() WHERE token=%s`, clear cookie.
- `GET /api/auth/me` → returns `{user_id, email, provider}` (no secrets).

**2.3 Session token strategy — HttpOnly cookie + server-side session table**
- Cookie: `yuzu_session=<opaque token>`; attributes `HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=...`.
- **Why not JWT:** server-side sessions are **revocable** ("sign out everywhere", force logout), smaller cookie, no key-rotation headaches. JWT is stateless but irrevocable without a denylist — wrong trade-off for a companion app.
- Auth dependency: `async def get_current_user(request: Request) -> str` in `app/api/utils.py`:
  - read `yuzu_session` cookie → `SELECT user_id FROM user_sessions WHERE token=%s AND expires_at>NOW() AND revoked_at IS NULL`.
  - return `user_id` (UUID str) or raise `HTTPException(401)`.
- **SSE compatibility:** the streaming endpoint `/api/send_message_stream` already uses `fetch()` + `StreamingResponse` (not native `EventSource`), so the HttpOnly cookie rides along automatically — no header gymnastics needed for auth. (Verified via `app/api/endpoints/chat.py`: Form/JSON body + `StreamingResponse`.)

**2.4 Protect every router**
- In `app/api/main.py`, apply `Depends(get_current_user)` to `chat`, `sessions`, `profile`, `memory`, `stream` routers. `auth` + `static` stay public.
- Each handler receives `user_id: str = Depends(get_current_user)` as first param and threads it into the service/orchestrator layer.

**2.5 Verification gate (Phase 2)**
- Manual: full login → callback → cookie set → `/api/auth/me` returns identity → logout revokes.
- Unauthorized request to `/api/send_message` → 401.
- Cookie absent/expired/revoked → 401.
- `ruff` + `py_compile` + `pytest`.

**Gate:** login loop works · all routers 401 without cookie.

---

### Phase 3 — Strict Client-Side BYOK (Zero-Trust API Keys)

**3.1 Decommission `api_keys` table + purge secrets**
- **Purge existing keys:** `UPDATE api_keys SET key_value=NULL, key_encrypted=FALSE;` (do **not** `DROP TABLE` — never-drop rule; leave it empty/tombstoned).
- Audit `profiles.providers_config` rows (Phase 0.4 result): if any key-like value found, strip it; keep only non-secret preferences (`preferred_provider`, `preferred_model`, `vision_model_preferences`).
- Remove from `SCHEMA_DDL` any future use; mark `api_keys` deprecated in a code comment.
- **Keep `app/encryption.py`** — still used for `messages.content_encrypted` if that path is live (separate concern, out of scope here, but do not delete the module).

**3.2 Backend: per-request key via header + ContextVar (stateless)**
- New header contract: **`X-Provider-Key: <plaintext key>`** on every request that triggers an external LLM/provider API call. Optional companion header `X-Provider-Name` when ambiguous (e.g. vision vs chat provider).
- **Scope rule — BYOK enforced only on LLM-producing endpoints.** Endpoints that only read in-memory or DB state and never call an external provider do NOT require (and should NOT enforce) `X-Provider-Key`. Verified exceptions (from `app/api/endpoints/stream.py`):
  - `GET /api/stream/{session_id}/status` — reads `StreamManager.get_stream()` in-memory buffer only; no LLM call → **no BYOK header**.
  - `GET /api/stream/{session_id}/sync` — reads `StreamManager.get_stream()` checksum/length only; no LLM call → **no BYOK header**.
  - `GET /api/profile`, `GET /api/sessions`, `GET /api/memory/*` (read-only) — DB reads only → **no BYOK header**.
  - Enforce BYOK on: `POST /api/send_message`, `POST /api/send_message_stream`, `POST /api/generate_image`, any vision/config endpoint that triggers an LLM call.
- New `app/api/context.py`: a `ContextVar` holding a small `RequestKeyring` (`{provider_name: key}`) populated by middleware from `X-Provider-Key` (+ `X-Provider-Name`). Set per-request, cleared in `finally`.
- Middleware/dependency `attach_provider_keyring(request)` runs on protected routers, reads headers, stuffs the ContextVar. **Backend never persists the key** — it lives only in request-scoped memory.
- **Provider read-site change:** `app/providers/base.py:210` `return await get_api_key_async(self.name)` → `return get_request_key(self.name)` (reads ContextVar). If absent → raise a typed `MissingProviderKeyError` → endpoint maps to `401`/`424` with a clear "set your API key in the client" message. **No DB key read remains.**
- Remove `Database.get_api_key(s)`, `add_api_key`, `remove_api_key` (sync + async) from the facade surface used by app code; keep the SQL constants inert or delete the call sites. Remove `POST /api/add_api_key`, `POST /api/add_chutes_key` endpoints (or repoint them to a no-op that tells the client to store locally).
- `app/services/config_service.py` + `session_service.py`: remove `get_api_keys()` calls; provider availability now derived from "key present in request" not "key in DB".

**3.3 Frontend: keys in LocalStorage/IndexedDB, attached per-request**
- New small module (vanilla ESM, no bundler per frontend rules): `static/js/keyring.js` — stores `{provider: key}` in `localStorage` (or `IndexedDB` if keys are large/multiple; LocalStorage is sufficient and simpler). Never sent to any non-LLM endpoint.
- A `fetch` wrapper/interceptor (`static/js/api.js` or inline in `chat.js`) injects `X-Provider-Key` (and `X-Provider-Name`) on LLM-producing endpoints only (per the 3.2 scope rule — NOT on `/api/stream/*/sync` or `*/status`).
- Because streaming uses `fetch` + `ReadableStream` (not `EventSource`), the custom header **can** be attached to the streaming request — this is the key enabler. **VERIFIED** (not a hypothetical): the streaming path lives in `static/js/modules/multimodal.js` (re-exported via `static/js/chat.js` → `./modules/index.js`), and there are **exactly two** `fetch("/api/send_message_stream", …)` call sites that need header injection:
  1. **`static/js/modules/multimodal.js:278`** — the chat + image-attach path. Uses `FormData` body. Currently has **no `headers` block** (FormData sets its own Content-Type). Inject: add `headers: { "X-Provider-Key": keyring.get(activeProvider) }` to the fetch options. (Do NOT set Content-Type here — FormData must set its own multipart boundary.)
  2. **`static/js/modules/multimodal.js:552`** — the `/imagine` path. Uses JSON body with `headers: { "Content-Type": "application/json" }`. Inject: merge `X-Provider-Key` into the existing headers object: `headers: { "Content-Type": "application/json", "X-Provider-Key": keyring.get(activeProvider) }`.
  Both call sites then proceed to `response.body.getReader()` + `TextDecoder()` for SSE parsing — header injection is transparent to the rest of the streaming logic. No `EventSource` exists anywhere in the streaming path, so no migration is needed.
- Settings UI: a "Provider Keys" panel that writes only to LocalStorage and shows masked `••••last4`; a "test connection" button that fires a throwaway LLM ping with the header.
- **No key ever appears in a request body, URL query string, or log.** Add a log-scrubbing rule: never log `X-Provider-Key`.

**3.4 Verification gate (Phase 3)**
- `SELECT key_value FROM api_keys` → all NULL.
- `grep -r "get_api_key" app/` → only references inside the decommissioned facade (no live callers).
- Request without `X-Provider-Key` to `/api/send_message` → 401/424 with clear message.
- Request with header → LLM call succeeds; backend logs show no key material.
- Frontend: key persists across reload in LocalStorage, survives page refresh, is sent only to LLM endpoints.
- `ruff` + `py_compile` + `npx @biomejs/biome check static/js/`.

**Gate:** DB holds no keys · backend has no key-read path · keys never logged.

---

### Phase 4 — Multi-Tenant Isolation

**4.1 The enforcement model (centralized, auditable)**
- **`user_id` is a required first parameter** on every tenant-scoped `Database` facade method and every `models_async`/`models` function — not a thread-local, not optional. Forgetting it is a `TypeError` at call time, not a silent cross-user leak.
- Every tenant-scoped SQL constant in `app/db/queries.py` + `app/memory/db_memory_queries.py` gains `AND user_id = %s` (or `WHERE user_id = %s` for single-row lookups). `user_id` is always the last bind param.
- FastAPI handlers obtain `user_id` via `Depends(get_current_user)` (Phase 2) and pass it down: endpoint → service (`chat_service`, `session_service`, `config_service`, `memory_service`) → orchestrator → memory module. The orchestrator signature `handle_user_message(message, interface=…)` becomes `handle_user_message(message, user_id, interface=…)`. Same for `handle_user_message_streaming`.

**4.2 Per-table scoping rules**
- `chat_sessions`: `SQL_SESSION_SELECT_ACTIVE` → `… WHERE is_active=TRUE AND deleted_at IS NULL AND user_id=%s LIMIT 1`. `create_session` inserts `user_id`. List-sessions endpoint scopes by `user_id`.
- `messages`: all selects/inserts carry `user_id` (denormalized on the row in Phase 1.2, so even a stray `session_id` reuse can't cross tenants). `get_chat_history` → `WHERE session_id=%s AND user_id=%s`.
- `semantic_facts`: **the semantic change** — static facts are **no longer global**. `db_memory.py:329` branch that skips session filter must now filter `WHERE user_id=%s` for *all* fact types. Retrieval (`app/memory/retrieval.py`), insertion (`db_memory.py`), decay (`memory_review.py`), PCL (`app/memory/pcl.py`), extractor — all gain `user_id`.
- `profiles`: `SQL_PROFILE_SELECT_FIRST` is **deleted**. Replaced by `SELECT * FROM profiles WHERE id=%s` with the authenticated `user_id`.

**4.3 Memory-guardian per-user**
- `app/memory/memory_review.py`: every `UPDATE semantic_facts … WHERE id=%s`/`id IN (…)` gains `AND user_id=%s`. The fact-id lists passed in must already be user-scoped (the queries that *build* those id lists get `user_id`).
- The **Weekly Memory Review** automation must iterate `SELECT id FROM profiles` and run the review **once per `user_id`**, scoping each pass. Update the automation's instruction to reflect per-user iteration.
- `scripts/cleanup_memory.sql`, `scripts/dedupe_facts.py`, `scripts/cleanup_memories.py` — audit & add `user_id` scope; otherwise they remain dangerous global mutators.

**4.4 Anti-regression guardrails (the "forget to scope" footgun)**
- **Static test** (`tests/test_tenant_isolation.py`): parse `queries.py` + `db_memory_queries.py`, assert every statement touching `chat_sessions`/`messages`/`semantic_facts` contains a `user_id` bind. Fails CI on any unscoped statement.
- **Runtime guard** in the facade: tenant-scoped methods raise `TenantScopeError` if `user_id` is falsy.
- **Integration test**: seed two users with distinct facts; assert User A's retrieval never returns User B's facts; assert User A's session list excludes User B's sessions.

**4.5 Verification gate (Phase 4)**
- `pytest tests/test_tenant_isolation.py` green (static + integration).
- Two-user manual test: cross-user leakage impossible across chat history, sessions, memory retrieval, memory-guardian cleanup.
- `ruff` + `py_compile` across `app/db/`, `app/memory/`, `app/orchestrator.py`, `app/services/`.
- Full `pytest tests/` green.

**Gate:** isolation tests green · zero unscoped tenant queries · memory-guardian per-user.

---

## Part C — Risk Register & Cross-Cutting Concerns

| # | Risk | Mitigation |
|---|---|---|
| R1 | UUID PK cutover (1.4–1.5) is the point of no return | Mandatory `pg_dump` (0.1); additive cols make 1.1–1.3 reversible; only 1.4–1.5 need backup-rollback |
| R2 | Static facts becoming per-user changes memory semantics | Document as intended (cross-user leak otherwise); existing single-user data backfilled to that one user — no loss |
| R3 | ~~`authlib` is a new dependency~~ **RESOLVED** | Finalized: `httpx` (already a direct dep) + `PyJWT 2.13.0` (already installed). Zero new dependencies. No `authlib`. |
| R4 | ~~Streaming must use `fetch` not `EventSource` for BYOK header~~ **RESOLVED** | Verified: streaming uses `fetch()` + `getReader()` at `static/js/modules/multimodal.js:278` (FormData) and `:552` (JSON). No `EventSource` anywhere. Two exact injection points identified in 3.3. |
| R5 | Memory-guardian automation currently unscoped | 4.3 updates automation to per-user iteration before re-enabling |
| R6 | `session_id: int → str` type ripple across memory layer | Phase 1.7 annotation sweep + `py_compile` gate per file |
| R7 | `legacy_*` columns linger (never-drop rule) | Acceptable; excluded from new installs via rewritten `SCHEMA_DDL`; documented as deprecated |
| R8 | Existing `content_encrypted` messages depend on `encryption.key` | Out of scope; key file preserved; flagged for separate audit |
| R9 | OAuth redirect URI tied to host; deploy env differences | `OAUTH_REDIRECT_URI` env-driven; document per-environment value |

**Finalized decisions (all locked, plan updated accordingly):**
1. **OAuth providers:** BOTH GitHub OAuth and Google OAuth from day one (not "Google first, GitHub later"). Shared `user_identities` table, shared callback/cookie machinery, IdP-specific endpoints only.
2. **OIDC/OAuth library stack:** `httpx` (already a direct dependency) + `PyJWT 2.13.0` (already installed). **No `authlib`, no heavy monolithic framework.** Zero new dependencies.
3. **Session store:** server-side `user_sessions` table (opaque token, revocable). Confirmed.
4. **UUID scope:** full UUID migration — `profiles.id`, `chat_sessions.id`, and `messages.session_id` all become UUID. Confirmed.
5. **Streaming/BYOK injection:** verified `fetch`-streaming (no `EventSource`) at `static/js/modules/multimodal.js:278` (FormData) and `:552` (JSON). BYOK header enforced on LLM-producing endpoints only; `/api/stream/*/sync` and `*/status` excluded (they read in-memory buffer, no LLM call). Confirmed.
6. **Data residency:** chat history, `semantic_facts`, and `profiles` stay in PostgreSQL tied to the user UUID. Only LLM API keys are client-side LocalStorage. Clearing browser cache loses only keys, never chat/memory/profile data.

---

## Execution order summary
`Phase 0` → `Phase 1` (UUID) → `Phase 2` (OAuth+session) → `Phase 4` (isolation) → `Phase 3` (BYOK). Each phase ends with a lint+compile+test+runtime gate and your sign-off before the next begins. No SQL runs, no implementation code is written, until you approve.
