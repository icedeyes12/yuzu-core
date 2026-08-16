# ADR 0007: Split the web UI into a Vite SPA and an API-only backend

- Status: Accepted
- Date: 2026-08-15

## Context

The web UI is served by the FastAPI backend through Jinja templates plus a `static/` directory of vanilla JavaScript and CSS. The interactive surface already runs on the `/api/v1` HTTP and SSE contract, but page rendering, asset delivery, and server-rendered state (user id meta tags, inline profile values, sidebar includes) are coupled to the backend. Deploying the UI requires deploying the whole Python application, and the UI cannot be served from a static host.

## Decision

Split the web UI into two independently deployable units while keeping the existing `/api/v1` HTTP/SSE contract as the shared boundary:

- **Frontend:** a Vite-built SPA (vanilla ES modules, multi-page entries) under `web/`, deployable to Cloudflare Pages or any static host. It is a pure consumer of the API: session cookie, per-user `localStorage` (BYOK keys, theme), and `/api/v1` calls only.
- **Backend:** the existing FastAPI application, runnable in API-only mode. It owns database access, provider calls, streaming, memory, tool dispatch, auth, and private image storage.

The migration is incremental and the contract never changes as part of the split. Env flags select the serving mode with default-preserving behavior:

- `SERVE_WEB_UI` (default true) — `false` removes the HTML page routes and the public `/static` mount, keeping `/api/v1`, health, metrics, and authenticated image routes.
- `SERVE_SPA` (default false, requires `SERVE_WEB_UI=true`) — page routes serve the built SPA from `web/dist` (local single-origin mode, no CORS/SameSite changes).
- `CORS_ORIGINS` and `COOKIE_SAMESITE` — opt-in cross-origin support for a static-hosted SPA; unset defaults preserve the legacy same-origin policy.

Provider keys remain browser-only BYOK data in `user_{user_id}_api_keys` carried per request in the bounded `X-BYOK-Config` header; no server-side key persistence is introduced.

## Consequences

- Both the Jinja stack and the SPA are maintained during the transition; Jinja pages keep working until each SPA replacement is verified. This is a deliberate dual-stack cost.
- The shared `/api/v1` contract is the single boundary between the units and is documented once in `docs/api/contract.md`; it is an invariant that neither side changes unilaterally.
- The SPA resolves its per-user storage namespace from `GET /api/v1/auth/me` instead of server-rendered state.
- Local Termux/proot deployments stay fully functional without Cloudflare by serving the built SPA from the backend in single-origin mode.
- The backend can eventually drop templates and public UI assets after the flip is complete, but that removal is a separate change gated by the same flags.

## Supersedes

None.
