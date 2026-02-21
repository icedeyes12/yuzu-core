# Implementation Summary: Deterministic Backend-Driven Tool Execution

## Overview

The yuzu-companion orchestration engine uses a strict, deterministic tool command protocol.
Providers operate as **pure chat completion engines** — no tool schemas are injected, no
`tool_calls` are parsed, and `finish_reason` is always `"stop"`. Tool execution is driven
entirely by the backend through `/command` detection in LLM text responses.

## Architecture

### Provider Layer (`providers.py`)
- Providers (Ollama, Cerebras, OpenRouter, Chutes) are pure chat completion engines.
- No `tools` payload is sent to any provider.
- No `tool_calls` or `type:function` parsing in responses.
- Providers always return plain strings (or `None` on failure).
- Multi-provider compatible — works with providers that do not support tool calling.

### Two-Phase Orchestration (`app.py`)

**Phase 1 — Command Construction**
1. User message saved to context (in-memory, not yet in DB).
2. Build context (system + last N messages).
3. Send to LLM — single call, no agentic looping.
4. If LLM returns `/command ...` on first line → execute tool deterministically.
5. Command text is NOT persisted as assistant content.

**Phase 2 — Tool Execution + Reinjection**
1. Execute tool via `execute_tool()`.
2. Capture result as markdown contract (`<details>` block).
3. Persist tool result with `*_tools` role in DB.
4. Second LLM pass sees tool result in context for natural response.
5. `image_tools` success is TERMINAL — no second LLM pass needed.

## Key Features

### Command Detection System
- **Function**: `_detect_command(response_text)`
- Validates command is on the first line only
- Rejects any text before the command
- Parses command name and arguments
- Handles multi-line commands (e.g., `/memory_sql`)

### Available Commands
- `/web_search [query]`
- `/memory_search [query]`
- `/memory_sql` (multi-line SQL)
- `/weather [location/URL]`
- `/image_analyze`
- `/imagine [prompt]` (maps to image_generate tool)

### Vision Auto-Switch
- Vision provider switching occurs ONLY for new messages containing images.
- Persistent visual context buffer for N follow-up turns.
- No vision switching for text-only messages.

### Error Persistence
- Tool errors are wrapped in markdown contracts and persisted.
- LLM failure triggers user message save to prevent conversation loss.
- Empty responses trigger a single retry.

## Testing

### Test Suite
1. **Command Detection Tests** (`tests/test_command_detection.py`)
   - Valid command detection, invalid command rejection, all tool types
2. **Integration Tests** (`tests/test_command_integration.py`)
   - Command execution flow, markdown contracts, second-pass logic
3. **Deterministic Pipeline Tests** (`tests/test_deterministic_pipeline.py`)
   - No agentic looping, no tools kwarg to providers, string-only responses
   - User message save order, context roles, terminal image_tools behavior
4. **Database Tests** (`tests/test_database_tool_result.py`)
   - Tool result persistence and role mapping

## Security
- **Input Validation**: Commands strictly validated (first line only, starts with `/`)
- **SQL Injection**: Memory SQL tool restricted to SELECT/UPDATE only
- **No tool schemas exposed**: Provider layer has no tool integration surface

## Execution Flow

```
User message received
  ↓
LLM generates response (pure text, no tool_calls)
  ↓
Check for /command on first line
  ↓
If /command detected:
  - Execute tool deterministically
  - Persist result as *_tools role
  - Second LLM pass for natural response
  ↓
Response returned to user
```

## Files Changed

1. **providers.py**: Removed tool schema injection and tool_calls parsing
2. **app.py**: Removed tool_calls handling, tool schema injection; pure /command flow
3. **tests/**: Updated tests to use /command pattern, added provider-purity tests
