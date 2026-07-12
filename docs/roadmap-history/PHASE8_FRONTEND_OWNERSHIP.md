# Frontend Ownership Matrix (Phase 8 Audit)

## Current State Assessment
As identified, the current frontend relies heavily on the DOM as the primary datastore, leading to cyclical patching, state loss, and brittle `innerHTML` manipulation.

### Current Owners

| Concept | Current Owner | Mechanism | Flaw |
| :--- | :--- | :--- | :--- |
| **Conversation (Full Transcript)** | DOM / Network Fetch | `document.getElementById('chatContainer')`, `fetch('/api/chat_history')` | No in-memory representation. Traversing history requires querying DOM nodes. |
| **Stream (Active Delta)** | `StreamManager` (String) | `stream.buffer += chunk` | Treats all incoming SSE data as a single monolithic string, ignoring tool lifecycle bounds. |
| **Message** | DOM Element | `<div data-message-id="...">` | State is tied to markup. Parsing is needed to read state back out. |
| **Tool / FC** | DOM `<details>` tags | Regex extraction during string patching + `[ACCORDION PRESERVATION]` inline hacks | Lifecycle (Started, Progress, Finished) is approximated by injecting HTML strings rather than state transitions. |
| **Attachments** | DOM `<img>` / `<a>` tags | Embedded via Markdown parsing | Backend sends JSON attachments, but frontend turns them into Markdown strings before rendering, losing object context. |
| **Abort / Cancellation** | `state.js` global | `currentAbortController` | Unscoped global variable. Not tied to a specific session or message stream cleanly. |
| **Rerender / Layout** | Interspersed globally | `scrollToBottom()`, manual `innerHTML` overrides in `multimodal.js` and `history.js` | Layout calculations happen simultaneously with data parsing, causing thrashing and scroll-jumping. |

## Target State (Phase 8 Design)

We will introduce `ConversationStore` as the single source of truth for the active session, decoupling data from the DOM.

### Proposed Owners

| Concept | Proposed Owner | Mechanism |
| :--- | :--- | :--- |
| **Conversation (Full Transcript)** | `ConversationStore` | `Map` or Array of immutable `ConversationEvent` objects. |
| **Stream (Active Event Flow)** | `EventRouter` (New) | Decodes SSE into structured signals (`AssistantStarted`, `ToolProgress`, etc.) and pushes them to `ConversationStore`. |
| **Message** | `ConversationEvent` Object | Pure JS object holding `id`, `role`, `content`, `attachments`, `tool_calls`. |
| **Tool / FC** | `ToolCall` Object | Array attached to an `AssistantEvent`. Managed by `ConversationStore`. |
| **Attachments** | `Attachment` Object | Array attached to `UserEvent` or `ToolResultEvent`. |
| **Abort / Cancellation** | `ConversationStore` | Handled at the session level internally. |
| **Rerender / Layout** | `Renderer` | Subscribes to `ConversationStore` events (`onMessageAdded`, `onMessageUpdated`). Linearly maps State -> DOM. |

## The "Freeze" Principle
1. A message in `ConversationStore` is active only while its generator is running.
2. During generation, `content` and `tool_calls` may accumulate.
3. Once the `done` event is received, the message is marked `isFinished = true` and frozen.
4. The `Renderer` will NEVER `innerHTML` replace a frozen message. If edits occur, a new event must supersede it.

## Next Implementation Steps
1. Create `static/js/modules/store.js` (`ConversationStore`).
2. Map `window.activeSessionId` directly into the store.
3. Update `stream-manager.js` to dispatch typed events to the Store instead of string concatenating.
4. Update `Renderer` to consume the Store.