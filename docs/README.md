# Documentation

`docs/` is the maintained documentation set for Yuzu Companion. The implementation is authoritative: when documentation and code disagree, update the documentation to match the code.

## Active references

| Area | Document | Ownership |
|---|---|---|
| Product intent | [`product.md`](product.md) | Product hierarchy and interface principles |
| System architecture | [`architecture/`](architecture/) | Runtime topology and backend/frontend boundaries |
| API contract | [`api/`](api/) | Shared HTTP/SSE contract between the frontend and backend |
| Backend | [`backend/`](backend/) | Entry points, providers, streaming, and native tools |
| Frontend | [`frontend/`](frontend/) | Vanilla JS/CSS ownership and event contracts |
| SPA | [`../web/README.md`](../web/README.md) | Vite SPA ownership; consumes the API contract |
| Database | [`database/`](database/) | PostgreSQL schema and tenant invariants |
| Memory | [`memory/`](memory/) | Graph extraction, retrieval, and maintenance boundary |
| Architecture decisions | [`adr/`](adr/) | Immutable accepted decisions |
| Future work | [`roadmap/`](roadmap/) | Future work only |
| Active feature specs | [`specs/`](specs/) | Work that is not yet baseline |

Package-level `README.md` files stay next to code when they describe local ownership. They should link to, not duplicate, the active references above.

## Governance

- Update an existing authoritative document before creating another one.
- Keep one owner per concept; merge overlapping documents instead of letting them drift.
- Verify every technical statement against the current implementation.
- Move completed reports, one-time migrations, superseded architecture, and retired plans to `docs/archive/` when they have historical value.
- Delete obsolete or duplicate documents when they have no historical value. Do not preserve documents “just in case.”
- `docs/scratch/` is disposable and never a source of truth or a dependency of active documentation.
- Roadmaps describe future work, not shipped implementation details.
- Accepted ADRs are immutable. If a decision changes, add a superseding ADR.
- Keep documentation concise, cross-linked, and synchronized with the implementation.

## Audit statuses

- **Active** — current source of truth.
- **Needs Update** — useful document whose facts or links require correction.
- **Merge** — overlapping content consolidated into another document.
- **Archive** — historical material retained outside active references.
- **Delete** — obsolete, duplicate, or empty material with no preservation value.
