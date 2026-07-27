# Frontend Architecture Contract

Status: current contract for the vanilla JS/CSS frontend.

## Ownership

| Area | Owner | Rule |
| --- | --- | --- |
| Server-rendered page structure | `templates/` | Jinja templates provide stable markup and data attributes. They do not own runtime state. |
| Page entrypoints | `static/js/{home,chat,config,about,sidebar}.js` | Bind page-level events and coordinate modules. They do not own conversation state or DOM rendering internals. |
| Conversation state | `static/js/modules/store.js` | `ConversationStore` is the single source of truth for messages, sessions, and processing state. |
| DOM rendering | `static/js/modules/store-renderer.js` and `static/js/modules/messages.js` | Subscribe to the store and render DOM. Do not append chat state outside the renderer. |
| API/event coordination | `static/js/modules/event-router.js`, `history.js`, `router.js` | Translate API/SSE events into store actions and navigation. |
| Tool rendering | `static/js/modules/tool-renderer/` | Validate normalized tool payloads and render tool cards only. |
| Reusable DOM helpers | `static/js/modules/dom-utils.js` and tool-renderer `dom-utils.js` | Escaping, safe URLs, and state-preserving DOM helpers only. |
| Visual tokens and CSS | `static/css/theme.css` and per-page/component stylesheets | CSS owns visual values, states, layout, and motion. |
| Visual identity data | `static/js/provider-registry.js`, `runtime-icon-renderer.js`, `badge-registry.js` | Return definitions and compatibility helpers; do not own application state or network calls. |

## Data Flow

```text
API / SSE
   -> event-router / history / page coordinator
   -> ConversationStore
   -> DOMRenderer
   -> DOM

CSS: design tokens -> component styles -> page composition
Visual identity: registry definitions -> UI renderer -> DOM
```

`ConversationStore` and `DOMRenderer` must not be bypassed for conversation updates. API payloads are normalized before renderer consumption.

## Visual Layer Boundaries

- `theme.css` owns core and semantic design tokens.
- Component styles consume semantic tokens; they do not encode theme-specific values.
- `provider-registry.js` owns provider identity only: names, family, logo metadata, accent, and lifecycle flags.
- `runtime-icon-renderer.js` owns runtime-generated SVG definitions and rendering. It does not know providers or application state.
- `badge-registry.js` owns badge labels and classes. It does not render provider logos.
- `visual-registry.js` is a compatibility facade for existing provider and badge callers; runtime icons are consumed directly from `RuntimeIconRenderer`. New code should import the narrow registry contract where module imports are available.
- Renderers convert definitions into DOM/HTML. Registries must not make network requests or mutate application state.

Allowed dependency direction:

```text
provider-registry   runtime-icon-renderer   badge-registry
         \              |              /
                 visual facade
                       |
                 page/renderers
```

Provider identity may select a provider logo or fallback icon by data, but icon definitions must not inspect provider strings. UI components must not recreate provider mappings.

## Adding Things Safely

### Provider

1. Add one contract-complete entry to `static/js/provider-registry.js`.
2. Use an existing family and badge where possible.
3. Add a logo asset only when it is owned, reusable, and available in both theme contexts; otherwise use the registry placeholder.
4. Do not add provider conditionals to components or renderers.

### Icon

1. Add one definition to `static/js/runtime-icon-renderer.js` with a stable name and `viewBox`.
2. Use `currentColor` so CSS controls the semantic color.
3. Keep accessible naming at the consuming button/control; decorative icons must be hidden from assistive technology.
4. Do not add a second ad-hoc inline SVG for an existing icon.

### Theme

1. Add values to the existing semantic token contract in `static/css/theme.css`.
2. Do not introduce color-named variables or component-specific theme aliases.
3. Validate contrast and reduced-motion behavior before committing.

### Component

1. Keep markup in the relevant template or renderer.
2. Put visual rules in the owning component/page stylesheet.
3. Reuse spacing, radius, elevation, state, and motion tokens.
4. Keep state changes in classes or data attributes; reserve inline styles for genuinely runtime values such as drag position, progress, or measured layout.

## Protected Boundaries

Do not change the backend, API contract, SSE protocol, `ConversationStore`, or renderer flow while making visual-only changes. If a visual change appears to require one of those changes, stop and split the work into a separately approved task.
