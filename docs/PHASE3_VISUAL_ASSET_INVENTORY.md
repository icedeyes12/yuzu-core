# Phase 3 — Visual Asset Inventory

## Scope
Audited the committed Phase 2 frontend presentation layer without changing application behavior.

## Asset map

| Asset / pattern | Location | Usage | Reusable | Status | Owner |
|---|---|---|---|---|---|
| Favicon ICO | `static/favicon.ico` | Browser favicon via `/favicon.ico` | Yes | Live | `main.py` route |
| Inline SVG UI icons | `templates/*.html` | Header, send, preview, home cards, auth providers | Partly | Live | Page templates |
| Runtime SVG icon map | `static/js/modules/multimodal.js` | Multimodal menu and controls | Yes | Live | Multimodal module |
| Runtime SVG provider icons | `static/js/sidebar.js` | Auth section provider buttons | Yes | Live | Sidebar module |
| Runtime SVG tool icons | `static/js/modules/tool-renderer/*` | Tool cards and status indicators | Partly | Live | Tool renderer |
| CSS generated graphics | `static/css/style.css`, `static/css/components/header.css`, page CSS | Select arrows, affection icon, decorative UI | No | Live | Owning stylesheet |
| Attachment images | `static/uploads/`, `static/generated_images/`, `static/image_cache/` | Runtime user/generated media | No | Runtime | Multimodal/image routes |
| Markdown diagrams | `static/css/marked.css` | Mermaid and markdown rendering | No | Live | Markdown stylesheet |

No standalone SVG, PNG, WebP, JPG, or GIF assets are present in the repository. The only checked-in raster/icon asset is the favicon.

## Accessibility findings

- Decorative template SVGs generally use `aria-hidden="true"`; provider/auth SVGs are decorative inside labelled controls.
- Runtime tool/weather symbols are marked `aria-hidden`, but status meaning is also expressed in surrounding text.
- The offline lightning emoji is decorative but currently lacks an explicit `aria-hidden` boundary.
- Weather condition emoji are presentation-only and currently hidden from assistive technology.
- Dynamic attachment images use a generic `alt="Attachment"`; this is functional but not descriptive.

## Icon proposal

Do not migrate to a public icon library in this phase. The app uses a small, locally-owned set of inline SVGs plus provider/brand marks. A library migration would touch templates, runtime HTML, and interaction snapshots without a clear visual or maintenance payoff. If approved later, Lucide is the best candidate because its SVG conventions match the existing outline icons and its browser usage is straightforward; it must remain separate from provider logos and weather identity.

## Provider identity

Provider cards currently render provider names and controls but do not have provider logos. Do not substitute emoji. A future provider-logo system should use explicit brand assets or a neutral generated placeholder, owned by the provider-card component.

## Motion inventory

Motion is distributed across page styles, shared utilities, markdown, and component styles. Existing keyframes are referenced; no safe dead-keyframe deletion was made. The current visual language has no single authoritative motion map yet.

## Safe Phase 3 implementation candidates

1. Add a small local semantic icon/status class layer for tool status and tool-card symbols, keeping existing behavior and DOM content stable.
2. Mark the offline decorative symbol explicitly as decorative.
3. Add a neutral provider-card placeholder hook only if the existing provider contract can consume it without changing behavior.

No public icon-library migration or broad asset rewrite should proceed without approval.

## Phase 3.6 hygiene findings

- No standalone SVG, PNG, WebP, JPG, or GIF is checked into the frontend. The only checked-in binary asset is `static/favicon.ico`, served by `main.py` and therefore live.
- The empty asset directories under `static/assets/` are intentional ownership boundaries for future assets; they contain only `.gitkeep` files and no orphaned visual files.
- Runtime image directories (`static/uploads/`, `static/generated_images/`, and `static/image_cache/`) are application data, not bundled frontend assets, and were not modified.
- Provider, badge, and UI icon definitions have dedicated owners in `static/js/provider-registry.js`, `static/js/badge-registry.js`, and `static/js/runtime-icon-renderer.js`. No separate provider logo files or duplicate asset paths exist.
- CSS animation references were checked against their keyframes. No unreferenced keyframe was removed speculatively. The only safe cleanup was removing unused generic animation helpers from `static/css/style.css`; live `fadeIn` and `spin` keyframes remain because chat, skeleton, typing, and loading components reference them.

## Bundle hygiene recommendations

- Keep the favicon as the only static binary until owned provider or brand artwork is available; there is no image bundle to optimize currently.
- Keep provider/icon/badge registry scripts loaded once per page before their consumers. They are small synchronous compatibility registries and are not candidates for lazy loading while the pages use them during initial render.
- If standalone provider logos are added later, store them under `static/assets/logos/providers/`, reference them only from `provider-registry.js`, and measure them before adding them to every page.
