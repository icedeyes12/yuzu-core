# Yuzu Core — Backend Agent Guide

Compact routing index and operating rules for backend development. Code and executable configurations are authoritative.

## ⚙️ Backend Runtime & Architecture

- **Runtime:** Python 3.12+, FastAPI, Uvicorn; `main.py` is the ASGI entry point.
- **Router Prefix:** Strictly versioned under `/v1` (`/v1/chat_history`, `/v1/send_message_stream`, `/v1/auth/*`).
- **Database Access:** PostgreSQL 18 via `psycopg` v3 async connection pool.
- **Extensions:** `pgcrypto`, `vector`, `pg_trgm`.
- **Memory Engine:** Graph-memory pipelines in `app/memory/` and `app/db/queries.py`.
- **Tool Protocol:** Native provider `tool_calls` dispatched strictly via `app/tools/registry.py`.

## 🛡️ Non-Negotiable Invariants

1. All tenant-scoped database queries and graph operations **MUST filter by `user_id`**.
2. Never format Markdown, HTML, or UI presentation in backend tools — tools return pure structured data.
3. Keep the orchestrator loop bounded (`_MAX_ORCHESTRATION_LOOPS = 4`).
4. Endpoints are transport only; orchestration logic belongs strictly in the Application/Services layer.
5. All IDs exposed to URLs/clients use Base62 Typed IDs (`ses_...`, `usr_...`) via `app/core/ids.py`.
6. Public module/function docstrings contain exactly one kaomoji and no human-readable prose.

## 🧪 Validation

```bash
ruff check .
ruff format --check .
pytest tests/ -k "not integration and not live" -q
```
