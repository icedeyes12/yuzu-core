# Backend Architecture

## Request Flow

```
Request → FastAPI (`main.py`) → Router (`app/api/main.py`) → Endpoint → Service → DB (`app/db/`)
```

### Entry Points

| File | Role |
|------|------|
| `app/web.py` | FastAPI app (~130 lines): mounts static files, includes API router, registers startup/shutdown |
| `main.py` | ASGI entry point for the FastAPI backend |
| `cli/app.py` | Inline async REPL using `rich` and `prompt_toolkit`; communicates with the backend through HTTP/SSE |

### Layer boundaries

The backend follows strict Separation of Concerns:

- `app/core/` contains cross-domain infrastructure such as encryption, configuration, runtime context, presets, and logging.
- `app/services/` contains business logic and orchestration.
- `app/providers/` contains all external API client execution, including image and embedding requests.
- `app/tools/` contains native function-calling schemas and structured dispatch only; it must not contain provider HTTP clients or UI formatting.

## Routing

`app/api/main.py` is the central router registry. It includes sub-routers from:

| Router | Path Prefix | Purpose |
|--------|-------------|---------|
| `app/api/static.py` | `/static/uploads`, `/static/generated` | File serving |
| `app/api/endpoints/chat.py` | `/api/send_message`, `/api/send_message_stream`, `/api/page_closed` | Chat & SSE |
| `app/api/endpoints/sessions.py` | `/api/sessions`, `/api/switch_session`, `/api/delete_session`, etc. | Session CRUD |
| `app/api/endpoints/profile.py` | `/api/config`, `/api/profile`, `/api/add_api_key`, etc. | Profile & settings |
| `app/api/endpoints/memory.py` | `/api/memory/stats`, `/api/memory/rebuild`, `/api/memory/decay` | Memory pipeline |

### Service Layer

Business logic extracted from endpoints into `app/services/`:

| Service | Function |
|---------|----------|
| `app/services/session_service.py` | `start_session`, `end_session_cleanup`, `auto_name_session_if_needed`, web tracker |
| `app/services/chat_service.py` | `handle_chat`, `process_uploaded_images`, SSE streaming initiation |
| `app/services/config_service.py` | `get_frontend_config()` — unified config for web + CLI, provider status, vision model list |
| `app/services/memory_service.py` | `trigger_pipeline()`, `summarize_session()`, `summarize_global_profile()` |

### Database Layer

`app/db/` consolidates the old `app/database/`:

| File | Role |
|------|------|
| `app/db/queries.py` | **Single source of truth** — all SQL constants, DDL, parsers |
| `app/db/connection.py` | Connection pool management (sync + async), `PgSession` context manager |
| `app/db/models.py` | Sync CRUD functions (one per SQL constant) |
| `app/db/models_async.py` | Async CRUD mirror using `AsyncPgSession` |
| `app/db/facade.py` | `Database` class — stable API with session-id defaults. Pure passthroughs use `_proxy` |

### Orchestrator

`app/services/orchestrator.py` is the single entry point for all user messages:

```
1. Image cache detection
2. LLM dispatch (app/services/llm_client.py)
3. Native tool-call parsing via provider `tool_calls`
4. Tool execution (app/tools/registry.py)
5. Synthesis pass (2nd LLM call)
6. Post-turn: async memory pipeline + cache cleanup
```

## CLI

The `yuzu` command is a thin-client inline REPL. It uses `prompt_toolkit` for asynchronous input and history, `rich` for Markdown rendering, and HTTP/SSE through `cli/client.py` for backend communication. The CLI does not import backend internals and must not be rebuilt as a full-screen TUI.

## Concurrency Guidelines (Async-Native)

Following recent refactors, Yuzu-Companion mandates strict async-native patterns to avoid event loop blocking and deadlocks:

1. **No nested `asyncio.run()`**: Do not spin up isolated event loops. Use `async/await` naturally down the call stack.
2. **Lazy Semaphores**: If limiting concurrency, use `asyncio.Semaphore`. Initialize them lazily inside the event loop (e.g., inside an async method or factory) rather than globally, to prevent cross-loop attachment errors.
3. **Database Access**: Use `AsyncPgSession` from `app/db/connection.py` for all I/O bound queries.

## What Was Removed

| Legacy | Replacement |
|--------|-------------|
| `app/api/routes.py` (~650 line monolith) | `app/api/endpoints/{chat,sessions,profile,memory}.py` |
| `app/api/routes/` (empty dir) | Deleted |
| `app/database/` (Flask-era naming) | `app/db/` |
| `app/providers.py` (single file) | `app/providers/` package (base, ollama, cerebras, openrouter, chutes) |
| `app/profile_analysis.py` | Memory logic → `app/memory/`, config → `app/services/config_service.py` |
| `api_send_message_with_images` | Merged into `ChatService.process_uploaded_images()` |
| `_NoopContext` in `app/session_lifecycle.py` | File deleted, no replacement needed |
| Flask-era `print()` debugging | `log.info()` / `log.error()` via `app/core/logging_config.py` |
| `os.path` string manipulation | `pathlib.Path` throughout |

## Provider Architecture

`app/providers/` is now a package with a clean hierarchy:

```
app/providers/
├── __init__.py      # Re-exports all providers + get_ai_manager()
├── base.py          # AIProvider ABC, AIProviderManager singleton
├── ollama.py        # OllamaProvider
├── cerebras.py      # CerebrasProvider
├── openrouter.py    # OpenRouterProvider
└── chutes.py        # ChutesProvider (primary)
```

Each provider implements `chat()`, `chat_stream()`, and (for embedding-capable) `embed()`.

## Security Notes

- All SQL uses `%s` parameterized queries (no string interpolation)
- `build_profile_update()` uses an allow list of column names validated against constants
- All API endpoints use Pydantic models for input validation
- Exception details are logged internally, generic messages returned to clients
- Path construction uses `pathlib.Path` with `os.path.basename()` guards
- Provider API keys remain in the browser BYOK configuration and are sent per request; they are not persisted server-side
