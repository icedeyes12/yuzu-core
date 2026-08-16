# Backend

**Status:** Active reference. Code is authoritative.

## Entry points

| Command | Entry point | Behavior |
|---|---|---|
| `yuzu-server` | `main:app` | FastAPI ASGI application |
| `yuzu` | `cli.app:main` | Inline Rich/prompt-toolkit REPL using HTTP and SSE |
| `python main.py` | `main.py` | Starts Uvicorn on `0.0.0.0:5000` |

FastAPI startup creates the psycopg pools, runs `init_pg_tables_async()`, checks PostgreSQL, and stores pools on application state. Shutdown closes the async pool.

## HTTP contract

`main.py` mounts `app.api.api_router` at `/api/v1` and the health router unversioned. Health probes stay unversioned. The full route surface, request headers (including `X-BYOK-Config`), BYOK encoding, SSE event types, and the RFC 9457 error format are the shared contract documented once in [`../api/contract.md`](../api/contract.md) — that document is authoritative and this README does not duplicate it. Hidden POST deletion routes remain compatibility aliases and are excluded from OpenAPI.

## Services and providers

`ConversationService` is the transport-independent boundary for message processing and image uploads. `orchestrator.py` owns the canonical execution loop; `llm_client.py` resolves request requirements against model metadata, then builds requests and dispatches to `AIProviderManager`.

Current provider modules are OpenRouter, OpenAI, Anthropic, Google, Grok, Groq, Cerebras, DeepSeek, Chutes, Mistral, NVIDIA NIM, Yuzu Portal, Custom OpenAI, and Custom Anthropic. Provider transport flags live in `app/providers/base.py`; model capabilities live in `app/core/capabilities.py`. Discovery normalizes provider `/models` metadata into `ModelInfo` and exposes `models` plus `model_infos` through config, provider-list, proxy, and refresh responses. OpenRouter/compatible metadata accepts both top-level and `architecture` modality arrays. Google refresh uses native `/v1beta/models` metadata for model IDs and token limits; native thinking semantics remain `unknown` unless explicitly declared. Partial declared metadata is merged with provider-specific inference per field; explicit declared values win, while missing fields remain eligible for inference. Missing capability metadata remains `unknown`.

Capability lifecycle:

```text
provider /models -> normalize_model_metadata() -> provider.model_infos
  -> ConfigService/API model_infos -> browser appConfig.model_infos
  -> llm_client request requirements -> effective request -> provider adapter
```

`ModelInfo` is an in-memory discovery cache. PostgreSQL persists selected provider/model and user generation settings, not raw model metadata. This is intentional: metadata is re-discovered rather than treated as a durable tenant cache. `RequestRequirements` and `EffectiveCapabilities` keep declared model facts separate from per-request inclusion decisions. Streaming and non-streaming dispatch use the same resolver.

### Session correlation

`chat_sessions.id` is the internal stable chat identity. The orchestrator passes it into `LLMContext.chat_session_id` for every non-streaming and streaming generation pass, including tool-loop passes, retries, and fallback attempts. Provider adapters do not receive a new session ID per request.

OpenRouter is the only provider-specific session integration currently implemented. Its documented Chat Completions `session_id` request field receives the Yuzu `chat_sessions.id`; OpenRouter documents this as request grouping, sticky routing, and observability grouping. Other providers receive no speculative session field. OpenRouter response `id`/generation IDs remain provider request identities, not Yuzu chat-session IDs.

Provider registration is not proof of live functionality. Without provider credentials and network access, adapters are classified as implemented but unverified unless covered by local payload/unit tests.


## Streaming

`POST /api/v1/send_message_stream` returns SSE. The service emits `token`, `tool_call`, `tool_result`, and terminal `done` events, plus comment heartbeats while waiting. `StreamBuffer` accumulates active output in RAM, while the orchestrator persists user, tool, and assistant records. The buffer removes itself after completion or failure. Clients must ignore SSE comment heartbeats and handle reconnect/termination paths.

## Configuration and secrets

The browser stores BYOK configuration per user in `localStorage` (`user_{user_id}_api_keys`) and sends it in the bounded `X-BYOK-Config` header (encoding and limits: [`../api/contract.md`](../api/contract.md)). The backend decodes it into request-scoped keyrings. Custom provider base URLs must be public HTTPS hosts. Do not reintroduce server-side API-key persistence.

## Validation commands

```bash
ruff format --check .
ruff check .
find static -type f -name '*.js' -exec node --check {} +
bunx biome check static/ web/src/
pytest
for file in tests/frontend/*.mjs; do node "$file"; done
```

The exact CI workflow is `.github/workflows/ci.yml`; inspect it before changing this list.
