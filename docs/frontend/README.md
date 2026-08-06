# Frontend architecture

**Status:** Active ownership contract for the vanilla JavaScript/CSS frontend.

## Data flow

```text
API / SSE
  -> page coordinators and event normalization
  -> ConversationStore
  -> DOMRenderer
  -> chat DOM
```

Conversation state must not be updated by bypassing the store. `DOMRenderer` is the only owner of message children under `#chatContainer`.

## Responsibility map

| Responsibility | Owner |
|---|---|
| Page bootstrap and cross-module coordination | `static/js/chat.js`, `home.js`, `config.js`, `about.js` |
| Conversation state | `static/js/modules/store.js` (`ConversationStore`) |
| Conversation DOM | `static/js/modules/store-renderer.js` (`DOMRenderer`) |
| Message structure/Markdown | `static/js/modules/messages.js` |
| SSE normalization and stream lifecycle | `static/js/modules/event-router.js` |
| History loading and session switching | `static/js/modules/history.js` |
| URL state and `popstate` | `static/js/modules/router.js` |
| Sidebar, auth, session controls | `static/js/sidebar.js` |
| Attachments and multimodal stream request | `static/js/modules/multimodal.js` |
| Scroll button and scroll listeners | `static/js/modules/scroll.js` |
| Input sizing and submit behavior | `static/js/modules/input.js` |
| Loading skeleton | `static/js/modules/skeleton.js` |
| Tool payload validation | `static/js/modules/tool-renderer/schemas.js` |
| Tool cards | `static/js/modules/tool-renderer/` |
| Provider identity metadata | `static/js/provider-registry.js` |
| Provider identity facade | `static/js/visual-registry.js` |
| Badge metadata and rendering | `static/js/badge-registry.js` |
| Runtime-generated icons | `static/js/runtime-icon-renderer.js` |
| Visual tokens | `static/css/theme.css` and component stylesheets |

## Event contract

The backend stream sends JSON SSE data events with `type` values including `token`, `tool_call`, `tool_result`, `error`, and `done`. `event-router.js` validates the event shape, tracks turn IDs and pending tool calls, and dispatches store mutations. Tool result payloads are normalized by `validateToolPayload()` in `schemas.js`; invalid payloads render a safe generic card.

## Visual identity rules

Provider metadata belongs in `provider-registry.js`; components must not recreate provider mappings. `visual-registry.js` remains a compatibility facade for existing consumers. Provider logos, generic icons, status visuals, and badges are separate asset concepts. Registries do not perform network requests or own application state.

## Editing rules

- Keep conversation state changes in `ConversationStore`.
- Keep chat message DOM changes in `DOMRenderer`.
- Keep network requests in the feature modules that own the feature.
- Keep static visual values in CSS; inline styles are for measured/runtime values only.
- Do not change backend contracts as part of a visual-only change.
- Run `node --check` and Biome for changed JavaScript.
