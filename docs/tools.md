# Tools Registry and Architecture

Yuzu-Companion features a pluggable tool system managed by the central registry in `app/tools/registry.py`.

## Tool Invocation (The `<command>` Tag)

To prevent LLM autoregressive hallucinations (such as looping or making up fake markdown `<details>` blocks), tool invocation uses a strict syntactic boundary:

**LLM Generation Format:**
```xml
<command>tool_name "arg1" "arg2"</command>
```

When the `StreamFilter` detects this tag, it halts yielding the command text to the user interface, parses the tool request, and forwards it to the `registry.py` dispatcher.

## Tool Output (The `<tools>` Tag)

After the tool executes, the system injects the tool's result back into the LLM context using the following format:

**System Injection Format:**
```xml
<tools>
[Tool Result for tool_name]
Status: Success
...data...
</tools>
```
This forces the LLM to process the result logically without trying to continue formatting a markdown accordion block.

## Supported Tools

All tools are located in the `app/tools/` directory and must implement an `execute(args, session_id)` interface.

1. **`image_generate`**
   - **Usage:** `<command>image_generate "prompt"</command>`
   - **Backend:** Calls the Chutes Image Generation API (Qwen Image Gen).
   - **Result:** Saves the image to disk and returns the local `static/generated_images/` path.

2. **`http_request`**
   - **Usage:** `<command>http_request "url"</command>`
   - **Backend:** Fetches raw text or HTML from the web.

3. **`memory_search`**
   - **Usage:** `<command>memory_search "query"</command>`
   - **Backend:** Queries the `semantic_facts` pgvector table for similar memories using RRF hybrid scoring.

4. **`memory_store`**
   - **Usage:** `<command>memory_store "fact content"</command>`
   - **Backend:** Persists a new semantic fact directly to long-term memory.