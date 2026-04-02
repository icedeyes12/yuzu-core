# Changelog

All notable changes to this project will be documented in this file.

## [2.1.0] - 2026-03-30

### Added — Standard Tool Calling System

- **`app/tools/schemas.py`**: New tool schema system with `ToolParam` and `ToolDefinition` dataclasses
  - Standardized tool definitions with name, description, and typed parameters
  - Every tool module now exports `TOOL_DEFINITION` for declarative schema

- **`app/tools/registry.py`**: Central tool registry — single source of truth for dispatch
  - Lazy-loaded `TOOL_DEFINITIONS` collected from each tool module on first access
  - `get_tool_definitions()` — returns list of all registered tool schemas
  - `get_tool_definition(name)` — returns schema for a specific tool
  - `format_tool_result()` — produces structured `GenerateResult(text, tool_calls)`
  - Legacy `execute_tool()` and `get_tool_role()` maintained for backward compat

- **`app/tools/__init__.py`**: Re-exports new registry API

### Changed — Provider Tool Support

- **`app/providers.py`**: OpenRouter and Chutes providers now accept `tools=[]` parameter
  - OpenAI-compatible `function` call schemas injected into chat completions payload
  - `send_message_full()` — returns `GenerateResult(text, tool_calls, provider, model)`
  - `parse_tool_calls()` — extracts structured tool calls from LLM response

### Changed — App Orchestration

- **`app/app.py`**: `handle_user_message` now dispatches structured tool_calls first
  - `ToolCall` and `GenerateResult` dataclasses for typed tool call handling
  - `generate_ai_response()` calls `send_message_full(tools=[...])` — LLM sees tool schemas
  - **New priority**: structured `tool_calls[0]` from LLM → execute via registry → done
  - **Fallback**: legacy `/command` text detection still works (backward compat)
  - Image tools remain terminal (no synthesis pass on success)

### Tool Schemas Registered

| Tool | Role | Params |
|---|---|---|
| `image_generate` | `image_tools` | `prompt` (str, required) |
| `request` | `request_tools` | `url` (str, required), `method` (str, optional) |
| `memory_search` | `memory_search_tools` | `query` (str, required) |
| `memory_store` | `memory_store_tools` | `fact` (str, required), `category` (str, optional) |

## [2.0.0] - 2026-03-29

### Changed — Architecture (Breaking)

- **Complete migration from Flask to FastAPI**: Entire web interface (`web.py`) rewritten with FastAPI best practices
  - Replaces `Flask(__name__)` with `FastAPI()` application instance
  - Replaces `@app.route()` decorators with `@app.get()` / `@app.post()`
  - Replaces Flask `render_template()` with `Jinja2Templates` + `TemplateResponse`
  - Replaces Flask `send_from_directory()` with `FileResponse`
  - Replaces Flask `jsonify()` with native Pydantic model responses or `dict`
  - Replaces Flask `session` cookies with in-memory `_web_session_tracker` dict

### Removed — Flask Stack

- **Flask** (`Flask>=3.0.0`) — web framework
- **Werkzeug** (`Werkzeug>=3.0.0`) — WSGI utilities (no longer needed with ASGI/uvicorn)

### Added — FastAPI Stack

- **FastAPI** (`fastapi>=0.115.0`) — modern, high-performance web framework
- **uvicorn** (`uvicorn[standard]>=0.30.0`) — ASGI server with auto-reload support
- **python-multipart** (`python-multipart>=0.0.9`) — form data/file upload handling
- **Pydantic v2** integrated validation for all request/response models:
  - `MessageRequest`, `StreamMessageRequest`, `ApiKeyRequest`, `ChutesKeyRequest`
  - `SessionCreateRequest`, `SessionSwitchRequest`, `SessionRenameRequest`, `SessionDeleteRequest`
  - `ProviderSetRequest`, `ProviderTestRequest`, `LocationUpdateRequest`, `GlobalKnowledgeUpdateRequest`

### Added — FastAPI Database Support

- `app/database.py`: Added `get_db()` generator for FastAPI `Depends()` dependency injection
  - Maintains compatibility with legacy `get_db_session()` context manager

### Migrated — Entry Point

- `main.py`: `launch_web_interface()` updated to use `uvicorn.run()` instead of Flask `app.run()`
  - Supports configurable `host`, `port`, and `reload` parameters

### Notes

- API routes remain at the same paths (`/api/*`) — backward compatible with frontend
- Static file serving moved from `flask.send_from_directory` to `fastapi.staticfiles.StaticFiles`
- Template rendering moved from `flask.render_template` to `fastapi.templating.Jinja2Templates`

### Fixed — Critical (Post-Migration)

- **P1**: `get_chat_history_for_ai` missing — restored full implementation with markdown contract parsing
- **P2**: `get_chat_history` filter too restrictive — added `ALL_TOOL_ROLES` to include tool messages in UI
- **P3**: Chat history limit too low — changed `limit=1000` to `limit=None` for sessions with 4000+ messages
- **P4**: Datetime serialization error — fixed `api_get_profile` datetime → ISO string conversion
- **P5**: Missing Database methods — added `add_image_tools_message`, `add_tool_result`, `add_system_note`, `add_memory_note`

## [1.0.69.29] - 2026-03-27

### Fixed — Memory System (Critical)

- **C1**: `process_messages_for_memory` name collision — canonical function is now `extractor.process_messages_for_memory`; removed shadowing alias from `segmenter.py`
- **C2**: `source_episodic_ids` never populated — `create_episodic_memory` now accepts `source_message_ids` and cross-links episodic↔semantic records
- **C3**: Inconsistent `access_count` initialization — standardized `access_count=1` for new records across all creation paths

### Fixed — Memory System (High)

- **H1**: Idempotency check missed `ConversationSegment` — added `seg_count > 0` to `already_initialized` guard in `app.py` session init
- **H2**: Semantic extraction not idempotent — `upsert_semantic_memory` now uses embedding cosine similarity (>0.95) duplicate detection, matching `memory_store` tool strategy; prevents near-duplicate fact accumulation
- **H3**: Last segment silently discarded when < 5 messages — removed minimum threshold; final group always flushed as a segment
- **H4**: `migrate_history.py` type mismatch — `segment_count = segment_session()` returned `dict`, not `int`; fixed to `seg_result.get('segments_created', 0)`

### Fixed — Memory System (Medium)

- **M1**: Inconsistent `confidence`/`importance` across creation paths — standardized to `confidence=0.7, importance=0.7` in `upsert_semantic_memory` and all migration paths
- **M3**: `models.py` was empty and misleading — now properly re-exports `SemanticMemory`, `EpisodicMemory`, `ConversationSegment` from `app.database` with `__all__`
- **M4**: `source_episode_id` misattributed — all facts in a batch were tagged with `batch[0]["id"]`; fixed to round-robin per-episode attribution
- **M5**: Inconsistent dedup strategy between `memory_store` tool and `upsert_semantic_memory` — resolved (both now use cosine similarity >0.95)

### Added — Memory System

- `app.memory.extractor`: `__all__` exported for clean import surface
- `app.memory.segmenter`: `__all__` exported (`segment_session`, `_detect_boundaries`, `_create_segment`)

## [1.0.69.28v4] - 2026-03-24

### Added
- Embedding model for semantic memory search
- Preview button for HTML codeblocks
- Docker installation support (Dockerfile, docker-compose.yml)

### Fixed
- Various bug fixes