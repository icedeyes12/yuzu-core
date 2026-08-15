# Spec: Frontend/backend split migration

Status: Draft (Active Development)
Target: v4.4
Component: Web UI + API boundary

## Overview

Split Yuzu Companion into two independently deployable units:

- **Frontend:** a Vite-built SPA (vanilla ES modules, multi-page entries) deployable to Cloudflare Pages or any static host.
- **Backend:** the existing FastAPI application in API-only mode, independently runnable locally (Termux/proot) without Cloudflare.

The migration is incremental. The backend keeps serving the current Jinja pages and public static assets until the SPA replaces them page by page, so the application never loses functionality mid-migration. The HTTP contract (`/api/v1` JSON, SSE event types, RFC 9457 errors) is the shared contract between the two units and must not change as part of this split.

## Target architecture

```text
Browser
  -> Vite SPA (web/)                  -> FastAPI API-only (backend, /api/v1)
  -> static assets (built by Vite)      -> PostgreSQL + provider clients
  -> BYOK keys (localStorage)           -> authenticated image routes
  -> OAuth redirect flow                -> session cookie
```

- The SPA is a pure consumer of the API. It holds no server state except the session cookie and user-scoped browser storage.
- The backend owns database access, provider calls, streaming, memory, tool dispatch, auth, and private image storage.
- Local single-origin mode: the backend serves the built SPA from `web/dist` as static files. No Cloudflare required.

## Current boundary inventory (verified against code)

### Already decoupled (runtime-fetched)

The interactive surface already runs on the API with cookie auth (`yuzu_session`):

- **Config/provider/model discovery:** `GET /api/v1/config`, `GET /api/v1/providers/list`, `GET /api/v1/proxy/models/{provider}` and `/refresh` (with `X-Provider-Key` / `X-Provider-BaseUrl` headers), `POST /api/v1/providers/set_preferred`, `POST /api/v1/providers/test_connection`. `model_infos` capability metadata is server-discovered and consumed from the API; `provider-registry.js` is static branding only.
- **Chat/streaming:** `POST /api/v1/send_message_stream` (multipart form with text + images, or JSON) returns SSE parsed client-side with fetch `ReadableStream`; `event-router.js` validates event shapes. Non-streaming `POST /api/v1/send_message`, image generation, `browser_unload`.
- **Sessions:** list/create/switch/rename/delete, `chat_history`, `chat_history/before` (pagination cursor), `clear_chat`, `end_session`.
- **Auth:** `GET /api/v1/auth/login?provider=google|github` (OAuth redirect), `/callback` (redirects back to the referer origin — already cross-origin capable), `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`.
- **Profile:** `GET/POST /api/v1/profile`, `/update_profile`, `/update_location`, `global-knowledge` CRUD, presets.
- **Stream recovery:** `GET /api/v1/stream/{session_id}/status` and `/sync`.
- **Private images:** authenticated `GET /api/v1/static/uploads/{filename}` and `/generated_images/{filename}`. `safeImagePath()` in `tool-renderer/dom-utils.js` rewrites message image paths to these routes.
- **Health/metrics:** unversioned `/health`, `/health/ready`, `/metrics` (backend-owned; not SPA concerns).

### Server-rendered coupling to sever

| Coupling | Where | SPA replacement |
|---|---|---|
| `<meta name="user-id">` | chat/index/config/about templates | Fetch `GET /api/v1/auth/me` on boot; derive the storage namespace `user_{user_id}` |
| User-scoped localStorage keys | `static/js/client-storage.js` (BYOK `user_{id}_api_keys`, theme `user_{id}_theme`, `getUserStorageKey()` for config `provider_models` cache) | Same key names, resolved lazily after `/me`; make module state mutable instead of evaluating at import |
| Inline profile values (`partner_name`, `affection`, `user_name`) | chat/index/config templates | Fetch `/api/v1/profile` / `/api/v1/config` (chat.js already re-fetches and patches the header) |
| `current_page` + `sidebar.html` include | all templates | Client-side route state and an SPA sidebar component |
| `url_for('static', ...)` asset URLs | all templates | Vite asset handling; vendored libs (`marked`, `katex`, `mermaid`, `highlight.js`) imported through npm (already `package.json` dependencies) |
| `window.fetch` monkey-patch (BYOK header + 401 redirect) | `static/js/sidebar.js` | Dedicated `apiFetch` module in the SPA: API base URL, `credentials: "include"`, `X-BYOK-Config` injection, 401 auth gate |
| OAuth login buttons | `templates/login.html` | SPA login page linking to `{API}/api/v1/auth/login?provider=...` |

### Backend changes required (Phase 0 — additive, flag-gated)

1. **CORS:** replace the hardcoded `allow_origins=["https://yuzuki.space"]` with an env-driven comma-separated `CORS_ORIGINS` list; set `allow_credentials=True` when origins are configured; allow `POST`/`PUT`/`DELETE` methods and headers `X-BYOK-Config`, `X-Provider-Key`, `X-Provider-BaseUrl`, `X-Client-Timezone`, `X-Client-Local-Time`. Default preserves today's behavior.
2. **Session cookie:** `COOKIE_SAMESITE` env (default `lax`); cross-site SPA deployments set `none` with `COOKIE_SECURE=true`. The OAuth state cookie already uses `samesite=none` when secure.
3. **`SERVE_WEB_UI` flag** (default `true`): when `false`, disable HTML page routes and the public `/static` mount; keep `/api/v1`, health, metrics, and the private image routes.
4. **`SERVE_SPA` flag** (default `false`, requires `SERVE_WEB_UI=true`): when set, the page routes serve the built SPA from `web/dist` (built via `npm --prefix web run build`) instead of the Jinja templates — local single-origin mode. `dist` is gitignored, so the server raises a clear error if it is missing. Jinja remains the default until each page's SPA replacement is verified.

## Migration order

### Phase 0 — Contract prep (backend-only, no UI behavior change)

- CORS env expansion, `COOKIE_SAMESITE`, `SERVE_WEB_UI` flag (all default-preserving).
- Verify `/openapi.json` is served (docs UI stays disabled) as the machine-readable contract reference.
- Existing Jinja UI keeps working unchanged.

### Phase 1 — SPA shell

- New `web/` with Vite (vanilla, multi-page entries: login, home, chat, config, about).
- Port `static/` JS/CSS/assets into the SPA; vendor libs via npm imports.
- Add `apiFetch` module and the `/api/v1/auth/me` bootstrap for storage namespaces.
- Dev server proxies `/api/v1` to the local backend; `?session=` fallback in `router.js` covers chat deep links until path rewrites land.

### Phase 2 — Incremental page port (dual-stack)

Port pages in risk order: login → home/about → config → chat/sidebar/sessions/streaming. The Jinja pages remain served by the backend until their SPA replacements are verified, so the app never breaks. The chat port must keep `ConversationStore` → `DOMRenderer` as the only state/DOM path and `event-router.js` as the SSE normalization path.

### Phase 3 — Backend API-only mode

- `SERVE_WEB_UI=false` for the hosted API; local Termux/proot runs keep `SERVE_WEB_UI=true` and set `SERVE_SPA=true` to serve the built SPA from `web/dist` (same-origin, no CORS/SameSite complications, no Cloudflare).
- Remove Jinja templates and public static mounts once the SPA is the only UI.

### Phase 4 — Cloudflare Pages deployment (optional, no lock-in)

- Deploy the built SPA to Pages; add `_redirects` so `/chat/{session_id}` and other paths resolve to the SPA entries.
- Configure the API base URL via build-time env (`VITE_API_BASE`).
- Backend: `COOKIE_SAMESITE=none`, `COOKIE_SECURE=true`, `CORS_ORIGINS` including the Pages origin.

### Phase 5 — Cleanup and documentation

- Delete `templates/` and public `static/` UI assets after the flip; keep `static/uploads`, `generated_images`, `image_cache` behind the API routes.
- Add an ADR for the split; update `docs/architecture`, `docs/frontend`, `docs/backend`, `docs/README.md`, root `README.md`, `package.json` scripts, and CI (add `vite build` and frontend checks).

## Invariants that must survive the split

- Native provider `tool_calls` remain the only live tool protocol.
- All tenant-scoped database operations carry `user_id`.
- Provider keys stay browser-only BYOK (`X-BYOK-Config` header, bounded at 64 KB); no server-side key persistence.
- Private image directories are never served by a public static mount.
- Conversation state and chat DOM updates go through the store and renderer only.
- CLI (`cli/`) stays a separate HTTP/SSE client; it is unaffected and serves as a contract reference.

## Open items

- Post-login redirect path is hardcoded to `/chat` in the OAuth callback; keep `/chat` as the SPA route to avoid a backend change, or add a configurable redirect path later.
- Decide whether the SPA theme applies after `/me` resolves (small initial-paint flash on non-default themes) or reads an un-namespaced fallback key; existing per-user keys must remain authoritative.
- Cloudflare Pages path rewrite strategy for `/chat/*` deep links (Pages `_redirects` rewrite vs. keeping `?session=`).

## Related references

- [`../architecture/`](../architecture/)
- [`../backend/`](../backend/)
- [`../web/`](../web/)
- [`../README.md`](../README.md)
