# Native tools

**Status:** Active reference. Registry authority: `app/tools/registry.py`.

Tool calls originate from provider-native `tool_calls`, become structured events, execute through the central registry, and return structured results. Backend tools do not format Markdown or HTML for the frontend.

## Registered tool names

The registry currently loads these names and aliases:

- `image_generate` and alias `imagine`
- `image_edit`
- `http_request` and alias `request`
- `memory_search`
- `memory_store`
- filesystem operations: `read`, `write`, `ls`, `mkdir`, `rm`
- `terminal`
- `python`
- `sql`
- `ask_rei`
- `weather`

The exact schemas are defined in the corresponding tool modules and exposed through `get_tool_definitions()`; this document intentionally does not duplicate their argument tables.

## Dispatch and persistence

`execute_tool_event()` is the canonical structured event path used by orchestration. `execute_tool()` is the registry's lower-level dispatch function. Session and tenant identifiers are injected where a schema requires them. Tool results are persisted as tool-role messages with correlation IDs so history can reconstruct the assistant/tool sequence.

## Frontend boundary

The browser receives tool events over SSE or history payloads. `static/js/modules/tool-renderer/schemas.js` resolves aliases, validates payloads, normalizes known schemas, and falls back to a generic card on validation failure. `static/js/modules/tool-renderer/` owns presentation only.

## Security boundary

Filesystem, shell, Python, and SQL tools are privileged operations and must follow the authorization and confirmation behavior in their implementations. Do not add new execution paths outside the registry. Legacy XML-style markup is strip-only cleanup and is never a live protocol.
