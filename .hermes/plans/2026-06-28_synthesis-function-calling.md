# Synthesis Loop → Native Function Calling Refactor

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Replace the current text-based `<command>` block synthesis loop with native OpenAI function calling. The LLM gets real tool definitions and a `respond` pseudo-tool for final output — no more regex parsing, no more infinite loops.

**Architecture:** Synthesis pass now sends `tools=[all_tools + respond_tool]` to the provider. The LLM either calls a real tool (bash, python, etc.) or calls `respond` to produce final text. Tool results are returned as proper `tool` role messages. The loop continues until LLM calls `respond` or hits max iterations.

**Tech Stack:** Python, OpenAI chat completions format, OpenRouter + Chutes providers (both support function calling)

---

## Current State (Problem)

```
Synthesis pass:
  - System prompt still has <command> docs
  - No tools sent to provider
  - LLM improvises <command> blocks in text
  - Loop parses text → executes → loops forever
```

## Target State

```
Synthesis pass:
  - System prompt: NO <command> docs, uses function calling instructions
  - tools=[...all_tools, respond_tool] sent to provider
  - LLM calls tools natively OR calls "respond" to finish
  - Tool results returned as role="tool" messages
  - Loop ends when LLM calls "respond" or hits max iterations
```

---

## Task 1: Create `respond` pseudo-tool definition

**Objective:** Add a `respond` tool to the registry that accepts a plain text string. This is the LLM's way to say "I'm done, here's my final answer."

**Files:**
- Modify: `app/tools/registry.py` — register `respond` tool in `_collect_definitions()`
- Create: `app/tools/respond.py` — simple tool that returns the text argument

**Step 1: Create `app/tools/respond.py`**

```python
"""Pseudo-tool for synthesis pass — LLM calls this to produce final text."""
from __future__ import annotations

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "respond",
        "description": "Produce your final response to the user. Call this when you have completed all tool executions and are ready to deliver your answer.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The final natural-language response to deliver to the user."
                }
            },
            "required": ["text"]
        }
    },
    "role": "synthesis"
}

async def execute(arguments: dict, **kwargs) -> dict:
    text = arguments.get("text", "")
    return {
        "ok": True,
        "data": {"text": text},
        "markdown": text,
    }
```

**Step 2: Register in `app/tools/registry.py`**

In `_collect_definitions()`, add:
```python
try:
    from app.tools import respond
    _TOOL_DEFINITIONS["respond"] = respond.TOOL_DEFINITION
except Exception as e:
    logger.info(f"[registry] Failed to load respond definition: {e}")
```

In `_load_tool_module()`, add:
```python
elif tool_name == "respond":
    from app.tools import respond
    _TOOL_MODULES[tool_name] = respond
```

**Step 3: Verify compile**

```bash
python3 -m py_compile app/tools/respond.py app/tools/registry.py
```

Expected: no output (success)

---

## Task 2: Add `is_synthesis` flag to `build_system_message_async`

**Objective:** When building system prompt for synthesis pass, replace tool docs with a short function-calling instruction. The model should understand it can call tools or `respond`.

**Files:**
- Modify: `app/prompts.py` — `build_system_message_async()`, already has `suppress_tools` param from previous fix

**Step 1: Update the synthesis note in `build_system_message_async()`**

Replace the current `synthesis_note` block:

```python
    synthesis_note = """
# SYNTHESIS PASS
You are in a **final response** pass. Tool execution is NOT available here.
- Do NOT output any `<command>` blocks.
- Produce your final natural-language response directly.
- Wrap the result in ACT tokens as usual.
""" if suppress_tools else ""
```

With:

```python
    synthesis_note = """
# SYNTHESIS PASS
You are in a tool-use pass. You have access to tools from the previous turn.
- You MAY call tools (bash, python, read, etc.) to gather more information.
- When done, call the `respond` tool with your final answer.
- Do NOT use `<command>` blocks — use function calls instead.
- Wrap your reasoning in ACT tokens as usual.
""" if suppress_tools else ""
```

**Step 2: Verify compile**

```bash
python3 -m py_compile app/prompts.py
```

Expected: no output (success)

---

## Task 3: Rewrite `_run_synthesis_async` and `_stream_synthesis_async`

**Objective:** Synthesis now sends real tool definitions + `respond` tool to the provider. Parse native `tool_calls` from the response instead of regex-parsing `<command>` blocks.

**Files:**
- Modify: `app/orchestrator.py` — `_run_synthesis_async()`, `_stream_synthesis_async()`, and the orchestration loop

**Step 1: Rewrite `_run_synthesis_async`**

```python
async def _run_synthesis_async(
    profile: dict[str, Any],
    session_id: str,
    interface: str,
    tool_markdown: str,
    user_id: str | None = None,
) -> str | None:
    """Run a 2nd LLM pass with native function calling.
    
    The LLM gets all tool definitions + a 'respond' pseudo-tool.
    Returns the final text from the 'respond' tool call,
    or None if the LLM didn't call respond.
    """
    text, raw = await generate_ai_response(
        profile,
        "",
        interface,
        session_id,
        is_tool_loop=True,
        suppress_tools=True,
        user_id=user_id,
    )
    if not text or not text.strip():
        return None

    # Parse tool_calls from raw response
    tool_calls = await _parse_raw_tool_calls_async(
        profile.get("providers_config", {}).get("preferred_provider", "ollama"),
        raw,
    )
    
    # Check if LLM called "respond"
    for tc in tool_calls:
        if tc["name"] == "respond":
            arguments = tc.get("arguments", {})
            return _clean(arguments.get("text", ""))
    
    # LLM called other tools — return marker for loop to handle
    return None
```

**Step 2: Rewrite `_stream_synthesis_async`**

```python
async def _stream_synthesis_async(
    profile: dict[str, Any],
    session_id: str,
    interface: str,
    tool_markdown: str,
    user_id: str | None = None,
) -> AsyncIterator[str]:
    """Stream the 2nd LLM pass with native function calling.
    
    Yields text chunks from the 'respond' tool call.
    Yields tool markdown for other tool calls.
    """
    async for chunk in generate_ai_response_streaming(
        profile,
        "",
        interface,
        session_id,
        is_tool_loop=True,
        suppress_tools=True,
        user_id=user_id,
    ):
        yield chunk
```

**Step 3: Update `_run_orchestration_loop_async`**

The loop now needs to handle native tool calls. Replace the `has_tool_blocks` check with `parse_tool_calls` logic:

```python
# In the loop, after getting synthesis:
# 1. Check if synthesis has native tool_calls (from streaming buffer)
# 2. If respond tool called → extract text, return
# 3. If other tools called → execute, loop
# 4. If no tool_calls → treat text as final response
```

**Step 4: Verify compile**

```bash
python3 -m py_compile app/orchestrator.py
```

Expected: no output (success)

---

## Task 4: Update `_send_to_provider` to include `respond` tool in synthesis

**Objective:** When `suppress_tools=True`, send all tool definitions + `respond` tool (not empty array). The LLM can then call tools natively.

**Files:**
- Modify: `app/llm_client.py` — `_send_to_provider()`

**Step 1: Change `_send_to_provider` logic**

Currently:
```python
schemas = [] if suppress_tools else _unique_tool_schemas()
```

Change to:
```python
if suppress_tools:
    # Synthesis pass: send all tools + respond, no <command> docs in prompt
    from app.tools.respond import TOOL_DEFINITION as RESPOND_DEF
    schemas = [*_unique_tool_schemas(), RESPOND_DEF]
else:
    schemas = _unique_tool_schemas()
```

**Step 2: Verify compile**

```bash
python3 -m py_compile app/llm_client.py
```

Expected: no output (success)

---

## Task 5: Update streaming path to handle native tool calls

**Objective:** The streaming path (`handle_user_message_streaming`) currently parses `<command>` blocks from text. After this fix, the synthesis sub-loop should handle native tool_calls from the streaming buffer.

**Files:**
- Modify: `app/orchestrator.py` — `_process_tool_commands_async()`, `_run_orchestration_loop_async()`

**Step 1: Add `_parse_streaming_tool_calls` helper**

In streaming mode, tool calls arrive as deltas. The `StreamBuffer` accumulates them. We need a way to extract tool_calls from the accumulated SSE text.

Actually — the current streaming path uses `generate_ai_response_streaming` which yields text chunks. For function calling in streaming, we need to accumulate `delta.tool_calls` instead of `delta.content`.

**Step 2: Add `generate_ai_response_streaming_with_tools`**

Create a new function that yields both text and tool_call chunks:

```python
async def generate_ai_response_streaming_tool_aware(
    profile, user_message, interface, session_id, *,
    ephemeral_context=None, is_tool_loop=False, suppress_tools=False,
    user_id=None,
) -> AsyncIterator[dict]:
    """Yield {'type': 'text', 'content': ...} or {'type': 'tool_call', 'name': ..., 'arguments': ...}"""
    ...
```

This needs the OpenRouter streaming handler to also yield `delta.tool_calls` from the SSE stream.

**Step 3: Update OpenRouter streaming to yield tool_calls**

In `app/providers/openrouter.py`, the streaming handler currently only extracts `delta.content`:

```python
if "content" in delta and delta["content"]:
    yield delta["content"]
```

Change to yield dicts:
```python
if "content" in delta and delta["content"]:
    yield {"type": "text", "content": delta["content"]}
if "tool_calls" in delta and delta["tool_calls"]:
    for tc in delta["tool_calls"]:
        yield {"type": "tool_call", "id": tc.get("id", ""), "name": tc.get("function", {}).get("name", ""), "arguments": tc.get("function", {}).get("arguments", "")}
```

**Step 4: Verify compile**

```bash
python3 -m py_compile app/providers/openrouter.py app/llm_client.py app/orchestrator.py
```

Expected: no output (success)

---

## Task 6: Update `parse_tool_calls` in providers

**Objective:** Ensure `parse_tool_calls` in OpenRouter provider correctly parses streaming-accumulated tool_calls.

**Files:**
- Modify: `app/providers/openrouter.py` — `parse_tool_calls()`

**Step 1: Verify current implementation handles both streaming and non-streaming**

Current implementation:
```python
def parse_tool_calls(self, raw_response) -> list[dict]:
    message = raw_response.get("choices", [{}])[0].get("message", {})
    tool_calls = message.get("tool_calls", [])
    ...
```

This already works for non-streaming. For streaming, we need to accumulate tool_call deltas from the SSE stream. The accumulation should happen in `stream_manager.py` or in the orchestrator.

**Decision:** For simplicity in the streaming path, keep using the existing `<command>` block parsing for the FIRST pass (main LLM response). Only the synthesis loop uses native function calling (which is non-streaming). This avoids needing to refactor the entire streaming pipeline.

**Revised scope:** Only `_run_synthesis_async` (non-streaming CLI path) gets the native function calling treatment. The streaming path keeps its current behavior but with `suppress_tools=True` (from the previous fix) to prevent infinite loops.

---

## Task 7: Final cleanup — remove `suppress_tools` from streaming path

**Objective:** Since we decided to keep streaming using the suppress approach (Task 6 decision), ensure the streaming path is clean.

**Files:**
- No changes needed — previous fix already added `suppress_tools=True` to streaming synthesis

---

## Verification

```bash
# Compile all changed files
python3 -m py_compile app/tools/respond.py
python3 -m py_compile app/tools/registry.py
python3 -m py_compile app/prompts.py
python3 -m py_compile app/llm_client.py
python3 -m py_compile app/orchestrator.py
python3 -m py_compile app/providers/openrouter.py

# Lint
ruff check app/tools/respond.py app/tools/registry.py app/prompts.py app/llm_client.py app/orchestrator.py app/providers/openrouter.py

# Tests
python3 -m pytest tests/test_commands.py tests/test_db_queries.py -v
```

---

## Risks & Tradeoffs

1. **Streaming function calling complexity:** Full streaming + tool_calls requires accumulating deltas across chunks. Keeping synthesis non-streaming (CLI path only) avoids this.
2. **Provider compatibility:** Chutes provider needs to support function calling too. Verify before deploying.
3. **Tool result format:** Native tool results use `role="tool"` messages, different from current `<details>` markdown blocks. Need to ensure synthesis handles both.
4. **Backward compat:** The `<command>` block protocol still works for the first pass. Only synthesis changes.

---

## Open Questions

1. Should we also refactor the first-pass LLM to use native function calling (instead of `<command>` blocks)? This would be a larger refactor but more consistent.
2. Should `respond` tool be always registered, or only when `suppress_tools=True`?
3. How to handle the case where LLM calls a tool in synthesis but doesn't call `respond` at the end? (fallback: use text content if present)
