# Shared API contract

**Status:** Active reference. Code is authoritative — this document describes the current implementation in `main.py` and `app/api/`, and it must be updated in the same change that alters either side of the boundary.

The HTTP and SSE contract between the frontend (Jinja pages and the Vite SPA under `web/`) and the backend. Both deployable units — the SPA on a static host and the API-only FastAPI backend — speak this single contract. It must not change as part of the frontend/backend split.

Consumers: [`../backend/README.md`](../backend/README.md) (backend-side reading), [`../../web/README.md`](../../web/README.md) (frontend-side reading), and the migration spec [`../specs/frontend-split-migration.md`](../specs/frontend-split-migration.md). The backend is the contract owner; the browser is the only consumer.

## Conventions

- Base path: `/api/v1`. Health and metrics stay unversioned.
- Success responses are JSON; write endpoints commonly return `{"status": "success", ...}`.
- Errors are RFC 9457 `application/problem+json` bodies via `app/api/errors.py` (`ProblemDetail`: `type`, `title`, `status`, `detail`, `instance`, `request_id`, optional `errors`).
- The machine-readable reference is `GET /openapi.json` (docs UI stays disabled).
- All `/api/v1` routes require the session cookie except the auth login/callback routes and provider discovery endpoints that accept an explicit `X-Provider-Key` header.

## Authentication and session

- **Session cookie** `yuzu_session` (HttpOnly). Attributes: `Secure` from `COOKIE_SECURE` (default true), `SameSite` from `COOKIE_SAMESITE` (default `lax`). Cross-site SPA deployments set `COOKIE_SAMESITE=none` together with `COOKIE_SECURE=true`; local single-origin mode keeps the defaults.
- **Boot identity:** `GET /api/v1/auth/me` → `AuthMeResponse` (`user_id`, `email`, `user_name`, `avatar_url`). The SPA resolves its storage namespace (`user_{user_id}_*`) from `user_id` instead of a server-rendered meta tag.
- **OAuth:** `GET /api/v1/auth/login?provider=google|github` redirects to the provider; `GET /api/v1/auth/callback` (hidden from OpenAPI) exchanges the code, sets the session cookie, and redirects back to the referer origin (cross-origin capable). `POST /api/v1/auth/logout` clears the cookie.
- **401/403** on any `/api/v1` route redirects the SPA to `/login` (the `apiFetch` auth gate).

## Request headers

| Header | Used on | Meaning |
|---|---|---|
| `X-BYOK-Config` | LLM endpoints (`send_message`, `send_message_stream`, `generate_image`) | Base64url-ish BYOK payload (see below). Bounded at 64 KB; larger sends 413. |
| `X-Provider-Key` | provider discovery/test endpoints | Provider API key for server-side model refresh and connection tests. |
| `X-Provider-BaseUrl` | provider discovery/test endpoints | Custom provider base URL (custom providers only). |
| `X-Client-Timezone` / `X-Client-Local-Time` | LLM endpoints | Client time context for prompt building. |

CORS (when `CORS_ORIGINS` is set) allows credentials plus these headers; the default preserves the legacy same-origin policy.

### BYOK encoding

The browser keeps provider keys per user in `localStorage` under `user_{user_id}_api_keys` as `{"providers": {provider: {api_key, base_url?, model_id?}}}`. The header value is:

```text
base64(encodeURIComponent(JSON.stringify({providers: {...}})))
```

The backend decodes it into request-scoped keyrings; keys are never persisted server-side and never leave the browser except in this per-request header.

## SSE streaming contract

`POST /api/v1/send_message_stream` accepts multipart form (text `message` + optional `images[]`) or JSON, and returns `text/event-stream`. Each event is a `data:` line carrying a JSON object. `: heartbeat` comment lines are sent while waiting and must be ignored by clients. On client disconnect the backend cancels the generation and cleans up the buffer.

| `type` | Shape | Meaning |
|---|---|---|
| `token` | `{"type": "token", "content": "...", "turn_id": "..."}` | Text delta appended to the active assistant bubble. |
| `tool_call` | `{"type": "tool_call", "data": {"event": "tool_call", "id", "name", "arguments", "turn_id"}}` | Model requested a tool; `id` is the provider call ID (generated if absent). |
| `tool_result` | `{"type": "tool_result", "data": {"event": "tool_result", "call_id", "name", "ok", "data", "turn_id", "error"?}}` | Tool execution outcome; `call_id` matches the preceding `tool_call` id. |
| `error` | `{"type": "error", "message": "..."}` | Stream failed; terminal. |
| `done` | `{"type": "done", "turn_id": "..."}` | Turn complete; terminal. |

`turn_id` correlates every event of one orchestrator turn. The frontend treats `done` and a clean EOF as equivalent terminal paths (client-side cancellation aborts the fetch and freezes the partial bubble). Tool payloads are validated client-side by the schema module; invalid payloads render a safe generic card.

Non-streaming `POST /api/v1/send_message` returns `MessageResponse` (`reply`, `status`) with the same tool-loop semantics.

## HTTP endpoint groups

| Group | Paths | Notes |
|---|---|---|
| Auth | `/api/v1/auth/login`, `/api/v1/auth/callback`, `/api/v1/auth/logout`, `/api/v1/auth/me` | The callback is hidden from OpenAPI; it lives only at `/api/v1/auth/callback`. |
| Chat | `/api/v1/send_message`, `/api/v1/send_message_stream`, `/api/v1/generate_image`, `/api/v1/browser_unload` | Stream uses the SSE contract above. |
| Sessions | `/api/v1/chat_history`, `/api/v1/chat_history/before` (ISO-8601 cursor pagination), `/api/v1/sessions/list`, `/create`, `/switch`, `/rename`, `/delete`, `/api/v1/sessions/{session_id}`, `/api/v1/clear_chat`, `/api/v1/end_session` | `chat_history/before` supports `has_more`/cursor paging; `clear_chat` clears the active session; `end_session` ends the active client session. |
| Profile/config | `/api/v1/config`, `/api/v1/profile`, `/api/v1/update_profile`, `/api/v1/update_location`, `/api/v1/global-knowledge*` (list/create/update/delete) | `GET /api/v1/config` is the single source of truth: `profile`, `ai_providers`, `all_models`, `model_infos`, `current_provider`, `current_model`. |
| Providers | `/api/v1/providers/list`, `/api/v1/providers/set_preferred`, `/api/v1/providers/test_connection`, `/api/v1/proxy/models/{provider}` and `/refresh` | Discovery requires `X-Provider-Key` (and `X-Provider-BaseUrl` for custom providers); `model_infos` carries capability/limits metadata. |
| Memory | `/api/v1/memory_stats`, `/api/v1/rebuild_structured_memory` | Graph-memory tenant stats and explicit rebuild; both hidden from OpenAPI. |
| Presets | `/api/v1/presets/list`, `/api/v1/presets/upsert`, `/api/v1/presets/activate`, `/api/v1/presets/{name}` | Active preset resolution drives generation parameters. |
| Stream recovery | `/api/v1/stream/{session_id}/status`, `/api/v1/stream/{session_id}/sync` | Reconcile client state with the server-side stream buffer. |
| Private images | `/api/v1/static/uploads/{filename}`, `/api/v1/static/generated_images/{filename}` | Authenticated; never served by a public mount. Clients rewrite message image paths via `safeImagePath()`. |
| Health/metrics | `GET/HEAD /health`, `GET /health/ready`, `/metrics` | Unversioned infrastructure probes; not SPA concerns. |

Routes marked `include_in_schema=False` are excluded from OpenAPI but are live: the POST compatibility aliases for deletions, the `/proxy/models/*` discovery routes, `/providers/test_connection`, `/generate_image`, `/browser_unload`, the `/stream/*` recovery routes, `/memory_stats` + `/rebuild_structured_memory`, and the OAuth callback. `GET /openapi.json` lists only the schema-visible subset. There is no separate `/api/auth/*` mount — the callback lives only at `/api/v1/auth/callback`.

## Serving modes

The same backend binary serves three modes, selected by env:

| Mode | Env | Behavior |
|---|---|---|
| Jinja UI (default) | `SERVE_WEB_UI=true`, `SERVE_SPA=false` | Page routes render `templates/`; `/static` mounts the legacy assets. |
| SPA (local single-origin) | `SERVE_WEB_UI=true`, `SERVE_SPA=true` | Page routes serve the built `web/dist` (must exist; `npm --prefix web run build`); `/assets` mounts the built bundle. No CORS/SameSite changes needed. |
| API-only | `SERVE_WEB_UI=false` | Only `/api/v1`, health, metrics, and private-image routes; page routes and the public `/static` mount are removed. |

## Related references

- [`../backend/README.md`](../backend/README.md) — backend ownership and services
- [`../../web/README.md`](../../web/README.md) — frontend ownership and API consumption
- [`../frontend/README.md`](../frontend/README.md) — legacy frontend architecture
- [`../specs/frontend-split-migration.md`](../specs/frontend-split-migration.md) — migration plan (not a contract reference)
- [`../../AGENTS.md`](../../AGENTS.md) — repository invariants
