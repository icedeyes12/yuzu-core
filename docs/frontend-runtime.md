# Frontend Runtime Ownership

Status: current ownership contract for the vanilla frontend.

## Responsibility map

| Responsibility | Owner | Boundary |
|---|---|---|
| Conversation state | `static/js/modules/store.js` | Owns messages, active session, generation state, and errors. Publishes state changes. |
| Conversation DOM | `static/js/modules/store-renderer.js` | The only subscriber that creates and updates message DOM inside `#chatContainer`. |
| Message structure and markdown formatting | `static/js/modules/messages.js` | Creates message elements, formats timestamps, and exposes the markdown rendering function used by the DOM renderer. |
| Tool result presentation | `static/js/modules/tool-renderer/` | Converts normalized tool events into tool-card markup. It does not own conversation state. |
| SSE/event normalization | `static/js/modules/event-router.js` | Converts stream events into `ConversationStore` mutations. It does not render DOM. |
| Session history requests | `static/js/modules/history.js` | Loads and switches history, then updates `ConversationStore`. |
| Session URL state | `static/js/modules/router.js` | Owns URL parsing, `pushState`, and `popstate`; delegates session loading to the chat entry point. |
| Chat bootstrap and cross-module orchestration | `static/js/chat.js` | Initializes chat modules and coordinates session switching. It does not render individual messages. |
| Sidebar DOM and session controls | `static/js/sidebar.js` | Owns sidebar/session/theme/auth UI and its event handlers. |
| Configuration UI | `static/js/config.js` | Owns provider/model/profile/knowledge/settings DOM and requests for that page. |
| Attachment UI and upload stream | `static/js/modules/multimodal.js` | Owns attachment selection, preview, multimodal controls, and the send request containing attachments. |
| Scroll-button behavior | `static/js/modules/scroll.js` | Owns the scroll button and the chat-container scroll/resize listeners. |
| Input layout and submit key behavior | `static/js/modules/input.js` | Owns textarea resizing, input-area measurement, and desktop Enter handling. Runtime layout values remain inline because they are measured values. |
| Loading/error chat overlays | `static/js/modules/skeleton.js` and `static/js/modules/store-renderer.js` | Skeleton owns loading markup; DOMRenderer owns generation/error indicators. |
| Provider identity | `static/js/provider-registry.js` | Owns provider metadata only. It does not render HTML or perform network requests. |
| UI badge definitions | `static/js/badge-registry.js` | Owns badge metadata/rendering only. |
| Runtime icons | `static/js/runtime-icon-renderer.js` | Owns the small runtime-generated icon set used where an `<img>` asset cannot be used. It is not a provider registry. |
| Theme tokens | `static/css/theme.css` | Owns semantic visual values; JavaScript only changes the selected theme attribute. |
| Network access | Feature owner modules | Existing page-specific requests remain in `config.js`, `sidebar.js`, `history.js`, `chat.js`, and `multimodal.js`. The sidebar fetch wrapper is the single cross-cutting auth/BYOK boundary. |

## Event ownership rules

- A module registers listeners only for the DOM region or browser API it owns.
- Chat message copy uses one delegated listener in `messages.js`.
- The chat-container scroll listener belongs to `scroll.js`; history does not register a second listener.
- URL `popstate` belongs to the singleton `RouterManager`.
- Page bootstrap listeners use `{ once: true }` where initialization must happen once.
- Runtime values such as measured textarea height and scroll-button position may use inline styles; static presentation belongs in CSS.

## DOM rules

`DOMRenderer` is the sole owner of message children under `#chatContainer`. Feature modules may read chat elements for behavior, but must not append conversation messages outside the store/render cycle. Sidebar, config, and multimodal own their separate DOM regions.

## Global API rules

Application globals are not used for module communication. Page entrypoints and shared UI modules are ES modules and communicate through imports. Remaining `window` usage is limited to browser APIs (`fetch`, `location`, `history`, `confirm`, `setTimeout`), third-party globals loaded by templates (`marked`, `hljs`, `mermaid`, `renderMathInElement`), and narrow one-time guards for delegated browser behavior. Runtime icons, provider identity, storage keys, session routing, and chat state are imported directly.

## Registry rules

Registries return identity/definition data or narrowly scoped presentation output. Provider metadata, badges, and runtime icons remain separate. No registry performs network access, owns application state, or subscribes to DOM events.
