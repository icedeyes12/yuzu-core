# Asset Consolidation Report

Status: Phase 3.6 low-risk consolidation.

## Library decision

- UI assets: Lucide Icons, fetched from the official Lucide repository.
- Provider assets: Simple Icons, fetched from the official Simple Icons repository.
- No icon-library migration was performed. Existing dynamic registry rendering remains unchanged.

## Ownership

- `static/assets/icons/`: generic UI controls only.
- `static/assets/logos/providers/`: provider and authentication brand marks.
- `static/assets/logos/brands/`: reserved for non-provider brand assets.
- `static/assets/status/`: reserved for status assets.
- `static/assets/illustrations/`: reserved for illustrations and empty states.

## Consolidated assets

- Added five fetched Lucide UI assets: arrow-down, send, sun, maximize, and x.
- Added nine fetched Simple Icons provider assets: Anthropic, Cloudflare, DeepSeek, GitHub, Google, Meta, Ollama, OpenRouter, Qwen, plus the existing provider set represented by the registry.
- Replaced five static inline SVG groups in `templates/chat.html` and two authentication SVG groups in `templates/login.html`.
- Replaced the duplicated authentication SVG strings in `static/js/sidebar.js` with external brand asset references.
- Registered approved provider logo paths for OpenRouter, Anthropic, Google, DeepSeek, and Ollama. Other providers retain the shared placeholder until an approved asset is available.

## Cleanup results

- Inline SVG in templates: 7 groups removed; only the deliberate dynamic runtime SVG renderer remains in `static/js/runtime-icon-renderer.js`.
- Provider mappings remain centralized in `static/js/provider-registry.js`.
- No dead asset was deleted because the repository had no previously tracked binary asset with a provably unused reference.
- No SVG was hand-generated. Downloaded assets retain upstream path data and were not visually redesigned.

## Bundle hygiene

The external assets are small standalone SVGs and are loaded only by the pages/components that use them. Provider logos are not preloaded globally; they are resolved through the provider registry. Further lazy-loading is not justified for these small controls. Runtime-generated SVGs remain in the dedicated `static/js/runtime-icon-renderer.js` module; static UI assets stay under `static/assets/`.
