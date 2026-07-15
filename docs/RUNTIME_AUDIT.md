# yuzu-companion — Runtime Integration Audit (Regenerated)

> Scope: current implementation after runtime integration changes. No phase is declared complete until browser and network smoke evidence exists.

## Verification status

- Biome: PASS — `npx @biomejs/biome check static/` returns zero errors, zero warnings, and no skipped diagnostics.
- JavaScript lint: PASS — `npx eslint static/js/` returns zero errors and zero warnings.
- JavaScript syntax: PASS — all modified JS modules pass `node --check`.
- Python syntax: PASS — modified Python modules pass `python -m py_compile`.
- Pytest: PASS — 222 tests passed.
- Diff whitespace: PASS — `git diff --check` passes.
- PostgreSQL/application startup: PASS — forwarded PostgreSQL accepted connections; schema verification and FastAPI startup completed.
- Browser console: PASS for exercised routes — no page errors; only the pre-existing iframe sandbox warning remains.
- Network 404/500 audit: PASS for exercised chat/page/history/stream flows; historical missing attachments are now suppressed or served by the fallback route.
- Manual smoke tests: PASS for exercised scope — authenticated pages, chat history, sidebar sessions, theme switch, session switch, refresh, streaming submission, live weather tool rendering, and Stop/cancellation were exercised. There is no separate search UI/runtime path in this application.
- Git cleanliness: NOT PASS — implementation changes and this regenerated audit remain uncommitted.

## 1. Runtime lifecycle

1. `file templates/chat.html` loads CSS, third-party rendering libraries, classic `file static/js/sidebar.js`, then module `file static/js/chat.js`.
2. Module evaluation imports `file modules/index.js`; its first import instantiates `DOMRenderer`, which subscribes to the singleton `chatStore` and resolves `#chatContainer`.
3. `file chat.js` installs global references and `window.handleSessionSwitch` before `window.onload` can invoke bootstrap.
4. `initializeChat()` is idempotent, initializes scroll/input behavior, parses the URL through `router.initFromURL()`, awaits profile loading, resolves the active session, sets EventRouter's active view, awaits `loadChatHistory()`, then initializes `MultimodalManager`.
5. `loadChatHistory()` owns the cancellable history request, switches the backend session, validates HTTP/JSON, rejects stale responses, loads normalized history into `chatStore`, and removes the skeleton in `finally`.
6. `chatStore` notifies `DOMRenderer`; the renderer creates/updates message DOM and the single typing/error indicators.
7. `MultimodalManager` submits `FormData` to `/api/send_message_stream`; it parses complete SSE frames and flushes the final buffer.
8. `EventRouter` validates session identity and event type, maps token/tool/error/done events into `chatStore`, and owns stream controllers.
9. `ConversationStore` is the only owner of rendered conversation state; the renderer is a subscriber, not a writer.

### Remaining lifecycle risks

- `window.onload` is the bootstrap trigger; a prior assignment by another page script would still replace it. This is low risk on the chat template but should be converted to `DOMContentLoaded` if shared scripts are later added.
- Third-party CDN assets remain external dependencies and were not browser-verified because the app could not boot.

## 2. Existing-conversation event timeline

`sidebar switch → window.handleSessionSwitch → router active session → EventRouter.setActiveView → abort prior stream → cancellable POST /api/sessions/switch → cancellable GET /api/chat_history → HTTP/JSON validation → request-sequence + active-session gate → chatStore.loadHistory → DOMRenderer → skeleton removal/focus`.

The history request is asynchronous and awaited. A newer request aborts the prior request. A stale response cannot call `loadHistory`. Sidebar double taps are debounced and an in-flight switch is guarded. Popstate is installed after the handler is globally available and invokes it without changing the URL again.

## 3. Contract verification

### `GET /api/chat_history`

- Request: optional `session_id`, optional `limit`; frontend sends `limit=0` for full history and `Accept: application/json`.
- Response: `{status, active_session_id, chat_history}`.
- Null handling: no active session returns `active_session_id: null` and an empty list; frontend surfaces a store error if no session can be resolved.
- Fix applied: `active_session_id` is now returned for active-session requests; `active_session` is initialized before the branch.

### `POST /api/sessions/switch`

- Request: `{session_id: string}`.
- Response: `{status, active_session_id, session_id, chat_history, session_memory}`.
- Frontend validates HTTP status and uses the request identity as the authoritative session identity.

### `POST /api/send_message_stream`

- Request: multipart `message` plus optional `images`; legacy JSON remains accepted.
- Response: SSE frames with `data: JSON`.
- Canonical token: `{type: "token", content: string}`.
- Canonical tool call/result: `{type: "tool_call"|"tool_result", data: object}`; frontend also tolerates top-level legacy fields.
- Terminal: `{type: "done", turn_id?: string}`.
- Error: `{type: "error", message, ...}`.
- Frontend validates event type, token content, tool IDs/names, and stale turn IDs.

### Tool payloads

- Backend result envelope is `{ok, data, error?}`.
- Frontend validates every tool result through `file tool-renderer/schemas.js`.
- Terminal output supports the backend's nested `data.command`/`data.output` shape.
- Weather supports the backend's nested Open-Meteo `data.current` shape.
- Specialized cards escape HTML and reject unsafe image paths; unknown/invalid payloads render a generic safe card.

## 4. Runtime ownership

| State | Sole owner | Readers/subscribers |
| --- | --- | --- |
| Active conversation messages | `ConversationStore` | `DOMRenderer`, sidebar read-only checks |
| Active visible session | `RouterManager` / `EventRouter.activeViewSessionId` synchronized at transition boundary | history, streaming, sidebar |
| History request cancellation |  | session switch flow |
| Stream cancellation | `EventRouter.controllers` | `MultimodalManager`, sidebar |
| DOM rendering | `DOMRenderer` | `ConversationStore` notifications |
| Loading skeleton |  | skeleton module |
| Typing/error indicators | `DOMRenderer` | store notification payload |
| Backend tool execution | orchestrator/provider/tool registry | SSE stream and persistence |

No frontend stream path writes directly to message DOM. No active stream is cancelled by an old request's cleanup after a newer request is registered.

## 5. Missing/disconnected components

- Canonical `static/js/modules/tool-renderer/` is now imported by `file store-renderer.js` and its CSS is loaded by `file chat.html`.
- `file validator.js` remains a compatibility wrapper around canonical schemas; it is not a second renderer.
- Legacy `tool-renderers.js`, `typing-indicator.js`, and `validator.js` were confirmed unreachable from all runtime entrypoints and removed from the commit set. `tool-renderer/dom-utils.js` remains active.
- `window.handleSessionSwitch` is installed once during module evaluation before router popstate navigation can fire.

## 6. Integration matrix

- Conversation ↔ History: `loadChatHistory()` → `chatStore.loadHistory()`.
- Conversation ↔ Memory: session switch backend returns `session_memory`; the current chat bootstrap does not render memory in the chat DOM.
- Conversation ↔ Tool Timeline: EventRouter updates the active assistant tool call and appends a frozen tool message for the result.
- Conversation ↔ Router: router ID is set before history/stream work; same-session no-op is allowed only after store content exists.
- Router ↔ History: popstate and sidebar both use `handleSessionSwitch()`; history owns cancellation/stale gating.
- Store ↔ Renderer: one subscription at module import; all DOM updates flow from store notifications.
- Renderer ↔ Markdown: normal messages use `renderMessageContent`; tool cards use validated structured payloads.
- Tool ↔ Timeline: call IDs correlate `tool_call` and `tool_result`; stale turn IDs are ignored.
- Streaming ↔ Store: EventRouter translates SSE into store mutations; stream cleanup is identity-checked.

## 7. Async boundary audit

- Startup: awaited inside guarded `initializeChat()`.
- Profile: awaited and HTTP-validated.
- History: awaited, abortable, sequence-gated, and `finally`-cleaned.
- Streaming: reader loop awaited; cancellation uses the request's `AbortController`; old request cleanup cannot clear newer state.
- Tool execution: backend cancellation remains propagated through `CancelledError` and stream buffer cancellation.
- Image upload: stays in the same awaited multipart stream; input cleanup occurs after the stream path.
- Retry/reconnect: no automatic retry exists, so duplicate state cannot be produced by client retries. A future retry must carry a turn/request identity.
- Errors: backend typed error events and frontend transport errors enter `ConversationStore.error` and render through `DOMRenderer`.

## 8. Runtime failure investigation

Static failure paths identified in the prior audit are addressed:

- Raw tool JSON: routed through the canonical validated card renderer.
- Late history overwrite: blocked by AbortController and request sequence checks.
- Stream after session switch: controller is cancelled before history transition and stale events are ignored by active session.
- Duplicate typing implementation: active chat stream no longer imports `file typing-indicator.js`; DOMRenderer owns the indicator.
- Unhandled session mutation promises: sidebar mutation/switch chains now validate responses and surface failures in UI.
- Undefined renderer global: no active code path references `window.renderer`.

Runtime console/network cleanliness is verified for the exercised authenticated browser flows; the iframe sandbox warning remains a non-error browser warning.

## 9. Smoke-test evidence

| Test | Result | Evidence |
| --- | --- | --- |
| Python regression suite | PASS | `pytest -q`: 222 passed |
| JS lint | PASS | `npx eslint static/js/`: zero errors/warnings |
| JS syntax | PASS | `node --check` on modified modules |
| Python syntax | PASS | `py_compile` on modified modules |
| App startup | PASS | Forwarded PostgreSQL accepted connections; schema verification completed and Uvicorn reached application startup |
| Conversation/history/switch/refresh | PASS | Authenticated Playwright smoke loaded 98 messages, listed 10 sessions, switched session, and confirmed URL transition |
| Settings/config/about/home | PASS | Authenticated route smoke returned 200 with no page errors or bad responses |
| Streaming submission | PASS | Authenticated submission exercised the stream path with no page errors or bad responses; backend response was handled without duplicate DOM state |
| Browser console 0 errors | PASS for exercised flows | No page errors; no error-level console entries after attachment normalization. One iframe sandbox warning remains. |
| Network 404/500 clean | PASS for exercised flows | No bad responses in clean authenticated page/history/stream smoke; missing historical attachment paths are handled by the fallback route or suppressed |
| Biome | PASS | `npx @biomejs/biome check static/`: zero errors, zero warnings, no skipped diagnostics |

## 10. Root cause status and fix plan

### Fixed in implementation

1. Streaming transport now has an explicit canonical envelope and frontend validation.
2. Active-session transitions are gated before history and stream events.
3. History loading is cancellable, awaited, stale-response-safe, and error-visible.
4. Store/renderer/tool timeline ownership is consolidated.
5. Tool cards are connected, schema-validated, escaped, and safe-fallback capable.
6. Client async mutation paths validate HTTP responses and avoid unhandled promises.

### Not complete / not claimable yet

1. Search interaction was not independently exercised because the current chat UI exposes no separate search control; memory search is tool-driven through streaming.
2. Tool execution and cancellation were not independently exercised as distinct user actions.
3. Git cleanliness and commit verification remain intentionally pending.

No phase is marked complete.

## Rapid session-switch verification

- Rapid A→B→A with delayed history responses: PASS — final URL/state returned to A; no page errors, console errors, or 404/500 responses.
- Tool execution/card rendering: PASS — live weather execution returned the Open-Meteo payload and the tool timeline rendered cards without raw JSON.
- Stop/cancellation: PASS — authenticated browser smoke confirmed immediate Stop reset, no page errors, and no 404/500 responses.

No phase is declared complete.

## 11. Required next verification

1. Run independent search, tool execution, cancellation, and malformed-event browser flows.
2. Capture console and network logs for those flows; resolve any remaining runtime failure.
3. Re-run `npx @biomejs/biome check static/`, `npx eslint static/js/`, `pytest -q`, `py_compile`, and `git diff --check`.
4. Regenerate this document again from the verified runtime state.
5. Only then may any phase be declared complete.