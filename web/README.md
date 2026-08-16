# web/ — Vite SPA

**Status:** Active ownership contract for the Vite-built single-page application.

This directory is the canonical frontend directory. The SPA is a pure consumer of the backend HTTP/SSE contract and is independently deployable to any static host (e.g. Cloudflare Pages) or served locally by the backend in single-origin mode (`SERVE_WEB_UI=true`, `SERVE_SPA=true`).

## Build and run

```bash
npm ci          # install (lockfile is committed)
npm run build   # outputs web/dist (gitignored; backend SPA mode requires it)
npm run dev     # Vite dev server; proxies /api/v1 to the local backend
```

## Structure

| Path | Ownership |
|---|---|
| `src/main.js` | Entry per page; boots auth, store, renderer, router |
| `src/pages/` | Page coordinators: `login`, `home`, `chat`, `config`, `about` |
| `src/modules/store.js` | `ConversationStore` — the only owner of conversation state |
| `src/modules/store-renderer.js` | `DOMRenderer` — the only owner of chat message DOM |
| `src/modules/event-router.js` | SSE decoding into store mutations; stream lifecycle and cancellation |
| `src/modules/apiFetch.js` | Fetch wrapper: API base (`VITE_API_BASE`), `credentials: "include"`, `X-BYOK-Config` injection, 401 auth gate |
| `src/modules/clientStorage.js` | User-scoped `localStorage` namespaces, BYOK encoding, key masking |
| `src/modules/provider-registry.js` | Static provider branding only (no network, no state) |
| `src/styles/` | CSS (Vite imports; `marked.css` is the vendored Markdown theme) |
| `public/` | Static assets copied verbatim into the build |

## Shared contract

The SPA consumes the backend's HTTP and SSE contract exactly as documented in [`../docs/api/contract.md`](../docs/api/contract.md). That document is the single source of truth for routes, request headers, BYOK encoding, error format, and the SSE event types; do not duplicate its content here or in page code.

Frontend rules that keep the contract intact:

- Conversation state changes go through `ConversationStore`; chat DOM changes through `DOMRenderer`. Never insert messages directly.
- The BYOK key payload (`user_{user_id}_api_keys`) is the only key store; keys travel per-request in `X-BYOK-Config` and are masked in the config UI (never echoed or stored elsewhere).
- Provider/model capability state comes from `GET /api/v1/config` (`model_infos`) and provider discovery responses; `provider-registry.js` is branding only.
- Private image paths are rewritten to the authenticated `/api/v1/static/...` routes; the SPA never references a public image mount.
- Do not change backend contracts as part of a frontend change.

## Validation

Run `node --check` on changed `src/` files, `npx @biomejs/biome check src/`, then `npm run build`. The CI workflow runs the full set plus the `tests/frontend/` smoke tests and the Playwright E2E suite.

## Related references

- [`../docs/api/contract.md`](../docs/api/contract.md) — the shared API contract
- [`../docs/frontend/README.md`](../docs/frontend/README.md) — legacy frontend architecture
- [`../docs/specs/frontend-split-migration.md`](../docs/specs/frontend-split-migration.md) — the split migration plan
- [`../AGENTS.md`](../AGENTS.md) — repository invariants
