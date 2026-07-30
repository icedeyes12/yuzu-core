# Yuzu Companion — Agent Operating Guide

Compact routing index for AI code generation. Reflects the current state of
the repository at HEAD of `dev`.

## Core Tech Stack & Environment

- **Language / Runtime:** Python 3.12+
- **Web framework:** FastAPI + Uvicorn (`main.py` is the ASGI entry point;
  `cli/app.py` is the terminal entry point registered as `yuzu` console script)
- **Database:** PostgreSQL with the `pgcrypto`, `vector` (pgvector), and `pg_trgm` extensions
- **DB adapter:** `psycopg[binary,pool]` v3 (raw SQL — no ORM)
- **Schema DDL:** `app/db/queries.py` (`SCHEMA_DDL` tuple) — single source of
  truth. UUIDv7 primary keys for profiles, sessions, messages, and graph memory
  records. All tenant-scoped tables carry `user_id UUID NOT NULL REFERENCES
  profiles(id) ON DELETE CASCADE`.
- **Graph memory:** `episodes`, `memory_nodes`, `memory_edges`,
  `memory_evidence`, and `global_knowledge_entries`; raw history remains in
  `messages`.
- **Embeddings:** Chutes graph embeddings; `EMBEDDING_DIM = 1536`
- **Memory maintenance:** graph integrity/provenance checks via the standalone
  `Skills/memory-guardian` skill; no runtime decay or legacy fact-review queue
- **Encryption:** ChaCha20-Poly1305 (`pycryptodome`) for API keys
- **Python linting:** `ruff check .` and `ruff format --check .`
- **Templates:** Jinja2 + vanilla JS / CSS in `templates/` and `static/`

## Architectural Compass

### Backend (`app/`)

- `app/orchestrator.py` — single entry point for user messages. Streaming +
  non-streaming paths. Owns image dedup, vision routing, and the canonical
  execution loop (max 4 iterations).
- `app/llm_client.py` — payload construction + provider dispatch (streaming
  and non-streaming). Calls `build_messages()` and passes
  `**ctx.parameters` to providers.
- `app/prompts.py` — system prompt assembly and the
  `build_messages(profile, session_id, interface, user_message, user_id, ...)`
  function. Structured content-array path is selected when the provider
  reports `supports_structured_system_content=True`.
- `app/providers/` — one file per provider (`base.py`, `chutes.py`,
  `openrouter.py`, `anthropic.py`, `openai.py`, `ollama.py`, `cerebras.py`,
  `deepseek.py`, `google.py`, `grok.py`, `groq.py`, `custom_anthropic.py`,
  `custom_openai.py`). All declare a `ProviderCapabilities` instance.
- `app/core/llm_context.py` — runtime SSOT dataclass assembled from profile,
  BYOK keyring, and the active preset payload. Holds the resolved
  `parameters` dict.
- `app/core/presets.py` — preset CRUD + `resolve_active_preset_payload()`
  used as the only source of runtime generation parameters when a preset is
  active.
- `app/db/queries.py` — SQL constants, `SCHEMA_DDL`, row parsers, encryption
  helpers. **All SQL lives here** — do not inline schema drift into business
  logic.
- `app/memory/memory.py` — background graph pipeline, batching, and segmentation.
- `app/memory/extractor.py` — structured batch extraction.
- `app/memory/graph.py` — graph persistence, provenance, and bounded expansion.
- `app/memory/retrieval.py` — tenant-scoped vector/trigram graph retrieval.
- `app/memory/embedder.py` — graph embedding client (`EMBEDDING_DIM=1536`).
- `app/tools/registry.py` — canonical tool dispatch via `ToolEvent` /
  `ToolResultEvent`. `execute_tool_event()` is the production execution path.
- `app/tools/schemas.py` — `ToolEvent`, `ToolResultEvent`, `StreamToolEvent`
  dataclasses.
- `app/tools/multimodal.py` — `MultimodalTools` class: image caching, base64
  encoding, vision model detection, `format_vision_message()`.
- `app/services/` — `SessionService`, `MemoryService`, `ChatService`,
  `ConfigService` — orchestration glue for the API layer.
- `app/stream_manager.py` — `StreamBuffer`: in-RAM chunk accumulation,
  single DB write on completion, self-cleanup after persistence.
- `app/legacy_markup.py` — strip-only helpers for archived XML-style
  `<command>` / `<tool>` blocks. **Not** an execution path.
- `app/api/endpoints/` — FastAPI routers: `auth.py`, `chat.py`, `memory.py`,
  `presets_endpoint.py`, `profile.py`, `sessions.py`, `stream.py`.

## Rules of Engagement (The "Constitution")

1. **Strict Runtime Data Boundaries.** Backend tools (`app/tools/`) must return purely structured data via Pydantic schema validation. Backend must NEVER format Markdown, HTML, or UI-centric presentation logic. Tool results are cleanly serialized objects.
2. **Centralized Frontend Runtime Validation.** All tools payloads reaching the client (via SSE or API fetch) MUST pass through `validator.js` (`validateToolResult()`). Renderers consume normalized objects only. UI code must not contain try-catch patching logic for broken backend strings.
3. **No Private/Location Data Leak to LLM.** User location (`lat`/`lon`) is strictly stored in the PostgreSQL `profiles` table. It is NOT injected into the system prompt. LLMs must call the `weather` tool which securely resolves coordinates from the database during execution.
4. **Native function calling is the only production tool protocol.** `ToolEvent` / `ToolResultEvent` flow through `app/tools/registry.py`. Legacy XML-style markup is cleanup-only.
5. **All SQL lives in `app/db/queries.py`.** No inline DDL or schema drift in business logic. Migrations are additive only.
6. **Tenant isolation is mandatory.** Every read/write against a `user_id`-scoped table must filter by `user_id`. Graph memory abstractions (`app/memory/graph.py`, `app/memory/retrieval.py`, and `app/db/models_async.py`) must preserve this boundary.
7. **Runtime parameters come from the active preset.** `LLMContext.from_profile` calls `resolve_active_preset_payload()` and uses that as the only source of `temperature`, `top_p`, `top_k`, `max_tokens`, and `additional_instructions` when a preset is active. Loose top-level context values are ignored in that case to keep the runtime payload reproducible.
8. **Structured system content is capability-gated.** When a provider's `ProviderCapabilities.supports_structured_system_content` is `True`, `build_messages` emits the system message as a content array (persona, metadata, memory, knowledge, instructions). Otherwise it falls back to legacy single-string assembly, but still appends `additional_instructions` as a second system message.
9. **Image deduplication is layered.**
   - `app/orchestrator.py` `_dedupe_image_paths` merges `cached_images` and `image_paths` by `os.path.realpath`, preserving first-occurrence order.
   - `app/prompts.py` `_build_multimodal_message` keeps a `seen` set so the same file referenced via different path forms cannot produce duplicate `image_url` blocks.
   - `app/tools/multimodal.py` `format_vision_message` keeps a parallel `seen` set as defense-in-depth.
10. **Stream ownership lives in `app/stream_manager.py`.** Do not add parallel streaming stacks. The orchestrator yields, `StreamBuffer` writes to DB once on completion.
11. **Vision routing is provider-via-`AIProviderManager.format_vision_message`.** `app/tools/multimodal.py` is the home of vision model detection and image cache; the orchestrator delegates through the base provider.
12. **Frontend Architecture.** `ConversationStore` owns the state. `DOMRenderer` owns the DOM. Do not bypass the store with direct `innerHTML` appends.
13. **Slider drag-threshold is required.** All `<input type="range">` elements must be wrapped with `attachSliderGuard(slider)` so vertical scroll does not move the slider. The guard activates on horizontal movement after a 6px touch-slop threshold and ignores minor vertical drift.
14. **API keys never persist server-side.** BYOK architecture: keys live only in browser `localStorage` (`yuzu_byok_config`) and arrive via `X-Provider-Key` / `X-Provider-BaseUrl` headers. The retired `api_keys` table must not be recreated.
