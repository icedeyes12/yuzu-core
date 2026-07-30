# Tools Registry and Architecture

Yuzu Companion uses native provider function calling through `app/tools/registry.py`. Tool results are structured data and are validated before frontend rendering.

## Supported tools

| Tool | Purpose | Memory behavior |
|---|---|---|
| `image_generate` | Generate an image through the configured provider | None |
| `http_request` | Fetch public HTTP/HTTPS resources with validation | None |
| `memory_search` | Search tenant-scoped graph nodes and bounded relationships | Read-only graph retrieval |
| `memory_store` | Store an explicit inferred claim as a graph node | Creates a tenant-scoped `memory_nodes` row through `GraphMemoryRepository` and uses graph embedding metadata |
| `multimodal` helpers | Vision routing, image caching, and encoding | None |

## `memory_search`

The tool calls `app.memory.retrieval.retrieve_memory_async()` with the authenticated `user_id`. Search uses graph nodes, optional vector similarity, trigram fallback, bounded relationship expansion, and provenance. It must not query a legacy unified fact table.

## `memory_store`

The tool validates the fact and category, embeds it when the embedding service is available, and persists a graph node with tenant ownership, confidence, importance, and embedding metadata. It does not write a legacy semantic-fact record.

Runtime extraction in `app/memory/memory.py` creates episodes, nodes, relationships, and evidence in one graph pipeline. The Memory Guardian does not invoke this extraction path; it only inspects and conservatively maintains stored graph state.

## Tool contract

- Tool execution flows through `ToolEvent` / `ToolResultEvent` and `execute_tool_event()`.
- Backend tool results contain structured data, not Markdown or HTML presentation.
- Every memory operation requires `user_id` and, where relevant, `session_id`.
- Frontend consumers validate tool results centrally through `validator.js`.
- Legacy XML-style command/tool markup is strip-only cleanup and is not an execution protocol.
