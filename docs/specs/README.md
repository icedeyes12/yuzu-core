# Feature specifications

This directory is for active feature specifications: intended behavior, contracts, and boundaries for work that is not yet the baseline implementation.

- [`yuzu-sandboxd.md`](yuzu-sandboxd.md) — authenticated sandbox-node execution, transport semantics, bootstrap integrity, isolation, and workspace confinement.
- [`frontend-split-migration.md`](frontend-split-migration.md) — incremental split of the Jinja/static web UI into a Vite SPA and an API-only FastAPI backend.

A spec is not a roadmap and must not claim that an unimplemented feature exists. When a feature becomes the baseline, fold its stable behavior into the relevant active reference and archive or delete the spec.
