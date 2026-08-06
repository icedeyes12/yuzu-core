# Yuzu Companion

Yuzu Companion is a private AI companion application with persistent conversation history, graph-backed memory, multimodal input, native provider function calling, and web and terminal clients.

## Runtime at a glance

- **Backend:** Python 3.12+, FastAPI, Uvicorn
- **Persistence:** PostgreSQL through psycopg v3, with pgvector and pg_trgm
- **Web UI:** Jinja2 templates with vanilla JavaScript and CSS
- **CLI:** Rich + prompt-toolkit inline REPL using HTTP/SSE
- **Providers:** OpenRouter, OpenAI, Anthropic, Google, Grok, Groq, Cerebras, DeepSeek, Chutes, Yuzu Portal, and custom OpenAI/Anthropic-compatible endpoints
- **Memory:** asynchronous graph extraction into episodes, nodes, edges, and evidence
- **Tool protocol:** native provider function calling through `app/tools/registry.py`

## Quick start

### Prerequisites

- Python 3.12 or newer
- PostgreSQL with `pgcrypto`, `pgvector`, and `pg_trgm`
- Node.js 22 and Bun for the frontend checks
- Provider credentials and OAuth credentials as needed

### Install

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` with PostgreSQL, encryption, session, provider, and OAuth values. Never commit `.env` or real secrets.

### Run

```bash
python main.py
```

The server listens on `http://127.0.0.1:5000` by default. The console entry point is also available after installation:

```bash
yuzu-server
```

The CLI is a separate client of the backend:

```bash
yuzu
# Optional backend override
YUZU_BACKEND_URL=http://127.0.0.1:5000 yuzu
```

## Repository map

```text
main.py                 FastAPI application and HTML routes
app/api/                Versioned HTTP routers and API contracts
app/services/           Orchestration and application workflows
app/providers/          External AI provider clients
app/core/               Shared runtime, security, configuration, and multimodal helpers
app/db/                 psycopg pools, facade, queries, and schema bootstrap
app/memory/             Graph extraction, persistence, and retrieval
app/tools/              Native tool definitions and central dispatch
cli/                    HTTP/SSE terminal REPL
static/                 Browser JavaScript, CSS, and vendored runtime assets
templates/              Jinja2 pages and partials
docs/                   Maintained architecture and operational documentation
tests/                  Unit, contract, integration, regression, and frontend checks
```

## Documentation

Start at [`docs/README.md`](docs/README.md). It defines the documentation taxonomy and maintenance rules. Active technical references are organized under `docs/architecture/`, `docs/backend/`, `docs/database/`, `docs/memory/`, and `docs/frontend/`.

The root `AGENTS.md` is the development operating guide. It includes the documentation governance rules that agents must follow.

## Quality checks

Run the checks used by CI before submitting changes:

```bash
ruff format --check .
ruff check .
find static -type f -name '*.js' -exec node --check {} +
bunx biome check static/
pytest
```

CodeQL scans Python and JavaScript/TypeScript in a separate workflow.

## Security

- Provider keys use request-scoped browser BYOK data and are not stored server-side.
- Tenant-scoped database operations must carry `user_id`.
- Uploaded and generated images are served through authenticated API routes.
- Do not expose secrets in logs or commits.

See [`SECURITY.md`](SECURITY.md) for vulnerability reporting and [`CONTRIBUTING.md`](CONTRIBUTING.md) for contribution workflow.

## License

MIT. See [`LICENSE`](LICENSE).
