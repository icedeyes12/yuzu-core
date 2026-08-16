# Yuzu Companion — Agent Operating Guide

Compact routing index for code and documentation work. Code and executable configuration are authoritative; documentation must describe the current implementation, not planned behavior.

## Runtime and structure

- **Runtime:** Python 3.12+, FastAPI, Uvicorn; `main.py` is the ASGI entry point.
- **CLI:** `cli/app.py` is an inline Rich/prompt-toolkit REPL registered as `yuzu`.
- **Database:** PostgreSQL through psycopg v3 pools and raw SQL. Required extensions are `pgcrypto`, `vector`, and `pg_trgm`.
- **Schema authority:** `app/db/queries.py` owns `SCHEMA_DDL`, SQL constants, row parsers, and schema bootstrap statements.
- **Web UI:** Jinja2 templates with vanilla JavaScript and CSS under `templates/` and `static/`.
- **Graph memory:** `episodes`, `memory_nodes`, `memory_edges`, and `memory_evidence`; raw conversation remains in `messages`.
- **Embeddings:** Yuzu Portal request-scoped embedding calls use `gemini/gemini-embedding-2-preview` with dimension `1536`.

## Architectural compass

- `main.py` owns application lifespan, page routes, the public static mount, `/api/v1` router registration, and unversioned health/metrics routes.
- `app/api/` owns HTTP transport, authentication dependencies, request validation, response models, and error serialization.
- `app/services/orchestrator.py` is the canonical message execution path for streaming and non-streaming requests. Its orchestration loop is bounded by `_MAX_ORCHESTRATION_LOOPS = 4`.
- `app/services/llm_client.py` builds provider requests and dispatches through `AIProviderManager`.
- `app/providers/` owns external AI API clients and `ProviderCapabilities` declarations.
- `app/core/` owns shared runtime context, BYOK handling, configuration, encryption, logging, presets, and multimodal helpers.
- `app/tools/registry.py` is the only production tool-dispatch path. Tools return structured data and do not format Markdown or HTML.
- `app/services/stream_manager.py` owns active stream buffers, subscriber lifecycle, cancellation, and cleanup. Do not add another streaming stack.
- `app/memory/` owns asynchronous extraction, graph persistence, retrieval, embeddings, and provenance.
- `app/db/` owns pooled access and the `Database` facade. Tenant-scoped reads and writes must carry `user_id`.
- `static/js/modules/store.js` owns conversation state; `static/js/modules/store-renderer.js` owns conversation DOM. Do not bypass either with direct message insertion.

## Non-negotiable invariants

1. Native provider `tool_calls` are the only live tool protocol. Legacy markup is cleanup-only.
2. All tenant-scoped database operations filter by `user_id`; graph retrieval must preserve this boundary.
3. Active preset resolution is the runtime source for generation parameters when a preset is active.
4. Provider keys use browser BYOK storage (`yuzu_byok_config`) and the bounded `X-BYOK-Config` request header. Do not recreate an `api_keys` persistence path.
5. Uploaded and generated images are served through authenticated `/api/v1/static/...` routes; the public `/static` mount must not expose private image directories.
6. Image attachments are deduplicated before persistence and again during multimodal prompt construction.
7. Do not put provider HTTP calls in `app/tools/`, SQL/DDL in service code, or UI presentation in backend tool results.
8. Keep migrations additive unless an explicitly approved migration requires otherwise. Inspect the live schema and relevant tests before changing persistence.
9. Do not introduce `asyncio.run()` inside the async request path or create parallel ownership abstractions for existing state.
10. For Python source edits, public module/class/function docstrings contain exactly one kaomoji and no human-readable prose, per repository rules.

## Documentation governance

`docs/README.md` is the documentation index and audit record. Follow these rules:

- Read existing documentation before creating anything. Update the authoritative document first.
- Do not create a new Markdown file when an existing authoritative document can be updated; create one only when no appropriate location exists.
- Keep one authoritative document per concept. Merge duplicates; do not create parallel explanations.
- Documentation must be verified against current code, tests, routes, schemas, and configuration. If code and docs disagree, code wins and the docs are corrected.
- Keep active documentation concise and linked from `docs/README.md`.
- Move completed reports, superseded architecture, and historical plans to `docs/archive/` when they have historical value.
- Delete obsolete, duplicate, speculative, or empty documents with no historical value. Do not preserve material “just in case.”
- `docs/scratch/` is disposable and never a source of truth. Production documentation must not depend on it.
- Roadmaps describe future outcomes and constraints only. Do not use them as implementation reports or current architecture references.
- ADRs are immutable after acceptance. If a decision changes, add a new ADR that explicitly supersedes the old one; only correct an existing ADR when it is factually malformed.
- Package-local `README.md` files document local ownership and link to, rather than duplicate, the active references in `docs/`.
- Before delivery, run link/reference checks appropriate to the changed docs and inspect `git diff --check`.

## Validation commands

```bash
ruff format --check .
ruff check .
find static -type f -name '*.js' -exec node --check {} +
bunx @biomejs/biome check static/
pytest
```

Run the smallest relevant checks during iteration, then the full applicable set before commit or push. Never claim runtime behavior was verified when PostgreSQL or an external provider was unavailable.
