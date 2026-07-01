# Tools Registry and Architecture

Yuzu-Companion features a pluggable tool system managed by the central registry in `app/tools/registry.py`.

## Tool Invocation

Tool execution is driven by provider `tool_calls` and `ToolEvent` / `ToolResultEvent` objects. Legacy XML-style markup is cleanup text only and is not an active protocol.

## Supported Tools

All tools are located in the `app/tools/` directory and must implement an `execute(args, session_id)` interface.

1. **`image_generate`**
   - **Usage:** native function call with `prompt`
   - **Backend:** Calls the Chutes Image Generation API (Qwen Image Gen).
   - **Result:** Saves the image to disk and returns the local `static/generated_images/` path.

2. **`http_request`**
   - **Usage:** native function call with `url`
   - **Backend:** Fetches raw text or HTML from the web.

3. **`memory_search`**
   - **Usage:** native function call with `query`
   - **Backend:** Queries the `semantic_facts` pgvector table for similar memories using RRF hybrid scoring.

4. **`memory_store`**
   - **Usage:** native function call with `fact`
   - **Backend:** Persists a new semantic fact directly to long-term memory.