# ADR 0006: Documentation taxonomy

- Status: Accepted
- Date: 2026-08-06

## Context

Documentation, plans, reports, and drafts had been mixed together. That made it unclear which files described the current implementation and encouraged duplicate documents.

## Decision

`docs/` is the documentation source of truth. Its maintained structure is:

- `docs/architecture/` — system topology and ownership boundaries
- `docs/backend/` — backend behavior, HTTP, streaming, and tools
- `docs/database/` — persistence and schema invariants
- `docs/frontend/` — browser ownership and event contracts
- `docs/memory/` — graph memory behavior
- `docs/adr/` — immutable architectural decisions
- `docs/roadmap/` — future work only
- `docs/specs/` — active feature specifications only
- `docs/scratch/` — disposable drafts, never a source of truth
- `docs/archive/` — historical reports and superseded documents

`docs/README.md` is the index. Existing documents must be updated, merged, archived, or deleted before adding another document for the same concept.

## Consequences

- Each concept has one maintained owner.
- Historical material is separated from active guidance.
- Scratch content cannot silently become implementation authority.
- Documentation work includes an audit of links and implementation drift.
