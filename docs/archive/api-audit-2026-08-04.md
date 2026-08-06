# Yuzu Companion — HTTP API Comprehensive Audit

> Audited against HEAD of branch `dev`, commit `3a59cbe`.  
> All findings are grounded in source code evidence.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Overall Scorecard](#2-overall-scorecard)
3. [API Inventory](#3-api-inventory)
4. [API Architecture Review](#4-api-architecture-review)
5. [Security Review](#5-security-review)
6. [Validation Review](#6-validation-review)
7. [Error Handling Review](#7-error-handling-review)
8. [OpenAPI Review](#8-openapi-review)
9. [Documentation Review](#9-documentation-review)
10. [Public vs Internal API Matrix](#10-public-vs-internal-api-matrix)
11. [Public API Catalog Proposal](#11-public-api-catalog-proposal)
12. [Developer Experience Review](#12-developer-experience-review)
13. [Maintainability Review](#13-maintainability-review)
14. [Performance Review](#14-performance-review)
15. [Operational Readiness Review](#15-operational-readiness-review)
16. [Test Coverage Review](#16-test-coverage-review)
17. [Versioning Review](#17-versioning-review)
18. [Breaking Change Risks](#18-breaking-change-risks)
19. [Prioritized Recommendations](#19-prioritized-recommendations)
20. [Suggested Roadmap](#20-suggested-roadmap)

---

## 1. Executive Summary

Yuzu Companion is a personal AI companion application with cookie-based OAuth authentication, SSE streaming, multimodal image upload, graph memory, and a BYOK (bring-your-own-key) provider architecture. This audit covers 7 router files, 1 health endpoint, 40+ endpoints, the full auth pipeline, and 26 test files across approximately 2,700 test lines.

**Verdict: NOT READY for public API release. READY WITH CHANGES for controlled single-tenant production use.**

The codebase shows strong discipline in areas the team has actively worked on — tenant isolation, SQL injection prevention, OAuth PKCE, and profile field whitelisting. Critical gaps exist in areas that received less attention:

- Security headers are entirely absent
- No HTTP rate limiting on any endpoint
- `POST /api/update_profile` accepts an arbitrary freeform `dict` before whitelisting happens in the SQL layer (mass assignment risk)
- File uploads carry zero content-type or size validation
- SSE streams have no `Cache-Control` or `X-Accel-Buffering` headers
- `/health` endpoint leaks no database readiness signal
- The entire API surface has no versioning strategy

---

## 2. Overall Scorecard

| Dimension               | Score |
|-------------------------|-------|
| API Architecture        | 6/10  |
| Security                | 4/10  |
| Documentation           | 3/10  |
| Developer Experience    | 4/10  |
| Maintainability         | 7/10  |
| Production Readiness    | 4/10  |
| Public API Readiness    | 2/10  |

---

## 3. API Inventory

All endpoints discovered from source code. The `/api` prefix applies to all endpoints except `/health` and HTML page routes.

### Auth Router (`app/api/endpoints/auth.py`, prefix: `/api/auth`)

| Method | Path | Auth | Streaming | Notes |
|--------|------|------|-----------|-------|
| GET | `/api/auth/login` | None (public) | No | Redirects to OAuth provider. Sets `_oauth_state` cookie. Supports `google` + `github`. |
| GET | `/api/auth/callback` | None (validates state cookie) | No | Completes PKCE OAuth flow. Sets `yuzu_session` cookie. Redirects to `/chat`. |
| POST | `/api/auth/logout` | Session cookie (optional) | No | Revokes session token, clears cookie. Works even without valid session. |
| GET | `/api/auth/me` | Session cookie | No | Returns identity row. No response model declared. |

### Chat Router (`app/api/endpoints/chat.py`, no prefix)

| Method | Path | Auth | Streaming | Notes |
|--------|------|------|-----------|-------|
| POST | `/api/send_message` | Session cookie | No | Non-streaming path. Errors returned as HTTP 200 with `{"reply": "Sorry..."}`. |
| POST | `/api/send_message_stream` | Session cookie | Yes (SSE) | Dual content-type dispatch (JSON or multipart). No image content-type validation. No `Cache-Control` or `X-Accel-Buffering` headers. |
| POST | `/api/generate_image` | Session cookie | No | Prepends `/imagine` to message and delegates to orchestrator. Swallows exceptions, returns HTTP 200 on error. |
| POST | `/api/browser_unload` | Session cookie | No | Called by browser `beforeunload`. Returns 200 even on error. Not idempotent. |

### Sessions Router (`app/api/endpoints/sessions.py`, no prefix)

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/api/chat_history` | Session cookie | `limit=0` loads ALL messages — dangerous on large sessions. |
| GET | `/api/chat_history/before` | Session cookie | Upward pagination. `before_ts` is a raw string with no format validation. |
| GET | `/api/sessions/list` | Session cookie | |
| POST | `/api/sessions/create` | Session cookie | Creates and immediately switches to the new session. |
| POST | `/api/sessions/switch` | Session cookie | Redundant `session_id` field in response. Runs `start_session_async` on every switch. |
| POST | `/api/sessions/rename` | Session cookie | No `max_length` constraint on `name`. |
| POST | `/api/sessions/delete` | Session cookie | **Wrong method** — should be `DELETE /api/sessions/{id}`. Includes full chat history in delete response. |
| POST | `/api/clear_chat` | Session cookie | Destructive. No confirmation token. `session_id` passed as query param on a POST. |
| POST | `/api/end_session` | Session cookie | Browser lifecycle. Swallows all exceptions silently. |

### Profile Router (`app/api/endpoints/profile.py`, no prefix)

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/api/config` | Session cookie | Frontend-specific config blob. Untyped response. |
| GET | `/api/profile` | Session cookie | Heavyweight: 4 sequential DB reads per call. No response model. |
| POST | `/api/update_profile` | Session cookie | **Mass assignment risk** — accepts `dict[str, object]`. Whitelist only in SQL layer. |
| GET | `/api/providers/list` | Session cookie | |
| GET | `/api/proxy/models/{provider}` | Session cookie | **SSRF risk** — makes outbound HTTP to user-supplied `base_url`. |
| POST | `/api/proxy/models/{provider}/refresh` | Session cookie | **SSRF risk** — same as above. |
| POST | `/api/providers/set_preferred` | Session cookie | |
| POST | `/api/providers/test_connection` | Session cookie | Dev/debug utility. |
| POST | `/api/update_location` | Session cookie | Validates lat/lon ranges correctly. |
| GET | `/api/global-knowledge` | Session cookie | |
| POST | `/api/global-knowledge` | Session cookie | Returns 201. |
| PATCH | `/api/global-knowledge/{entry_id}` | Session cookie | **PATCH semantics broken** — requires all fields. |
| DELETE | `/api/global-knowledge/{entry_id}` | Session cookie | Returns 204. Correct HTTP semantics. |

### Memory Router (`app/api/endpoints/memory.py`, no prefix)

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| POST | `/api/rebuild_structured_memory` | Session cookie | Long-running. No async job ID returned. Blocks HTTP connection. |
| GET | `/api/memory_stats` | Session cookie | Admin/maintenance operation. |

### Stream Router (`app/api/endpoints/stream.py`, prefix: `/api/stream`)

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/api/stream/{session_id}/status` | Session cookie | Frontend polling helper. |
| GET | `/api/stream/{session_id}/sync` | Session cookie | Debugging/sync utility. |

### Presets Router (`app/api/endpoints/presets_endpoint.py`, no prefix)

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/api/presets/list` | Session cookie | |
| POST | `/api/presets/upsert` | Session cookie | |
| POST | `/api/presets/activate` | Session cookie | |
| POST | `/api/presets/delete` | Session cookie | **Wrong method** — should be `DELETE /api/presets/{name}`. |

### Static Router (`app/api/static.py`, prefix: `/api/static`)

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/api/static/uploads/{filename}` | **None** | Unauthenticated user file access. Path traversal guarded. |
| GET | `/api/static/generated_images/{filename}` | **None** | Returns 1×1 SVG on missing file instead of 404. |

### Health Router (`app/api/endpoints/health.py`, no prefix)

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET/HEAD | `/health` | None | Always returns `{"status": "ok"}`. Does NOT check DB connectivity. |

### HTML Routes (`main.py`, not under `/api`)

| Method | Path | Auth |
|--------|------|------|
| GET | `/login` | None |
| GET | `/` | Session cookie |
| GET | `/chat` | Session cookie |
| GET | `/chat/{session_id}` | Session cookie |
| GET | `/config` | Session cookie |
| GET | `/about` | Session cookie |
| GET | `/static/html/sidebar.html` | None |
| GET | `/favicon.ico` | None |

### Anomalies Detected

- **Duplicate static serving:** `/api/static/uploads/{filename}` and `/api/static/generated_images/{filename}` duplicate the `StaticFiles` mounts registered in `main.py`. Two serving paths for the same directories exist simultaneously.
- **Alias endpoint:** `POST /api/generate_image` prepends `/imagine` and calls the same orchestrator as `POST /api/send_message`. No distinct value. Creates a maintenance fork.
- **Dead root files:** `prompt_optimizer.py` and `hello_world.py` at project root are not endpoints but exist in the tracked tree.

---

## 4. API Architecture Review

### Resource Naming

Paths are inconsistent across three conventions used simultaneously:

- Underscored RPC-style: `/send_message`, `/clear_chat`, `/rebuild_structured_memory`
- Kebab-case REST style: `/global-knowledge`
- Slash-noun RPC: `/sessions/create`, `/providers/list`

No consistent convention exists across the surface.

### HTTP Method Correctness

| Endpoint | Current | Correct |
|----------|---------|---------|
| `POST /api/sessions/delete` | POST + body | `DELETE /api/sessions/{id}` |
| `POST /api/presets/delete` | POST + body | `DELETE /api/presets/{name}` |
| `PATCH /api/global-knowledge/{id}` | Requires all fields | Should be `PUT`, or implement partial update |
| `POST /api/clear_chat` | POST with `session_id` as query param | POST with `session_id` in body |

### Versioning

Zero versioning. The `FastAPI(version="1.0.0")` declaration is cosmetic metadata only. No `/v1/` prefix, no `Accept-Version` header support, no deprecation headers. Breaking changes cannot be introduced without immediately breaking all consumers.

### Pagination

`GET /api/chat_history` uses a `limit` query param. `GET /api/chat_history/before` uses a timestamp cursor. Neither uses Link headers, standard cursor envelopes, or total counts. The `has_more` boolean is the only pagination signal.

### Filtering, Sorting, Searching

Absent. No filtering on sessions list, no sort control, no search over message history.

### Streaming

`POST /api/send_message_stream` returns `text/event-stream` without setting `Cache-Control: no-cache` or `X-Accel-Buffering: no`. On nginx proxies this causes the response to be buffered, breaking the streaming UX entirely.

### Idempotency

`POST /api/sessions/create` is not idempotent — calling it twice creates two sessions. No `Idempotency-Key` header support. Clients that retry on network failure will duplicate sessions.

### Response Consistency

Three distinct error shapes exist:

1. `{"detail": "..."}` — FastAPI default `HTTPException`
2. `{"reply": "Sorry, ..."}` — `/api/send_message` error path (HTTP 200, error in body)
3. `{"type": "error", "message": "..."}` — SSE error event

No success response schema is enforced. Some endpoints return `{"status": "success"}`, others return domain objects directly, others return 204 No Content. There is no shared `APIResponse` wrapper.

### Timestamp Format

`parse_message_row` returns `"timestamp": str(row.get("timestamp", ""))`. `str(datetime)` produces `"2026-08-02 14:30:00.123456"` — not ISO 8601, no timezone specifier. This will break typed client deserializers.

---

## 5. Security Review

### SEC-01 — CRITICAL: No HTTP Security Headers

**Evidence:** `grep -rn 'X-Content-Type\|X-Frame\|Strict-Transport\|Content-Security' app/ main.py` — zero results.

No `X-Content-Type-Options: nosniff`, no `X-Frame-Options`, no `Strict-Transport-Security`, no `Content-Security-Policy`, no `Referrer-Policy`, no `Permissions-Policy`.

Any XSS payload served via an assistant message (rendered as Markdown/HTML in the frontend) has no CSP backstop. Clickjacking is unrestricted.

**Mitigation:** Add a middleware that injects security headers on every response.

---

### SEC-02 — HIGH: No HTTP Rate Limiting

**Evidence:** No `slowapi`, `limits`, or equivalent in `pyproject.toml` or `main.py`. Provider-level semaphore rate limiting exists in `app/providers/base.py` but limits outbound LLM calls, not inbound API requests.

**Impact:** `POST /api/send_message_stream` can be called in parallel by any authenticated user without throttling, driving arbitrary LLM costs and exhausting DB connection pools.

**Mitigation:** Add `slowapi` or reverse-proxy rate limits. Minimum: per-user concurrency limit on the stream endpoint.

---

### SEC-03 — HIGH: SSRF in Proxy Model Endpoints

**Evidence:** `profile.py:193` — `url = f"{base_dir}/models"` where `base_dir` is derived from the user-supplied `X-Provider-BaseUrl` header. No URL scheme validation, no allowlist, no DNS rebinding protection.

**Exploit scenario:** An authenticated user sends `X-Provider-BaseUrl: http://169.254.169.254/latest/meta-data` (AWS metadata endpoint), or `http://localhost:5432` (PostgreSQL), or `http://internal-host/admin`. The server makes the GET request and returns the response body to the client.

**Affected endpoints:** `GET /api/proxy/models/{provider}`, `POST /api/proxy/models/{provider}/refresh`

**Mitigation:** Validate URL scheme is `https`. Reject private/loopback IPs. Consider a SSRF-safe HTTP client wrapper.

---

### SEC-04 — HIGH: Open Redirect in OAuth Callback

**Evidence:** `auth.py:192` — `redirect_target = urljoin(origin, "/chat")` where `origin` is the `Referer` header captured at login initiation.

**Exploit scenario:** An attacker hosts a page at `https://evil.com` that includes a link or iframe to `/api/auth/login?provider=google`. The victim's browser sends `Referer: https://evil.com`. The PKCE state embeds this origin. After OAuth completes, the callback issues `RedirectResponse(url="https://evil.com/chat")`. The session cookie is already set; the victim lands on the attacker's domain.

**Mitigation:** Strip the origin host entirely. Always redirect to the internal path `/chat` only.

---

### SEC-05 — HIGH: File Upload — No Content-Type or Size Validation

**Evidence:** `chat.py:112` — `images: list[UploadFile] = File(default=[])`. No content-type check, no extension allowlist, no size limit. `conversation_service.py:107` writes uploaded bytes to `static/uploads/`.

**Impact:** An authenticated user can upload arbitrary files (scripts, HTML, executables). Without `X-Content-Type-Options: nosniff`, browsers may execute uploaded scripts served from the same origin.

**Mitigation:** Validate `upload.content_type` against `{"image/jpeg", "image/png", "image/webp", "image/gif"}`. Enforce max file size (e.g., 10 MB). Rename files to random UUIDs on disk.

---

### SEC-06 — HIGH: Unauthenticated Access to Uploaded User Files

**Evidence:** `static.py:14` — `GET /api/static/uploads/{filename}` has no `Depends(get_current_user)`. The `StaticFiles` mount at `/uploads` in `main.py` also has no auth middleware.

**Impact:** Any file uploaded by any user is world-readable to anyone who knows or guesses the filename.

**Mitigation:** Add `get_current_user` dependency. Implement per-user filename namespacing or ownership verification before serving.

---

### SEC-07 — MEDIUM: Mass Assignment via `/api/update_profile`

**Evidence:** `profile.py:43` — `ProfileUpdateRequest { updates: dict[str, object] }` accepts an arbitrary dictionary. Whitelist enforcement happens inside `build_profile_update` in `queries.py`, which silently ignores unknown keys.

**Risks:**
- No input size limit on the dict or individual values
- No field-level validation errors (clients get silent success or generic 500)
- The API shape is opaque — impossible to document or generate typed clients for

**Mitigation:** Replace `dict[str, object]` with a typed Pydantic model listing exactly which fields can be updated, with appropriate validators per field.

---

### SEC-08 — MEDIUM: Session Cookie `samesite` Inconsistency

**Evidence:** `session.py:48` — `set_session_cookie` always sets `samesite="lax"`. `auth.py:94` — OAuth state cookie uses `samesite="none"` when secure. These policies are mismatched.

**Impact:** Session cookie may not be sent during the OAuth redirect-back flow behind Cloudflare tunnels, causing silent auth failures.

**Mitigation:** Align `samesite` policy between state cookie and session cookie using the same detection logic.

---

### SEC-09 — MEDIUM: `X-BYOK-Config` Header Parsed Without Size Limit

**Evidence:** `chat.py:36` — `byok_header = request.headers.get("X-BYOK-Config")`. No size check before base64 decode + JSON parse. A 1 MB header causes unnecessary memory allocation. Malformed payloads fail silently (the request proceeds without BYOK).

**Mitigation:** Add a size check before processing. Return 400 if the header exceeds a reasonable limit (e.g., 64 KB).

---

### SEC-10 — MEDIUM: Missing-Image Fallback Returns HTTP 200

**Evidence:** `static.py:41` — returns a 1×1 SVG with HTTP 200 when generated image file does not exist.

**Impact:** Caching layers cache a "not found" as a successful image. Clients cannot detect missing images.

**Mitigation:** Return `HTTPException(status_code=404)`.

---

### SEC-11 — LOW: SSE Endpoint Has No Server-Side Timeout

**Evidence:** `send_message_stream` opens an unbounded SSE connection. If the orchestrator hangs (LLM provider timeout), the connection holds a DB pool slot indefinitely.

**Mitigation:** Add a server-side timeout in the SSE generator. Yield SSE keepalive comments every 15s.

---

### SEC-12 — LOW: Backup SQL File in Repository Contains Chat History

**Evidence:** `.yuzuki/backup/yuzuki_backup_20260616_195231.sql` visible in grep output — contains full conversation history including sensitive user content. This file appears to be in the working tree.

**Mitigation:** Add `.yuzuki/` to `.gitignore`. Audit git history for prior commits containing this file.

---

### SEC-13 — LOW: HTML Cached as `.jpg` in `image_cache/`

**Evidence:** `app/static/image_cache/844389de9e04133e0de22480d7e2624fddc92f36.jpg` contains GitHub page HTML. A `.jpg` extension on an HTML response served without content-type validation can trigger browser MIME-sniffing.

**Mitigation:** Validate cached files before storing. Reject non-image content.

---

## 6. Validation Review

### Strengths

- `GlobalKnowledgeEntryCreateRequest` has `min_length`, `max_length`, and numeric constraints. Correct.
- `LocationUpdateRequest` validates lat/lon ranges with `ge`/`le`. Correct.
- `MessageRequest` has `min_length=1`. Correct.
- `build_profile_update` in `queries.py` enforces a column allowlist (`_PROFILE_TEXT_FIELDS`, `_PROFILE_JSON_FIELDS`, `_PROFILE_LOCATION_FIELDS`). Prevents SQL column injection.
- Session ID inputs validated for `min_length=1` in all request models.

### Gaps

| Gap | Location | Impact |
|-----|----------|--------|
| `ProfileUpdateRequest.updates: dict[str, object]` — no field-level validation | `profile.py:43` | SEC-07 |
| `SessionRenameRequest.name` — no `max_length` | `sessions.py:37` | 10 MB name accepted |
| `before_ts` — raw string, no ISO format validation | `sessions.py:88` | Malformed value → 500 |
| `PresetUpsertRequest.payload: dict[str, object]` — no depth/size limit | `presets_endpoint.py:31` | Unbounded nested objects |
| `message` with single space passes `min_length=1` but `.strip()` makes it empty → returns 200 instead of 422 | `chat.py:75` | Validation bypass |
| Upload `filename` not validated for null bytes or path separators | `chat.py:112` | Defense-in-depth gap |

---

## 7. Error Handling Review

### HTTP Status Code Inconsistencies

| Situation | Expected | Actual |
|-----------|----------|--------|
| LLM error in `/api/send_message` | 502 or 503 | 200 `{"reply": "Sorry..."}` |
| LLM error in `/api/generate_image` | 502 | 200 `{"reply": "Failed...", "status": "error"}` |
| DB pool timeout | 503 | 503 ✓ |
| Missing active session in `clear_chat` | 400 | 500 |
| Invalid `before_ts` timestamp | 422 | 500 |
| Any error in `browser_unload` | any | 200 always |

### Error Schema Inconsistency

Three error shapes coexist:

```json
// FastAPI HTTPException
{"detail": "Not found"}

// send_message error path (HTTP 200)
{"reply": "Sorry, I encountered an error processing your message."}

// SSE error event
{"type": "error", "message": "Please provide a message or images!"}
```

No RFC 9457 Problem Details. No consistent `type`, `title`, or `instance` URI.

### Silent Exception Swallowing

- `POST /api/end_session` — `except Exception: raise HTTPException(500)` with no logging
- `POST /api/browser_unload` — `except Exception: return {"status": "error"}` as HTTP 200
- `POST /api/clear_chat` — `except Exception: raise HTTPException(500)` with no logging

---

## 8. OpenAPI Review

The FastAPI-generated schema (`/docs`, `/redoc`) has the following issues:

1. **No `response_model` declared on any endpoint.** FastAPI infers `Any` for all responses. The schema shows every endpoint returning an untyped `{}`. Client generation is not feasible.

2. **No `summary` or `description` on most endpoints.** Only `GET /api/chat_history` and `GET /api/chat_history/before` have docstrings. All others have none.

3. **`include_in_schema=False` used exactly once** (favicon). All internal/operational endpoints appear in the public schema.

4. **No `operation_id` overrides.** Auto-generated IDs like `api_send_message_stream_send_message_stream_post` become method names in generated SDKs.

5. **No `example` values** on any field. `Field(..., description="...")` exists in some models but no `example=` kwarg.

6. **Swagger UI and ReDoc are publicly accessible** at `/docs` and `/redoc` without authentication. This exposes the full API surface, BYOK header format, internal endpoint structure, and all parameter names to unauthenticated users.

**Recommendation:** Set `docs_url=None, redoc_url=None` in production config. Serve docs separately behind auth.

---

## 9. Documentation Review

**Public-facing:** None. No README section documents the API. No API reference exists outside the auto-generated OpenAPI schema.

**Internal:** `AGENTS.md` is the primary living specification and is comprehensive for internal development. It is not an API reference and cannot substitute for one.

**OpenAPI accuracy:** The schema is technically accurate (FastAPI generates from actual routes) but useless due to absent response models. It accurately represents inputs; response shapes are entirely undocumented.

**BYOK header format:** Entirely undocumented. The base64 + URL-encoded JSON structure with the `providers` key is reverse-engineered from frontend code only.

**SSE event envelope:** The `{"type": "token", "content": "..."}`, `{"type": "done", ...}`, `{"type": "error", ...}`, `{"type": "tool_call", ...}` shapes are not documented anywhere outside `event-router.js`.

---

## 10. Public vs Internal API Matrix

| Endpoint | Classification | Reason |
|----------|---------------|--------|
| GET `/api/auth/login` | PUBLIC | Entry point for auth flow |
| GET `/api/auth/callback` | INTERNAL | OAuth callback, not for direct client calls |
| POST `/api/auth/logout` | PUBLIC | Session termination |
| GET `/api/auth/me` | PUBLIC | Identity verification |
| POST `/api/send_message` | PRIVATE | Legacy non-streaming path |
| POST `/api/send_message_stream` | PUBLIC | Primary chat interface |
| POST `/api/generate_image` | PRIVATE | Alias for send_message; merge or remove |
| POST `/api/browser_unload` | INTERNAL | Browser lifecycle |
| GET `/api/chat_history` | PUBLIC | Core data access |
| GET `/api/chat_history/before` | PUBLIC | Pagination continuation |
| GET `/api/sessions/list` | PUBLIC | Session management |
| POST `/api/sessions/create` | PUBLIC | Session management |
| POST `/api/sessions/switch` | PRIVATE | UI state management |
| POST `/api/sessions/rename` | PUBLIC | Session management |
| POST `/api/sessions/delete` | PUBLIC | Session management (after method fix) |
| POST `/api/clear_chat` | PUBLIC | Destructive but legitimate |
| POST `/api/end_session` | INTERNAL | Browser lifecycle |
| GET `/api/config` | PRIVATE | Frontend-specific config blob |
| GET `/api/profile` | PRIVATE | Frontend-specific fat payload |
| POST `/api/update_profile` | PUBLIC | Core user settings |
| GET `/api/providers/list` | PUBLIC | Provider discovery |
| GET `/api/proxy/models/{provider}` | PRIVATE | Frontend helper; SSRF risk |
| POST `/api/proxy/models/{provider}/refresh` | PRIVATE | Frontend helper; SSRF risk |
| POST `/api/providers/set_preferred` | PUBLIC | Provider selection |
| POST `/api/providers/test_connection` | PRIVATE | Dev/debug utility |
| POST `/api/update_location` | PUBLIC | User data |
| GET `/api/global-knowledge` | PUBLIC | Knowledge management |
| POST `/api/global-knowledge` | PUBLIC | Knowledge management |
| PATCH `/api/global-knowledge/{id}` | PUBLIC | Knowledge management |
| DELETE `/api/global-knowledge/{id}` | PUBLIC | Knowledge management |
| POST `/api/rebuild_structured_memory` | INTERNAL | Admin/maintenance |
| GET `/api/memory_stats` | INTERNAL | Admin/maintenance |
| GET `/api/stream/{session_id}/status` | PRIVATE | Frontend polling helper |
| GET `/api/stream/{session_id}/sync` | INTERNAL | Debugging utility |
| GET `/api/presets/list` | PUBLIC | Preset management |
| POST `/api/presets/upsert` | PUBLIC | Preset management |
| POST `/api/presets/activate` | PUBLIC | Preset management |
| POST `/api/presets/delete` | INTERNAL | Should be DELETE /presets/{name} |
| GET `/api/static/uploads/{filename}` | INTERNAL | Requires auth; currently public |
| GET `/api/static/generated_images/{filename}` | INTERNAL | Requires auth; currently public |
| GET `/health` | PUBLIC | Infrastructure probe |

### Recommended `include_in_schema=False`

```
/api/auth/callback
/api/browser_unload
/api/end_session
/api/proxy/models/{provider}
/api/proxy/models/{provider}/refresh
/api/providers/test_connection
/api/rebuild_structured_memory
/api/memory_stats
/api/stream/{session_id}/status
/api/stream/{session_id}/sync
/api/static/uploads/{filename}
/api/static/generated_images/{filename}
```

---

## 11. Public API Catalog Proposal

The minimal viable public surface for a stable v1 release:

```
Authentication
  GET  /v1/auth/login                    Initiate OAuth
  POST /v1/auth/logout                   Terminate session
  GET  /v1/auth/me                       Get current identity

Chat
  POST /v1/chat/stream                   Send message, receive SSE

Sessions
  GET    /v1/sessions                    List sessions
  POST   /v1/sessions                    Create session
  GET    /v1/sessions/{id}/messages      Chat history (paginated)
  PATCH  /v1/sessions/{id}              Rename session
  DELETE /v1/sessions/{id}              Delete session
  POST   /v1/sessions/{id}/clear        Clear messages

Profile
  PATCH /v1/profile                      Update user settings
  PATCH /v1/profile/location            Update location
  POST  /v1/profile/provider            Set preferred AI provider

Knowledge
  GET    /v1/knowledge                   List knowledge entries
  POST   /v1/knowledge                   Create entry
  PUT    /v1/knowledge/{id}             Replace entry
  DELETE /v1/knowledge/{id}             Delete entry

Presets
  GET    /v1/presets                     List presets
  POST   /v1/presets                     Create or update preset
  POST   /v1/presets/{name}/activate     Activate preset
  DELETE /v1/presets/{name}             Delete preset

Infrastructure
  GET  /health                           Liveness probe
  GET  /health/ready                     Readiness probe (checks DB)
```

---

## 12. Developer Experience Review

### First-Contact Friction: High

No API overview document. Loading `/docs` shows untyped responses for every endpoint. A developer integrating from scratch cannot determine what fields any response contains.

### Authentication Flow

The OAuth flow is not documented. The BYOK header format (base64 + URL-encoded JSON with a `providers` key structure) is entirely undocumented and requires reading `chat.py:25-57` to understand.

### Streaming UX

The SSE envelope format is not documented anywhere. Frontend developers must reverse-engineer it from `event-router.js`. The format includes at minimum:
- `{"type": "token", "content": "...", "turn_id": "..."}`
- `{"type": "done", "turn_id": "..."}`
- `{"type": "error", "message": "..."}`
- `{"type": "tool_call", ...}`

### Response Predictability: Low

Error responses come in three different shapes (see §7). Success responses have no consistent envelope. A developer cannot write a generic error handler that works across all endpoints.

### Naming Inconsistency

snake_case paths, kebab-case paths, and slash-noun paths coexist. No consistent convention.

### SDK Generation: Not Feasible

No `response_model` declarations. Generated client methods return `Any` for all calls. Operation IDs are verbose and auto-generated.

---

## 13. Maintainability Review

### Strengths

- Router-per-domain separation is clean: `auth`, `chat`, `sessions`, `profile`, `memory`, `stream`, `presets`
- `get_current_user` dependency is the single auth enforcement point — used consistently
- `build_profile_update` centralizes column whitelisting in SQL layer
- SQL constants in `queries.py` — no inline SQL in business logic
- `StreamBuffer` ownership isolated in `stream_manager.py`

### Weaknesses

1. **Parallel non-streaming and streaming paths.** `POST /api/send_message` and `POST /api/send_message_stream` maintain separate code paths through `ConversationService`. Any orchestrator change must be tested against both. The non-streaming path should be a thin wrapper or eliminated.

2. **God endpoint: `GET /api/profile`.** Reads profile, active session, 50 messages, and all provider configs in four sequential DB calls. Called on every page load. Performance bottleneck; impossible to cache or paginate individually.

3. **Overlap between `GET /api/config` and `GET /api/profile`.** Both return model parameters and provider info. Two sources of truth for the same data.

4. **`_extract_keyrings` is defined in `chat.py` and imported by `memory.py` and `profile.py`.** A utility defined in an endpoint file being imported by other endpoint files is a layering violation. Should live in `app/api/utils.py`.

5. **`get_client_id` produces an unstable identifier.** Derived from `client_host + user_agent_hash`. Not stable across IP changes (mobile users, VPNs). Used for `SessionService` state management, not just logging.

6. **No shared response model base class.** Every endpoint defines its own ad-hoc response shape.

7. **`POST /api/sessions/switch` has side effects.** Calls `SessionService.start_session_async` (writes a system event to DB) on every tab switch. This is a side effect on what should be a data retrieval operation.

---

## 14. Performance Review

Evidence-based findings only.

### Sequential DB Reads on Every Page Load

`GET /api/profile` issues four sequential DB round-trips:
1. `get_profile_async`
2. `get_active_session_async`
3. `get_chat_history_async`
4. `ConfigService.get_ai_providers_payload`

At 5 ms per call over a local socket: 20 ms minimum per page load. Over a remote DB this compounds with latency.

### Wasted Transfer on Session Switch

`POST /api/sessions/switch` returns 50 messages in the response body on every switch. For a client that already has history loaded, this is 50 × avg_message_size bytes of unnecessary transfer per switch.

### Unbounded History Load

`GET /api/chat_history` with `limit=0` calls `get_chat_history_async(limit=None)`. A session with thousands of messages loads all rows into process memory. This is documented as dangerous in `AGENTS.md` but the API still permits it with no admin gating.

### Blocking Long-Running Operations

`POST /api/rebuild_structured_memory` blocks the HTTP connection for the entire memory pipeline duration — potentially minutes for large sessions. No background job, no polling endpoint with a job ID.

### SSE Buffering Under nginx

No `Cache-Control: no-cache` or `X-Accel-Buffering: no` on `StreamingResponse`. Under nginx, chunks are buffered until the buffer fills, defeating the purpose of SSE and causing the client to see no tokens until a threshold is reached.

### No Provider Model List Caching

`GET /api/proxy/models/{provider}` makes a live `httpx` call to the external provider API on every request. No caching of model lists — frequently repeated calls (e.g., on config page load) each hit the provider's API.

---

## 15. Operational Readiness Review

### Logging

Structured logging via the `logging` module with `get_logger(__name__)` used consistently. No correlation ID or request ID attached to log lines — impossible to trace a request across service boundaries or correlate logs with client errors.

### Metrics

None. No Prometheus metrics, no StatsD, no `/metrics` endpoint. Request latency, error rate, and token usage are unobservable without log parsing.

### Tracing

None. No OpenTelemetry, no distributed trace headers propagated.

### Health Checks

`GET /health` always returns `{"status": "ok"}` with no DB check. A liveness probe that always passes is useless as a readiness indicator. A pod with a dead DB connection pool will pass the health check and continue receiving traffic.

`GET /health/ready` (Kubernetes readiness probe pattern) is absent.

### Graceful Shutdown

The lifespan context manager closes the async pool on shutdown. In-flight SSE connections are not drained — clients mid-stream receive an abrupt disconnect.

### Timeouts

No request timeout middleware. A hung LLM provider call holds an HTTP connection open indefinitely (uvicorn default: no timeout). `httpx` calls in `auth.py` and `profile.py` correctly set `timeout=15`. The SSE generator has no timeout.

### Background Jobs

Memory pipeline runs inline in the orchestrator. No task queue, no retry logic, no job visibility.

---

## 16. Test Coverage Review

26 test files, ~2,700 lines total.

### Covered

| Area | Test File |
|------|-----------|
| OAuth PKCE flow | `test_auth_oauth.py` |
| Health endpoint | `test_health_endpoint.py` |
| Tenant isolation SQL | `test_tenant_isolation.py` |
| DB query structure | `test_db_queries.py` |
| Graph memory | `test_graph_memory.py` |
| FC orchestrator loop | `test_fc_orchestrator.py` |
| Provider protocol | `test_fc_provider.py`, `test_openai_protocol.py` |
| Streaming contract | `test_fc_streaming.py`, `test_stream_continuation_contract.py` |
| Prompt assembly | `test_prompts_runtime.py` |
| Shell exec sandboxing | `test_shell_exec.py` |
| Image provider payload | `test_image_provider_payload.py` |
| Presets | `test_phase2_presets.py` |

### Not Covered

| Missing Test Area | Risk |
|-------------------|------|
| `POST /api/send_message` success, error, BYOK paths | No integration coverage of primary endpoint |
| `POST /api/send_message_stream` SSE envelope, image upload, error SSE | No streaming integration test |
| `POST /api/update_profile` field acceptance/rejection, oversized payload | Mass assignment risk untested |
| `GET /api/proxy/models/{provider}` SSRF scenario | Critical security gap untested |
| `POST /api/sessions/delete` wrong HTTP method | Semantics bug untested |
| File upload content-type validation | Feature does not exist, so untested |
| HTTP rate limiting | Feature does not exist, so untested |
| Security headers | Feature does not exist, so untested |
| `GET /api/chat_history` with `limit=0` OOM risk | High-impact path untested |
| Session switch DB side effects | Untested |
| Auth callback redirect URL construction with malicious `origin` | SEC-04 untested |

---

## 17. Versioning Review

### Current State

No versioning. All routes are unversioned. `version="1.0.0"` in `FastAPI()` is metadata only.

### Risk

Any breaking change to request/response shape, authentication, or route paths immediately breaks all consumers with no migration path.

### Recommended Strategy for Stable Release

1. Prefix all public routes with `/v1/`
2. Keep `/health` and `/health/ready` unversioned
3. Introduce `Deprecation` and `Sunset` response headers when a v1 endpoint is replaced
4. Never remove or rename fields from a v1 response — only add new optional fields
5. Mark experimental endpoints with `X-Yuzu-Stability: experimental` response header
6. Maintain a `CHANGELOG.md` with API change entries

---

## 18. Breaking Change Risks

If `/v1/` is introduced, these current behaviors constitute pre-existing risks that must be resolved before freezing the contract:

| Risk | Detail |
|------|--------|
| Timestamp format | `str(datetime)` is not ISO 8601 and not stable across Python versions |
| `GET /api/profile` fat payload | Splitting into focused endpoints breaks frontend code that destructures the combined blob |
| LLM error as HTTP 200 | Clients checking status code miss errors; fixing returns 502/503 which is a breaking change |
| BYOK header format | Undocumented; cannot be versioned without prior documentation |
| `POST /api/sessions/delete` | Changing to `DELETE /api/sessions/{id}` breaks all existing callers |
| `PATCH /api/global-knowledge/{id}` | Fixing to true partial update changes required fields |

---

## 19. Prioritized Recommendations

### P0 — Critical (must fix before any external exposure)

| ID | Issue | Evidence | Effort |
|----|-------|----------|--------|
| P0-1 | Add security headers middleware | Zero results for `X-Content-Type-Options` in codebase | 2h |
| P0-2 | Fix SSRF in proxy model endpoints | `profile.py:193` — unvalidated `base_url` in outbound request | 4h |
| P0-3 | Add authentication to `/api/static/uploads/{filename}` | `static.py:14` — no `Depends(get_current_user)` | 3h |
| P0-4 | Add file upload content-type and size validation | `chat.py:112` — `UploadFile` with no validation | 2h |
| P0-5 | Fix LLM errors returned as HTTP 200 | `chat.py:99-101`, `chat.py:203` | 1h |

### P1 — High (strongly recommended before public release)

| ID | Issue | Evidence | Effort |
|----|-------|----------|--------|
| P1-1 | Implement HTTP rate limiting | No rate limiter in `pyproject.toml` | 4h |
| P1-2 | Add `/v1/` version prefix to all public routes | All routes unversioned | 2h + frontend |
| P1-3 | Fix open redirect in OAuth callback | `auth.py:192` — `urljoin(origin, "/chat")` | 1h |
| P1-4 | Add SSE headers to streaming response | No `Cache-Control`/`X-Accel-Buffering` | 30m |
| P1-5 | Implement `/health/ready` with DB check | `health.py` — always returns ok | 1h |
| P1-6 | Replace `dict[str, object]` in `update_profile` with typed model | `profile.py:43` | 3h |
| P1-7 | Add `response_model` to all endpoints | All endpoints return untyped `Any` | 8h |

### P2 — Medium

| ID | Issue | Evidence | Effort |
|----|-------|----------|--------|
| P2-1 | Fix `PATCH /global-knowledge/{id}` to accept partial updates | Requires all fields currently | 1h |
| P2-2 | Change `POST /sessions/delete` to `DELETE /sessions/{id}` | Wrong HTTP method | 2h |
| P2-3 | Change `POST /presets/delete` to `DELETE /presets/{name}` | Wrong HTTP method | 1h |
| P2-4 | Move `_extract_keyrings` to `app/api/utils.py` | Defined in endpoint, imported across endpoints | 30m |
| P2-5 | Split `GET /api/profile` into focused endpoints | 4 sequential DB reads per page load | 4h |
| P2-6 | Add `before_ts` format validation | Raw string passed to DB | 30m |
| P2-7 | Set `include_in_schema=False` on 12 internal endpoints | All internal ops visible in public schema | 1h |
| P2-8 | Add request timeout middleware | No timeout on any endpoint | 2h |
| P2-9 | Fix 1×1 SVG fallback to return 404 | `static.py:41` | 15m |
| P2-10 | Gate `limit=0` in `GET /api/chat_history` behind admin header | `sessions.py:55` | 30m |

### P3 — Low

| ID | Issue | Evidence | Effort |
|----|-------|----------|--------|
| P3-1 | Add request correlation ID middleware | No request ID in any log line | 2h |
| P3-2 | Add `operation_id` overrides to all routes | Auto-generated verbose IDs | 2h |
| P3-3 | Standardize error envelope to RFC 9457 Problem Details | Three incompatible error shapes | 4h |
| P3-4 | Add SSE keepalive comments | No keepalive; long silences close connections | 1h |
| P3-5 | Remove `POST /api/generate_image` alias endpoint | Alias for `/imagine` prefix hack | 30m |
| P3-6 | Remove duplicate static serving paths | Router + StaticFiles mount both serve same dirs | 30m |
| P3-7 | Add Prometheus metrics middleware | No metrics endpoint | 4h |
| P3-8 | Add `.yuzuki/` to `.gitignore` | Backup SQL with chat history tracked in repo | 5m |

---

## 20. Suggested Roadmap

### Sprint 0 — Security Hardening (before any external exposure)

Resolve P0-1 through P0-5. These are non-negotiable before the app is accessible beyond localhost or a trusted internal network.

**Deliverables:**
- Security headers middleware active on all responses
- SSRF mitigations on proxy model endpoints
- Authenticated file serving for uploads
- Upload content-type and size validation
- LLM errors propagated as proper 5xx status codes

### Sprint 1 — API Stability

Resolve P1-1 through P1-5.

**Deliverables:**
- Per-user rate limiting on stream endpoint
- `/v1/` prefix on all public routes
- Auth callback redirect confined to internal paths
- SSE response headers set correctly
- `/health/ready` endpoint with DB probe

### Sprint 2 — Schema Completeness

Resolve P1-6, P1-7, P2-6, P2-7.

**Deliverables:**
- Typed `response_model` on all endpoints
- Typed `ProfilePatchRequest` replacing `dict[str, object]`
- `before_ts` format validation
- Internal endpoints hidden from OpenAPI schema

### Sprint 3 — REST Correctness

Resolve P2-1 through P2-5.

**Deliverables:**
- DELETE methods for session and preset deletion
- True PATCH semantics for global-knowledge
- `_extract_keyrings` relocated to utils
- `GET /api/profile` split into focused endpoints
- Timeout middleware active

### Sprint 4 — Observability

Resolve P2-8, P3-1, P3-7.

**Deliverables:**
- Request timeout middleware
- Correlation ID in every log line and response header
- Prometheus metrics endpoint

### Sprint 5 — Developer Experience

Resolve P3-2, P3-3, P3-4, P3-5, P3-6, P3-8 plus documentation pass.

**Deliverables:**
- RFC 9457 error envelope
- Operation ID overrides for SDK generation
- SSE event format documented
- BYOK header format documented
- Alias and duplicate endpoints removed
- `.yuzuki/` in `.gitignore`

---

*End of audit report.*
