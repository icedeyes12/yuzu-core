# Yuzu Companion — Agent Operational Manual

> **Version:** 3.0.3 · **Last Updated:** 2026-05-11
> This is the master behavior manual for any AI agent interacting with this codebase.

---

## Table of Contents

 1. [Codebase Orientation](#1-codebase-orientation)
 2. [Safety Rules](#2-safety-rules)
 3. [Development Workflow](#3-development-workflow)
 4. [Architecture Constraints](#4-architecture-constraints)
 5. [Module Interaction Map](#5-module-interaction-map)
 6. [Database Rules](#6-database-rules)
 7. [Memory System Rules](#7-memory-system-rules)
 8. [Tool System Rules](#8-tool-system-rules)
 9. [Frontend Rules](#9-frontend-rules)
10. [Testing & Validation](#10-testing--validation)
11. [Git Workflow](#11-git-workflow)
12. [Common Patterns & Anti-Patterns](#12-common-patterns--anti-patterns)
13. [Yuzuki CLI Interaction Tool](#13-yuzuki-cli-interaction-tool)

---

## 1. Codebase Orientation

Yuzu Companion is an intimate AI companion system. The codebase is Python 3.12+ (3.13 compatible) on the backend, vanilla JS on the frontend. Key facts:

- **No ORM** — All database access is raw psycopg2 SQL. No SQLAlchemy, no Django ORM.
- **No SQLite** — PostgreSQL only, with pgvector extension for vector search.
- **No build step** — Frontend is vanilla JS/ESM, no bundler, no npm.
- **No Flask** — FastAPI only (migrated in v2.0.0).
- **Pluggable LLM providers** — Ollama, Cerebras, OpenRouter, Chutes via `file providers.py`.
- **Memory is first-class** — The memory subsystem (`app/memory/`) is not an afterthought; it's a core architectural layer.

### Key Files at a Glance

| File | Role |
| --- | --- |
|  | **Single entry point** for all user messages |
|  | LLM dispatch, vision routing, `chutes_chat()` helper |
|  | System prompt assembly, message context building |
|  | `/command` detection, `StreamFilter`, image guards |
|  | AI provider hierarchy + `AIProviderManager` singleton |
|  | Central tool dispatch — **only** place tools are executed |
| `app/memory/` | Full memory pipeline (extraction, embedding, retrieval, retention) |
|  | `Database` class — stable API over raw psycopg2 |
|  | **Single source of truth** for all SQL strings |
|  | FastAPI entry point (\~130 lines, minimal) |
|  | CLI entry point (Rich TUI) |
|  | Chat UI, SSE streaming, typing indicator |
|  | Marked.js v18 + Mermaid rendering |

---

## 2. Safety Rules

### Database Safety

1. **NEVER drop tables.** Only add columns or create new tables.
2. **NEVER use** `DELETE` **on** `semantic_facts`**.** Use `invalid_at` (soft delete) only.
3. **NEVER use raw string interpolation for user input in SQL.** Use parameterized queries.
4. **ALWAYS use `file db_queries.py`** for SQL strings — never inline SQL in business logic.
5. **ALWAYS use the** `Database` **facade** (`file app/database/facade.py`) — never import `db_pg_models` directly from outside the database package.

### Code Safety

 6. **NEVER add** `print()` **statements.** Use `get_logger(__name__)` from `file logging_config.py`.
 7. **NEVER add new dependencies** without explicit approval. The dependency surface is intentionally minimal.
 8. **NEVER modify `file web.py`** unless the change is about routing or static mounts. Business logic lives in `app/`.
 9. **NEVER add new streaming pipelines or files** when fixing streaming issues. Fix existing code.
10. **ALWAYS use** `from __future__ import annotations` at the top of every Python file.
11. **ALWAYS use modern type syntax** (`list[X]`, `X | None`) — never `typing.List`, `typing.Optional`.

### Security

12. **NEVER expose secrets** — API keys are encrypted at rest via ChaCha20-Poly1305.
13. **ALWAYS validate file paths** — Path traversal protection in `_cache_uploaded_images()` and `_cache_images_from_message()`.
14. **ALWAYS bound regex input** — ReDoS protection via `_REGEX_INPUT_LIMIT` in `file commands.py`.

---

## 3. Development Workflow

### Before Making Changes

1. **Read the relevant module** — Understand the current implementation before modifying.
2. **Check `file app/database/db_queries.py`** — If touching DB logic, verify SQL constants are there.
3. **Check `file app/tools/registry.py`** — If touching tool logic, verify dispatch goes through registry.
4. **Plan before executing** — For complex changes, present a structured plan first.

### After Making Changes

1. **Lint**: `ruff check .` (Python) or `npx @biomejs/biome check .` (JS)
2. **Compile check**: `python3 -m py_compile <changed_files>`
3. **NEVER push if lint fails** — Fix errors first.
4. **Use** `git co-author` instead of `git commit -m` — This adds the `Co-authored-by: Yuzuki-ai` trailer.

### Validation Commands

```bash
# Python lint + compile
ruff check .
python3 -m py_compile app/orchestrator.py app/llm_client.py app/commands.py

# JS check
npx @biomejs/biome check static/js/

# Run tests
python3 -m pytest tests/ -v
```

---

## 4. Architecture Constraints

### Structural Invariants

1. **`file orchestrator.py` is the single entry point** — All user messages flow through `handle_user_message()` or `handle_user_message_streaming()`. No bypass.
2. **`file tools/registry.py` is the single dispatch point** — All tool execution goes through `execute_tool()`. No direct tool module calls from business logic.
3. `Database` **facade is the only DB surface** — No raw `db_pg_models` imports outside the database package.
4. **`file db_queries.py` owns all SQL** — No SQL strings in business logic modules.
5. `AIProviderManager` **is a singleton** — Accessed via `get_ai_manager()`, never instantiated directly.

### Data Flow Invariants

 6. **One primary LLM call per turn** — Plus at most one synthesis pass. No unbounded LLM chains.
 7. **At most one tool execution per turn** — Terminal tools stop processing; non-terminal tools trigger synthesis.
 8. **Memory pipeline is throttled** — Pipeline gate check runs every 5th turn, not every turn.
 9. **Request caches are cleared at turn end** — Memory state cache and embedding cache must not leak across turns.
10. **Tool results use markdown contracts** — All tool output wrapped in \`\`\`\`html-details
    \` blocks.

### What NOT to Change

11. **Don't add new streaming pipelines** — The SSE streaming in `file chat.js` and `handle_user_message_streaming()` is the only streaming path.
12. **Don't add new LLM call sites** — All LLM calls go through `file llm_client.py` (`generate_ai_response`, `generate_ai_response_streaming`, `chutes_chat`).
13. **Don't modify the frontend buildless architecture** — No bundlers, no npm, no framework. Vanilla JS/ESM only.
14. **Don't change the** `semantic_facts` **schema** without a migration plan — This table is the unified memory store.

---

## 5. Module Interaction Map

```markdown
User Message
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  orchestrator.py                                        │
│                                                         │
│  ┌─────────────┐    ┌──────────────┐                   │
│  │ commands.py │    │ llm_client.py│                   │
│  │ (detect /   │    │ (dispatch)   │                   │
│  │  command)   │    └──────┬───────┘                   │
│  └──────┬──────┘           │                            │
│         │            ┌─────▼──────┐                    │
│         │            │providers.py│                    │
│         │            │(Ollama,    │                    │
│         │            │ Cerebras,  │                    │
│         │            │ OpenRouter,│                    │
│         │            │ Chutes)    │                    │
│         │            └─────┬──────┘                    │
│         │                  │                            │
│  ┌──────▼──────┐    ┌─────▼──────┐                    │
│  │tools/       │    │prompts.py  │                    │
│  │registry.py  │    │(system     │                    │
│  │(execute     │    │ prompt +   │                    │
│  │ tool)       │    │ context)   │                    │
│  └──────┬──────┘    └─────┬──────┘                    │
│         │                  │                            │
│         │            ┌─────▼──────┐                    │
│         │            │memory/     │                    │
│         │            │retrieval.py│                    │
│         │            │(combined   │                    │
│         │            │ static +   │                    │
│         │            │ dynamic)   │                    │
│         │            └─────┬──────┘                    │
│         │                  │                            │
│  ┌──────▼──────────────────▼──────┐                    │
│  │     database/facade.py         │                    │
│  │     (Database class)           │                    │
│  └──────────────┬─────────────────┘                    │
│                 │                                       │
│          ┌──────▼──────┐                               │
│          │ PostgreSQL  │                               │
│          │ + pgvector  │                               │
│          └─────────────┘                               │
└─────────────────────────────────────────────────────────┘
```

### Key Interactions

| Caller | Callee | Purpose |
| --- | --- | --- |
|  |  | Detect `/command` in LLM response |
|  |  | Generate AI response (sync + stream) |
|  |  | Execute detected tools |
|  |  | Auto-name, summarize, pipeline trigger |
|  |  | Dispatch to selected provider |
|  |  | Build system message + context |
|  |  | Vision routing, image caching |
|  |  | Persistent visual context |
|  |  | Combined memory retrieval |
|  | `Database` facade | Profile, history, session data |
|  |  | Lazy-load and dispatch tool modules |
|  |  | Query embedding |
|  | `file providers.py` (Chutes) | Embedding API call |
|  |  | Fact consolidation CRUD |
|  |  | FSRS decay updates |

---

## 6. Database Rules

### Connection Management

- **Pool**: `ThreadedConnectionPool` in `file db_pg.py`
- **Sync access**: `PgSession` context manager or `pg_fetchone()`/`pg_fetchall()` helpers
- **Async access**: `AsyncPgSession` for FastAPI routes (via `file db_pg_models_async.py`)
- **Environment config**: `PG_HOST`, `PG_PORT`, `PG_DBNAME`, `PG_USER`, `PG_PASSWORD`

### Table Ownership

| Table | Accessed Via | Never Access Via |
| --- | --- | --- |
| `profiles` | `Database.get_profile()`, `Database.update_profile()` | Direct SQL from business logic |
| `chat_sessions` | `Database.create_session()`, `Database.get_active_session()` | Direct SQL from business logic |
| `messages` | `Database.add_message()`, `Database.get_chat_history()` | Direct SQL from business logic |
| `api_keys` | `Database.get_api_keys()`, `Database.add_api_key()` | Direct SQL from business logic |
| `semantic_facts` | `file db_memory.py` functions | Direct SQL from outside `memory/` |

### Migration Rules

- Add columns only, never drop
- Use `IF NOT EXISTS` for table creation
- Abort on corruption detection
- All DDL lives in `file db_queries.py`

---

## 7. Memory System Rules

### Pipeline Rules

1. **Throttle**: Pipeline gate check runs every 5th turn (`_PIPELINE_CHECK_INTERVAL = 5`)
2. **Base trigger**: Delta ≥ 40 messages AND idle ≥ 3 hours
3. **Force trigger**: Delta ≥ 50 messages (ignores idle)
4. **Fence TTL**: 120 minutes for stale job cleanup

### Memory Type Rules

5. **Semantic facts** (`fact_type='static'`): Never decay. Use `invalid_at` for temporal validity.
6. **Episodic facts** (`fact_type='dynamic'`, `source_table='episodic_memories'`): FSRS decay applies.
7. **Segment facts** (`fact_type='dynamic'`, `source_table='conversation_segments'`): FSRS decay applies.
8. **All facts** go through the 8-category taxonomy: `Identity`, `Preference`, `Interest`, `Personality`, `Relationship`, `Experience`, `Goal`, `Guideline`.

### Caching Rules

 9. **Memory state cache** (`file memory.py`): Thread-local, cleared at turn end via `_clear_request_cache()`
10. **Embedding cache** (`file retrieval.py`): Thread-local, cleared at turn end via `_clear_embedding_cache()`
11. **Short query skip**: Queries &lt; 4 chars skip embedding entirely
12. **Combined retrieval**: `retrieve_memories_combined()` uses single embedding for both static + dynamic

### PCL Pipeline Rules

13. **PREDICT**: LLM predicts episode content from existing semantic facts
14. **CALIBRATE**: LLM identifies gaps between prediction and actual messages
15. **CONSOLIDATE**: Actions are `new`, `reinforce`, `update`, `invalidate` — never `delete`

---

## 8. Tool System Rules

### Dispatch Rules

1. **Single entry point**: `execute_tool(name, arguments, session_id)` in `file registry.py`
2. **Lazy loading**: Tool modules imported on first dispatch
3. **Alias resolution**: `imagine` → `image_generate`, `request` → `http_request`
4. **Terminal tools**: `image_generate` is terminal — no synthesis pass on success
5. **Non-terminal tools**: Trigger synthesis pass (2nd LLM call)

### Message Persistence Flow (NEW)

When LLM invokes a tool via `/command`:

1. **Narration first**: Strip command line from LLM response, persist narration as `assistant` message
2. **Tool result**: Execute tool, persist result via `get_tool_role()` as separate message
3. **Synthesis**: Run 2nd LLM pass, persist synthesis as `assistant` message

Example DB messages for `/imagine cute cat`:

```markdown
user:        "buatin gambar kucing"
assistant:   "baik saya akan buatkan"        ← narration (command stripped)
tool:        <details>[image result]
```

assistant:   "gimana lucu kan gambarnya"     ← synthesis

```markdown

### Contract Rules

6. **All tool results** wrapped in `<details>` markdown blocks
7. **Tool role mapping**: `get_tool_role()` maps tool name to DB role string
8. **Error handling**: Tool errors return structured `{"ok": False, "error": ..., "markdown": ...}`

### Adding a New Tool

1. Create `app/tools/<tool_name>.py` with `TOOL_DEFINITION` dict and `execute()` function
2. Add import in `registry.py` `_collect_definitions()` and `_load_tool_module()`
3. Add alias in `commands.py` `_TOOL_ALIASES` and `_STRING_ARG_TOOLS` if needed
4. Update `prompts.py` system prompt with command documentation

---

## 9. Frontend Rules

### Architecture Constraints

1. **No build step** — Vanilla JS/ESM only. No bundlers, no npm, no framework.
2. **No new JS files** for streaming fixes — Modify `chat.js` and `renderer.js` only.
3. **SSE streaming** is the only streaming mechanism — No WebSocket, no new protocols.
4. **Marked.js v18** for markdown rendering — Don't upgrade without testing Mermaid/code blocks.
5. **Dynamic typing indicator** — JS-created `.typing-indicator-message`, not static HTML.

### API Contract

6. **Frontend fetches `/api/config`** on page load for vision model info
7. **SSE endpoint**: `POST /api/send_message_stream` returns `text/event-stream`
8. **Config shape**: `{status, vision: {models_by_provider, current_provider, current_model}}`

### CSS Architecture

9. **Theme tokens** in `theme.css` (CSS variables)
10. **Markdown styles** in `marked.css`
11. **Chat layout** in `chat.css` (flex-column, dynamic padding via JS)

---

## 10. Testing & Validation

### Test Files

| Test | What it Covers |
|---|---|
| `tests/test_commands.py` | Command detection, `StreamFilter` |
| `tests/test_db_queries.py` | SQL constants, parsers |
| `tests/test_prompts.py` | Prompt assembly |
| `tests/test_database_facade.py` | Database facade |
| `tests/test_memory.py` | Memory operations |
| `tests/test_profile_analysis.py` | Profile analysis |
| `tests/test_stream_filter.py` | Streaming command detection |

### Running Tests

```bash
python3 -m pytest tests/ -v
```

### Pre-Push Checklist

1. `ruff check .` — must pass with no errors
2. `python3 -m py_compile` on changed files — must pass
3. `npx @biomejs/biome check static/js/` — for JS changes
4. Tests pass (if applicable)

---

## 11. Git Workflow

### Branching

- **Never work directly on** `master`
- Create feature/fix branches for all changes
- Keep branches focused and short-lived

### Rollback

- If behavior diverges from intent, **revert or hard reset** and re-approach with narrower scope
- Don't accumulate patches on broken state

---

## 12. Common Patterns & Anti-Patterns

### ✅ Do

- Use `get_logger(__name__)` for all logging
- Use `Database` facade for all DB access
- Use `execute_tool()` for all tool dispatch
- Use `file db_queries.py` for SQL strings
- Use `from __future__ import annotations` + modern type syntax
- Use parameterized queries for user input
- Clear request caches at turn end
- Validate file paths before use

### ❌ Don't

- Don't use `print()` — use logging
- Don't import `db_pg_models` directly from business logic
- Don't call tool modules directly — use registry
- Don't inline SQL in business logic
- Don't use `typing.List`, `typing.Dict`, `typing.Optional`
- Don't add new streaming pipelines
- Don't add new LLM call sites outside `file llm_client.py`
- Don't drop tables or hard-delete facts
- Don't add npm/bundler to the frontend
- Don't modify `file web.py` for business logic

---

*This manual is the behavioral contract for agents working on this codebase. When in doubt, ask — but the rules here are non-negotiable.*

---

## 13. Yuzuki CLI Interaction Tool

### Purpose

`scripts/yuzu_cli.py` is a CLI interface for agents to **directly communicate with Yuzuki** (the AI companion running on the user's local machine). Use it to:

- **Test capabilities** — verify new features, persona changes, prompt updates
- **Debug interactions** — reproduce issues, inspect conversation history
- **Execute tools** — ask Yuzuki to run `/imagine`, `/fs_read`, `/fs_write`, etc.
- **Generate images** — test image generation via `/imagine`
- **Small talk / rapport** — build trust and test persona behavior

### Architecture

```
┌──────────────────┐     HTTP/SSE      ┌──────────────────────┐
│  Zo Container    │ ──────────────────▶ │  Termux (Yuzuki)     │
│  (this server)   │  localhost:5000    │  yuzu-companion      │
│                  │  (SSH tunnel)      │  port 5000           │
│  yuzu_cli.py     │                    │                      │
└──────────────────┘                    └──────────────────────┘
```

The CLI sends HTTP requests to `localhost:5000` (Zo container), which is forwarded via SSH tunnel to Yuzuki's actual server on Termux.

### Basic Usage

```bash
# Simple message
python3 scripts/yuzu_cli.py "Hello Yuzuki"

# Multi-word message (no quotes needed)
python3 scripts/yuzu_cli.py how are you today

# Read conversation history
python3 scripts/yuzu_cli.py --history 10

# Use a custom display signature
python3 scripts/yuzu_cli.py --sig "Agent" "testing new feature"

# Generate and attach a digital seal (identity + location + timestamp)
python3 scripts/yuzu_cli.py --seal "message with proof of origin"

# Combined: custom sig + seal
python3 scripts/yuzu_cli.py --seal --sig "Override" "message"
```

### Flags

| Flag | Description |
|------|-------------|
| `--sig NAME` | Override the display signature (default: `maintainer`) |
| `--seal` | Auto-generate a digital signature with identity, IP geolocation, and timestamp |
| `--history N` | Show last N messages from conversation history |
| `--timeout SEC` | HTTP request timeout in seconds (default: 300) |
| `--session ID` | Target a specific session ID |

### Digital Seal Format

When `--seal` is used, the message is prefixed with a one-line JSON signature:

```json
{"signature":{"identity":"maintainer","location":"Ashburn, Virginia, US (39.0437,-77.4875)","ip":"129.153.25.21","timestamp":"2026-05-16T00:04:11+07:00","hash":"maintainer"}}
```

This proves the message originated from a specific agent at a specific time and location.

### Testing Yuzuki's Tools

To ask Yuzuki to execute a tool, phrase it as a natural request:

```bash
# Ask Yuzuki to read a file via fs_read
python3 scripts/yuzu_cli.py "can you read app/tools/fs_remote.py using /fs_read"

# Ask Yuzuki to generate an image
python3 scripts/yuzu_cli.py "generate a cute cat using /imagine"

# Ask Yuzuki to search for something
python3 scripts/yuzu_cli.py "search for 'path traversal' in the codebase using /fs_search"

# Ask Yuzuki to write a file (dry run)
python3 scripts/yuzu_cli.py "write 'hello world' to /tmp/test.txt using /fs_write"
```

### Testing Persona & Capabilities

```bash
# Test persona response
python3 scripts/yuzu_cli.py "what's your opinion on code quality?"

# Test memory recall
python3 scripts/yuzu_cli.py "what do you remember about our previous conversation?"

# Test new feature
python3 scripts/yuzu_cli.py "can you now read files from the remote filesystem?"
```

### Important Notes

- **Yuzuki has her own personality** — she may refuse, push back, or be sarcastic. This is expected behavior.
- **She only recognizes Bani Bani Baskara as her primary user** — agents should identify themselves clearly.
- **Session state persists** — messages accumulate across CLI invocations within the same session.
- **Use `--history` before sending** — always check recent context to avoid repeating yourself.