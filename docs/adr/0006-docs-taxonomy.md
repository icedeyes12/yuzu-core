# ADR 0001: Documentation taxonomy (roadmap / adr / specs / scratch / archive)

Status: Accepted
Date: 2026-08-06

## Context

Ad-hoc plan files were scattering across whatever working directory the agent
happened to be in (`~/`, repo root, random paths). The rise of remote agents
(Hermes, Codex, ChatGPT drafts) made this worse: multiple authors, no SSOT.

## Decision

`docs/` is the single source of truth. Standard subfolders:

- `docs/roadmap/` — living multi-version roadmaps
- `docs/adr/` — Architecture Decision Records (decisions that are settled)
- `docs/specs/` — features actively being built
- `docs/scratch/` — raw drafts, free to mutate; not facts
- `docs/archive/` — retired roadmaps / superseded decisions

Existing top-level .md files in `docs/` are left as-is (legacy); new content
must use the subfolders above. No new plan files in the repo root or in the
agent's `pwd`.

## Consequences

- Agents (Hermes, Codex, humans) have exactly one place to look for plans.
- `docs/scratch/` absorbs early-stage ideas without polluting the repo root.
- Archiving is explicit: move a file, don't delete it.
