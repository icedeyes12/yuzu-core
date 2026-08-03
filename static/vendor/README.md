# Vendored Frontend Assets

This directory contains the third-party frontend assets required at runtime.
Assets are served locally to keep the chat UI independent of external CDNs and compatible with the same-origin CSP.

## Libraries

- marked 18.0.7 — `marked/marked.umd.js`
- mermaid 11.4.0 — `mermaid/mermaid.min.js`
- KaTeX 0.16.11 — `katex/katex.min.js`, `katex/auto-render.min.js`, `katex/katex.min.css`, and `katex/fonts/`
- Highlight.js 11.11.1 — `highlight.js/highlight.min.js`, `highlight.js/tomorrow-night-blue.min.css`, and the runtime language modules:
  - Python
  - JavaScript
  - Bash
  - JSON

Only runtime assets belong here. Do not copy development bundles, source maps, or unused language modules without a runtime reference.

## Updating

1. Update the dependency version in the repository root `package.json`.
2. Run `npm install` to refresh `package-lock.json`.
3. Copy only the required runtime assets into this directory.
4. Verify references in `templates/chat.html`, `window.hljs`, `highlightElement()`, the marked/fence renderer, Mermaid, and inspect views.
5. Run the frontend regression checks, `pytest`, `ruff check .`, and `ruff format --check .`.
6. Confirm the Content-Security-Policy still allows only the intended same-origin assets.

Keep `package.json`, `package-lock.json`, and the versions documented here consistent with the authoritative project metadata in `pyproject.toml`.

## Runtime contract

- Highlight.js must load before `static/js/chat.js`.
- Tool-generated images must use authenticated API paths under `/api/v1/static/`.
- Mermaid and HTML fence blocks use buffered rendering; their inspect source views use Highlight.js.
- Do not replace local assets with CDN URLs unless the CSP and offline-runtime requirements are intentionally changed.

License and attribution remain with each vendored library. See the corresponding upstream package metadata for full license text.

---

Update verification command:

```sh
node tests/frontend/test_safe_image_path.mjs
```

Then run the full project checks listed above.
