# Backend

**Status:** Active reference. Code is authoritative.

## Entry points

| Command | Entry point | Behavior |
|---|---|---|
| `yuzu-server` | `main:app` | FastAPI ASGI application |
| `yuzu` | `cli.app:main` | Inline Rich/prompt-toolkit REPL using HTTP and SSE |
| `python main.py` | `main.py` | Starts Uvicorn on `0.0.0.0:5000` |

FastAPI startup creates the psycopg pools, runs `init_pg_tables_async()`, checks PostgreSQL, and stores pools on application state. Shutdown closes the async pool.

## HTTP routes

`main.py` mounts `app.api.api_router` at `/api/v1`. The OAuth router is additionally mounted at `/api` for callback compatibility. Health probes stay unversioned.

| Group | Representative paths |
|---|---|
| Auth | `/api/v1/auth/login`, `/api/v1/auth/logout`, `/api/v1/auth/me`; callback compatibility also exists at `/api/auth/callback` |
| Chat | `/api/v1/send_message`, `/api/v1/send_message_stream`, `/api/v1/generate_image`, `/api/v1/browser_unload` |
| Sessions | `/api/v1/chat_history`, `/api/v1/chat_history/before`, `/api/v1/sessions/list`, `/api/v1/sessions/create`, `/api/v1/sessions/switch`, `/api/v1/sessions/rename`, `/api/v1/sessions/{session_id}` |
| Profile/config | `/api/v1/config`, `/api/v1/profile`, `/api/v1/providers/*`, `/api/v1/global-knowledge*` |
| Presets | `/api/v1/presets/list`, `/api/v1/presets/upsert`, `/api/v1/presets/activate`, `/api/v1/presets/{name}` |
| Stream recovery | `/api/v1/stream/{session_id}/status`, `/api/v1/stream/{session_id}/sync` |
| Images | Authenticated `/api/v1/static/uploads/{filename}` and `/api/v1/static/generated_images/{filename}` |
| Health | `GET/HEAD /health`, `GET /health/ready` |
| Metrics | `/metrics` when metrics are enabled; otherwise 404 |

The API uses RFC 9457-style `application/problem+json` error responses from `app/api/errors.py`. Hidden POST deletion routes remain compatibility aliases and are excluded from OpenAPI.

## Services and providers

`ConversationService` is the transport-independent boundary for message processing and image uploads. `orchestrator.py` owns the canonical execution loop; `llm_client.py` builds requests and dispatches to `AIProviderManager`.

Current provider modules are OpenRouter, OpenAI, Anthropic, Google, Grok, Groq, Cerebras, DeepSeek, Chutes, Yuzu Portal, Custom OpenAI, and Custom Anthropic. Capability flags live in `app/providers/base.py` and are overridden per provider. Chutes and OpenRouter currently opt into structured system content and vision; Anthropic and Custom Anthropic deliberately use the text system path. Other providers inherit the base defaults unless their module overrides a flag.

### Session correlation

`chat_sessions.id` is the internal stable chat identity. The orchestrator passes it into `LLMContext.chat_session_id` for every non-streaming and streaming generation pass, including tool-loop passes, retries, and fallback attempts. Provider adapters do not receive a new session ID per request.

OpenRouter is the only provider-specific session integration currently implemented. Its documented Chat Completions `session_id` request field receives the Yuzu `chat_sessions.id`; OpenRouter documents this as request grouping, sticky routing, and observability grouping. Other providers receive no speculative session field. OpenRouter response `id`/generation IDs remain provider request identities, not Yuzu chat-session IDs.

Provider registration is not proof of live functionality. Without provider credentials and network access, adapters are classified as implemented but unverified unless covered by local payload/unit tests.


## Streaming

`POST /api/v1/send_message_stream` returns SSE. The service emits `token`, `tool_call`, `tool_result`, and terminal `done` events, plus comment heartbeats while waiting. `StreamBuffer` accumulates active output in RAM, while the orchestrator persists user, tool, and assistant records. The buffer removes itself after completion or failure. Clients must ignore SSE comment heartbeats and handle reconnect/termination paths.

## Configuration and secrets

The browser stores BYOK configuration under `yuzu_byok_config` and sends it in the bounded `X-BYOK-Config` header. The backend decodes it into request-scoped keyrings. Custom provider base URLs must be public HTTPS hosts. Do not reintroduce server-side API-key persistence.

## Validation commands

```bash
ruff format --check .
ruff check .
find static -type f -name '*.js' -exec node --check {} +
bunx biome check static/
pytest
```

The exact CI workflow is `.github/workflows/ci.yml`; inspect it before changing this list.
