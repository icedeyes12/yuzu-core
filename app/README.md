# Yuzu Companion — Application Module

The `app/` directory is the core of Yuzu Companion — the AI companion system that powers long-running conversations with persistent memory, multimodal input, and canonical event flows.


---

## Table of Contents

- [Overview](#overview)
- [Directory Structure](#directory-structure)
- [Core Entry Points](#core-entry-points)
  - [`file app/orchestrator.py`](#apporchestratorpy--message-orchestration)
  - [`file main.py`](#mainpy--fastapi-web-server)
  - [`file cli/app.py`](#cliapppy--cli-application)
- [API Routing](#api-routing)
- [Database Layer](#database-layer)
- [AI Provider System](#ai-provider-system)
- [Tool System](#tool-system)
- [Memory System](#memory-system)
- [Multimodal System](#multimodal-system)
- [Encryption](#encryption)
- [Session Management](#session-management)
- [Configuration](#configuration)
- [Workflow: Message Processing](#workflow-message-processing)
- [Dependencies](#dependencies)
- [Architecture Principles](#architecture-principles)


---

## Overview

Yuzu Companion is a multi-interface AI companion with:

- **Multi-provider dispatch** — Chutes, OpenRouter, Anthropic, OpenAI, Ollama, Cerebras, DeepSeek, Google, Grok, Groq, plus custom OpenAI-/Anthropic-style endpoints
- **Native function calling** — `ToolEvent` / `ToolResultEvent` is the only production tool protocol; legacy XML-style markup is stripped as cleanup text
- **Structured system content** — providers advertising `supports_structured_system_content=True` receive a content-array system message; others fall back to legacy single-string
- **Tenant-isolated PostgreSQL** — UUIDv7 primary keys, `user_id` FK on every tenant-scoped table, pgvector + pg_trgm extensions
- **Graph memory** — episodes, inferred nodes, relationships, and evidence stored in PostgreSQL with pgvector
- **BYOK architecture** — API keys live only in browser `localStorage`; the `api_keys` table has been purged
- **Three interfaces** — Terminal (`cli/app.py` via Rich + prompt_toolkit), Web (`main.py` FastAPI), and programmatic API

```mermaid
graph LR
    A[User] --> B[cli/app.py<br/>CLI]
    A --> C[main.py<br/>Web]
    A --> D[External<br/>API Calls]

    B --> E[app/orchestrator.py<br/>Core Logic]
    C --> E
    D --> E

    E --> F[(PostgreSQL<br/>pgvector + pg_trgm)]
    E --> G[AI Providers<br/>Chutes/OpenRouter/Anthropic/...]
    E --> H[Tools<br/>image_generate/http_request/...]
    E --> I[Memory<br/>graph-backed inferred knowledge]
```

---

## Directory Structure

```
app/
├── api/
│   ├── endpoints/              # FastAPI routers (auth, chat, memory, profile, sessions, stream, presets_endpoint)
│   ├── __init__.py             # Exposes api_router
│   ├── main.py                 # api_router composition
│   ├── static.py               # Static file mounting
│   └── utils.py
├── auth/                       # Cookie session + OAuth helpers
├── core/                       # LLMContext, presets, request keyring
├── db/                         # psycopg v3 connection + Database facade + queries.py (SSOT SQL)
├── memory/                     # Embedder, graph retrieval, extraction, and pipeline
├── providers/                  # One file per provider; ProviderCapabilities declarations
├── services/                   # SessionService, MemoryService, ChatService, ConfigService
├── static/                     # Subdir for additional static assets bundled with the package
├── tools/                      # Native FC registry, schemas, multimodal helpers, per-tool modules
├── encryption.py               # ChaCha20-Poly1305 encryptor
├── key_manager.py              # Master key lifecycle
├── legacy_markup.py            # Strip-only cleanup helpers (not a live protocol)
├── llm_client.py               # Payload construction + provider dispatch
├── logging_config.py           # get_logger() factory
├── orchestrator.py             # Single entry point for user messages
├── profile_analysis.py         # Cross-session profile analysis
├── prompt.md                   # Canonical system prompt text
├── prompts.py                  # build_messages(), structured system content composer
├── stream_manager.py           # StreamBuffer (RAM buffering + single-write persistence)
└── visual_context.py
```

---

## Architectural Pipeline

### 1. `app/orchestrator.py` — Message Orchestration

The single entry point for handling user messages. Coordinates:

1. **Canonical Schema Conversion**: Forces all upstream requests into strict Event flows. No HTML parsing.
2. **Image deduplication**: Deduplicates paths by `os.path.realpath`.
3. **Vision model routing**: Defers to Provider Capabilities.
4. **Execution Sandbox**: Strict native `tool_calls` execution isolated via `app/tools/registry.py`. Tools NEVER format presentation strings.
5. **Orchestration Loop**: Recursive iteration loop bounded by a max cap (4 turns).
6. **System Persona Prompting**: Dynamic provider-specific generation (structured vs legacy string assembly based on `supports_structured_system_content`).
7. **Memory Triggering**: `MemoryService` triggers the background worker queue via `trigger_memory_pipeline_async`.

Streaming execution runs in a background worker thread with cooperative cancellation via `abort_check` and the `StreamFence` mechanism (UUID fence ID, 300s timeout).

### `file main.py` — FastAPI Web Server

The ASGI entry point registered as the `yuzu-server` console script:

- Lifespan management for the async psycopg connection pool and `init_pg_tables_async`
- Static mounts (`/static`, `/uploads`, `/generated_images`)
- HTML page routes (`/`, `/chat`, `/config`, `/about`, `/login`)
- Registers `api_router` from `app/api/`
- Loads `.env` via `python-dotenv`

### `file cli/app.py` — CLI Application

Terminal interface using Rich + prompt_toolkit. Registered as the `yuzu` console script:

- Interactive chat loop with command handling (`/model`, `/imagine`, `/vision`, `/session`, etc.)
- Session management menu
- Provider/model switching
- Code block extraction and saving
- Web interface launcher

### `file app/stream_manager.py` — Streaming State Coordinator

`StreamBuffer` owns in-flight stream buffers outside the request thread. It accumulates chunks in RAM, replays buffered output to reconnecting clients, persists once on completion, and self-cleans after the DB write. The API layer reads from it during reconnect and profile reload paths, while the orchestrator worker thread writes into it as generation advances.

---

## API Routing

### `file app/api/__init__.py`

Package init that exposes `api_router` for registration in `main.py`.

### `file app/api/main.py`

Composes the routers exported by each `app/api/endpoints/*` module into a single `api_router`.

### Routers in `app/api/endpoints/`

| Module | Prefix | Purpose |
| --- | --- | --- |
| `auth.py` | `/api/auth` | Login, logout, session cookie |
| `chat.py` | `/api/chat` | Synchronous + streaming message handling |
| `memory.py` | `/api/memory` | Graph memory stats and rebuild |
| `presets_endpoint.py` | `/api/presets` | Preset CRUD + active switching |
| `profile.py` | `/api/profile` | Profile read + update (settings, providers, advanced params) |
| `sessions.py` | `/api/sessions` | Session CRUD + auto-rename |
| `stream.py` | `/api/stream` | Stream state recovery for reconnecting clients |

`/api/config` (served by `ConfigService.get_frontend_config`) is the frontend SSOT for provider/vision model lists — eliminates hardcoded model lists in `static/js/config.js`.

The streaming endpoints (`/api/chat/stream`, `/api/profile`) support state reattachment: when a background stream is still active, they surface the live `StreamBuffer` content so the UI can recover after a disconnect or reload without losing the partial assistant response.

---

## Database Layer

### `file app/db/queries.py` — Schema DDL + SQL SSOT

Single source of truth for SQL strings, schema DDL, encryption helpers, and row parsers. All queries in business logic go through constants exported from this file.

**Tenant model:**

- `profiles` — UUIDv7 PK; tenant root
- `chat_sessions` — UUIDv7 PK; `user_id` FK → `profiles(id)` ON DELETE CASCADE
- `messages` — SERIAL int PK; `session_id` + `user_id` UUID FKs
- `episodes`, `memory_nodes`, `memory_edges`, `memory_evidence` — tenant-scoped graph memory tables with pgvector embeddings
- `user_identities` — OAuth provider linkage (Google sub / GitHub id)
- `user_sessions` — session token storage

**Extensions:** `pgcrypto`, `vector` (pgvector), `pg_trgm`.

**Safety rules:**

- NEVER drops tables
- Only safe migrations (add columns, never destructive)
- Aborts if database corruption detected
- Legacy migration columns (`legacy_int_id`, `legacy_session_id`, `memory_json`) are NOT in `SCHEMA_DDL` — they exist only as migration artifacts

### `file app/db/` — Connection + Database Facade

- `connection.py` — `get_sync_pool()`, `get_async_pool()`, `close_async_pool()`, `PgSession` / `AsyncPgSession` context managers
- `__init__.py` — `Database` facade exposing the high-level operations used by orchestrator and services
- `init_pg_tables_async()` — invoked at FastAPI startup; idempotent DDL apply

---

## AI Provider System

### `file app/providers/` — Pluggable Provider Architecture

```mermaid
classDiagram
    class AIProvider {
        +name: str
        +config: Dict
        +capabilities: ProviderCapabilities
        +get_models()
        +send_message()
        +send_message_streaming()
        +supports_vision()
        +format_vision_message()
    }

    class ProviderCapabilities {
        +supports_native_fc: bool
        +supports_streaming_fc: bool
        +supports_tool_call_parsing: bool
        +supports_structured_system_content: bool
    }

    class AIProviderManager {
        +providers: Dict
        +load_providers()
        +get_available_providers()
        +send_message()
        +send_message_streaming()
        +provider_supports_structured_system()
        +parse_tool_calls()
    }

    AIProvider <|-- ChutesProvider
    AIProvider <|-- OpenRouterProvider
    AIProvider <|-- AnthropicProvider
    AIProvider <|-- OpenAIProvider
    AIProvider <|-- OllamaProvider
    AIProvider <|-- CerebrasProvider
    AIProvider <|-- DeepSeekProvider
    AIProvider <|-- GoogleProvider
    AIProvider <|-- GrokProvider
    AIProvider <|-- GroqProvider
    AIProvider <|-- CustomAnthropicProvider
    AIProvider <|-- CustomOpenAIProvider
    AIProviderManager --> AIProvider
```

**Capability matrix (current declarations):**

| Provider | Structured System Content | Native FC | Streaming FC | Tool-Call Parsing |
| --- | --- | --- | --- | --- |
| Chutes | ✅ | ✅ | ✅ | ✅ |
| OpenRouter | ✅ | ✅ | ✅ | ✅ |
| Anthropic | ❌ | ✅ | ✅ | ✅ |
| OpenAI | (default) | ✅ | ✅ | ✅ |
| Ollama / Cerebras / DeepSeek / Google / Grok / Groq / custom | (default false) | per provider | per provider | per provider |

`ProviderCapabilities` defaults to `False` for every flag — providers opt in by passing kwargs to the `super().__init__()` call.

---

## Tool System

The tool system is driven by native function calling and `ToolEvent` / `ToolResultEvent`. Legacy XML-style markup is cleanup text only and must not be treated as a live protocol.

### `file app/tools/schemas.py` — Tool Schema Definitions

```python
@dataclass
class ToolParam:
    name: str
    description: str
    type: str = "string"
    required: bool = True
    default: Optional[str] = None

@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: List[ToolParam]
    requires_session: bool = False
    category: str = "general"
```

Plus `StreamToolEvent`, `make_tool_call_event()`, `new_turn_id()`.

### `file app/tools/registry.py` — Central Registry

Single source of truth for tool dispatch. Lazy-loads `TOOL_DEFINITIONS` from each tool module on first access.

**Key exports:**

- `get_tool_definitions()` — returns list of all registered `ToolDefinition` dicts
- `get_tool_definition(name)` — returns schema for a specific tool
- `execute_tool_event(event, session_id, user_id)` — canonical async execution path producing a `ToolResultEvent`
- `get_tool_schemas()` — OpenAI-format tool schemas for the LLM payload
- `get_tool_role(name)` — maps tool name to DB role string

### Tool Dispatch Flow

```mermaid
flowchart TD
    A[LLM response] --> B{tool_calls present?}
    B -->|Yes| C[Structured native tool call]
    B -->|No| F[Plain text response]
    C --> G[execute_tool_event]
    G --> H[ToolResultEvent]
    H --> I{Terminal tool?}
    I -->|Yes| J[Persist + return]
    I---|No| K[Recursive pass via orchestrator loop]
    K --> L[Final response]
    J --> L
```

**Dispatch priority:**

1. Structured `tool_calls[0]` from LLM → `execute_tool_event` → persist → synthesis if needed
2. Plain text → return as-is

### Registered Tool Schemas

| Tool | Role | Params | Terminal |
| --- | --- | --- | --- |
| `image_generate` | `image_tools` | `prompt` (str, required) | ✅ |
| `http_request` | `request_tools` | `url` (str, required), `method` (str, optional) | ❌ |
| `memory_search` | `memory_search_tools` | `query` (str, required) | ❌ |
| `memory_store` | `memory_store_tools` | `fact` (str, required), `category` (str, optional) | ❌ |

### Tool Modules

Each tool module exports a `TOOL_DEFINITION` dict alongside its `execute()` function:

| Module | Purpose |
| --- | --- |
| `app/tools/image_generate.py` | Image generation via Chutes API |
| `app/tools/http_request.py` | Fetch public HTTPS endpoints with size/type validation |
| `app/tools/memory_store.py` | Persist inferred graph nodes with category metadata |
| `app/tools/memory_search.py` | Search graph nodes and bounded relationships |
| `app/tools/multimodal.py` | Vision model routing and image caching (non-tool helpers) |

---

## Memory Architecture

Memory is graph-backed inferred knowledge. Raw conversation remains in `messages`; summarized interactions live in `episodes`; inferred claims live in `memory_nodes`; relationships live in `memory_edges`; and provenance lives in `memory_evidence`. Explicit user-managed facts remain separate in `global_knowledge_entries`.

```mermaid
flowchart LR
    A[User Message] --> B[messages]
    B --> C{Batch gate}
    C -->|eligible batch| D[One structured extraction call]
    D --> E[episodes]
    D --> F[memory_nodes]
    D --> G[memory_edges]
    D --> H[memory_evidence]
    F --> I[Graph retrieval: pgvector/text + bounded expansion]
    G --> I
    I --> J[PromptBuilder]
    J --> K[LLM response]
```

The pipeline runs asynchronously in batches. Retrieval is tenant-scoped, uses exact pgvector search when embeddings are available, falls back to trigram text search, and returns bounded graph expansion. Each retrieved node has explicit confidence, importance, validity, status, and provenance. There is no `semantic_facts` compatibility path, PCL pass, FSRS decay, or LLM review stage.

### Ownership

| Component | Responsibility |
| --- | --- |
| `messages` | Raw conversation only |
| `episodes` | Summarized interactions |
| `memory_nodes` | Inferred persistent claims |
| `memory_edges` | Relationships |
| `memory_evidence` | Links to source messages and episodes |
| `global_knowledge_entries` | Explicit user-managed facts |
| `app/prompts.py` | Prompt presentation only |

### Key Modules

| Module | Purpose |
| --- | --- |
| `memory.py` | Batch gate and asynchronous extraction orchestration |
| `extractor.py` | One structured extraction pass per eligible batch |
| `graph.py` | PostgreSQL graph persistence, provenance, and bounded expansion |
| `retrieval.py` | Graph retrieval and prompt-shaped formatting |
| `embedder.py` | Chutes embedding client (`EMBEDDING_DIM=4096`) |
| `tools/memory_store.py` | Explicit tool-driven inferred node creation |
| `tools/memory_search.py` | Graph search tool |

## Multimodal System

### `file app/tools/multimodal.py`

Handles image processing for vision and generation:

```mermaid
flowchart TD
    A[User Message] --> B{Image detected?}
    B -->|Yes| C[Download to cache]
    B---|No| D[Normal text processing]
    C --> E{Image type?}
    E -->|URL| F[Cache remote image]
    E -->|Upload| G[Use local path]
    F --> H[Base64 encode]
    G --> H
    H --> I[format_vision_message]
    I --> J[Provider vision model]
    J --> K[Vision analysis]

    L[imagine command] --> M[Chutes API]
    M --> N[Save to<br/>static/generated_images/]
    N --> O[Return path in contract]
```

**Vision pipeline:**

1. Extract image URLs/paths from message markdown
2. Download remote images to `static/image_cache/` (URL hash as filename)
3. Encode as base64 `data:` URI
4. `format_vision_message()` builds a content array with a `seen` set so the
   same source never produces duplicate `image_url` blocks
5. Provider executes the vision-capable model
6. Vision response attached to conversation

**Image generation pipeline:**

1. Detect `/imagine` command or image generation keywords
2. Call Chutes image API
3. Save result to `static/generated_images/`
4. Return markdown with image path
5. Synthesis pass (via orchestrator) for the model to describe / react to the generated image

**Defense-in-depth image dedup** also lives in `app/orchestrator.py`
(`_dedupe_image_paths` by `os.path.realpath`) and `app/prompts.py`
(`_build_multimodal_message` with a `seen` set).

---

## Encryption

### `file app/encryption.py`

ChaCha20-Poly1305 encryption for API keys at rest:

- **API keys**: Always encrypted
- **Messages**: Encryption disabled by default (configurable)
- Key derivation from master key in `encryption.key`
- Fallback to sentinel on decryption failure

### `file app/key_manager.py`

Master key lifecycle management:

- Key generation on first run
- Secure key storage
- Key rotation support

---

## Session Management

```mermaid
stateDiagram-v2
    [*] --> ActiveSession
    ActiveSession --> MessageExchange: user sends message
    MessageExchange --> MemoryPipeline: trigger extraction (throttled)
    MemoryPipeline --> Retrieval: context building
    Retrieval --> LLM: inject memory context
    LLM --> Response: generate reply
    Response --> MessageExchange: loop
    ActiveSession --> EndSession: /exit or timeout
    EndSession --> SessionSummary: update memory
    SessionSummary --> [*]
```

Session lifecycle is coordinated by `app/services/session_service.py`:

- `start_session_async()` — initialize session, run memory pipeline
- `end_session_cleanup_async()` — flush state, run finalization
- `auto_name_session_if_needed_async()` — LLM-driven session rename
- `init_new_session_async()` — create a fresh session for the user

On session start:

1. Verify graph nodes, relationships, evidence, and prompt retrieval after migration
2. Segment unsegmented messages
3. Run the asynchronous graph extraction pipeline
4. Initialize session context

---

## Configuration

### Profile Settings (stored in `profiles` table)

```python
{
    "user_name": str,             # User's display name
    "partner_name": str,          # AI companion name
    "affection": int,             # 0-100 affection level
    "theme": str,                 # UI theme
    "memory": {                   # Player profile memory
        "player_summary": str,
        "key_facts": {
            "likes": [],
            "dislikes": [],
            "personality_traits": []
        }
    },
    "providers_config": {
        "preferred_provider": str,
        "preferred_model": str,
        "vision_model_preferences": {"provider": str, "model": str},
        "streaming_enabled": bool
    },
    "context": {
        # Loose top-level context (legacy)
        "temperature": float,
        "top_p": float,
        "top_k": int,
        "max_tokens": int,
        "additional_instructions": str,
        "history_limit": int,
        # Preset storage (current SSOT for runtime params)
        "presets": [
            {"name": str, "payload": {...}, "is_active": bool},
            ...
        ],
        "active_preset": str
    }
}
```

### Preset Round-Trip (Phase 2 contract)

- `context.presets` is the source of truth.
- Schema: `[{name, payload, is_active}, ...]` with at most one `is_active=True`.
- Active resolution: the most recently set `is_active` entry wins (deterministic).
- `sync_top_level_with_active()` mirrors the active preset's payload into the
  legacy top-level context keys so older readers that look at
  `context["temperature"]` still see the active values during the transition
  window.
- `LLMContext.from_profile` calls `resolve_active_preset_payload()` and uses
  that as the *only* source for runtime parameters when a preset is active.

### API Key Management (BYOK Architecture)

Yuzu Companion employs a strict Bring Your Own Key (BYOK) architecture.
The server does NOT act as a password manager. Credentials only live in
memory during the request lifecycle.

- **Frontend Storage:** API keys are stored securely in the browser's
  `localStorage` (`yuzu_byok_config`).
- **Transmission:** Keys are injected dynamically via the `X-Provider-Key`
  and `X-Provider-BaseUrl` HTTP headers.
- **Backend Role:** The backend resolves these headers into a transient
  `LLMContext` object via `app/core/context.py`'s request keyring, ensuring
  zero persistent secret storage in the database.
- **Legacy:** The `api_keys` table has been destructively removed to comply
  with this security model (see `migrations/step_3_1_purge_api_keys.sql`).

---

## Workflow: Message Processing

```mermaid
sequenceDiagram
    participant U as User
    participant API as app/api/endpoints/chat.py
    participant O as app/orchestrator.py
    participant M as app/memory/retrieval.py
    participant P as app/prompts.py
    participant L as app/llm_client.py
    participant PV as Provider
    participant T as app/tools/registry.py
    participant DB as PostgreSQL

    U->>API: POST /api/chat/stream
    API->>O: handle_user_message_streaming
    O->>O: _dedupe_image_paths(cached, image_paths)
    O->>DB: persist user message + image_paths
    O->>P: build_messages(profile, session_id, user_id, ...)
    P->>M: retrieve_for_context (user_id-scoped)
    M-->>P: hybrid context
    P-->>O: messages list (structured or legacy)
    O->>L: generate_ai_response_streaming
    L->>PV: chat completions (with tool schemas)
    PV-->>L: chunks + tool_call events
    L-->>O: streamed chunks
    O->>T: execute_tool_event (if tool_calls)
    T-->>O: ToolResultEvent
    O->>L: recursive loop pass
    L->>PV: chat completions (with tool results)
    PV-->>L: final chunks
    L-->>O: final response
    O->>DB: persist assistant message
    O->>M: trigger_memory_pipeline_async (throttled)
    O-->>API: streamed chunks
    API-->>U: SSE response
```

---

## Dependencies

```markdown
# Core
pycryptodome>=3.20.0    # ChaCha20-Poly1305 encryption
python-dotenv>=1.0.0    # .env loading

# Database
psycopg[binary,pool]>=3.1  # PostgreSQL adapter (psycopg v3) with pgvector support

# Web (FastAPI)
fastapi>=0.115.0        # Modern async web framework
uvicorn[standard]>=0.30.0  # ASGI server
pydantic>=2.8.0         # Data validation with type hints
python-multipart>=0.0.9 # For file uploads
Jinja2>=3.1.0           # Template engine

# Terminal UI
rich>=13.0.0            # Rich terminal formatting
prompt-toolkit>=3.0.0   # Interactive prompts
textual>=0.47.0         # TUI framework

# Networking
requests>=2.33.0        # HTTP client for AI providers
httpx>=0.27.0           # Async HTTP client
```

---

## Architecture Principles

1. **Single entry point** — `handle_user_message()` / `handle_user_message_streaming()`
   in `app/orchestrator.py` are the only gateways for user messages.
2. **Native FC only** — all tool execution flows through
   `app/tools/registry.py::execute_tool_event`. No XML-style markup as a
   live protocol.
3. **SSOT for SQL** — every query string and DDL statement lives in
   `app/db/queries.py`. Business logic never inlines SQL.
4. **Tenant isolation** — every `user_id`-scoped read/write filters by
   `user_id`; every retrieval function accepts and forwards it.
5. **Preset-driven runtime params** — `LLMContext.from_profile` resolves the
   active preset payload and uses that as the only source for `temperature`,
   `top_p`, `top_k`, `max_tokens`, `additional_instructions`.
6. **Structured system content** is capability-gated per provider; legacy
   text fallback exists for providers that don't declare
   `supports_structured_system_content=True`.
7. **Layered image dedup** — `_dedupe_image_paths` in orchestrator +
   `seen` set in `build_messages` + `seen` set in
   `format_vision_message`. The same file referenced via different path
   forms never produces duplicate `image_url` blocks.
8. **Safe migrations** — the database never drops tables, only adds
   columns; legacy migration columns are migration artifacts, not part of
   `SCHEMA_DDL`.
9. **No heuristic detection** — the LLM determines tool calls via native
   function calling. There are no hardcoded regex-driven execution paths.
10. **Request-scoped caching** — memory state and embeddings cached
    per-turn and cleared at turn end to minimize API calls.
11. **BYOK only** — API keys never persist server-side; the `api_keys`
    table is gone and must not be reintroduced.
12. **Stream ownership** lives in `app/stream_manager.py`. Do not add
    parallel streaming stacks.
