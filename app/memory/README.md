# Yuzu Memory System

Long-term memory architecture for persistent, evolving AI companion relationships.

The runtime memory owner is the PostgreSQL graph: `episodes`, `memory_nodes`, `memory_edges`, and `memory_evidence`.

## Ownership

| Concept | Owner |
|---|---|
| Raw conversation | `messages` |
| Summarized interaction | `episodes` |
| Inferred persistent knowledge | `memory_nodes` |
| Relationships | `memory_edges` |
| Provenance | `memory_evidence` |
| Explicit user facts | `global_knowledge_entries` |
| Prompt presentation | `app/prompts.py` |

## Runtime Flow

```
messages -> batch gate -> one structured extraction call
         -> episodes + memory_nodes + memory_edges + memory_evidence
         -> graph retrieval (pgvector/text + bounded expansion)
         -> PromptBuilder
```

Extraction runs asynchronously for eligible batches. Retrieved graph nodes carry confidence, importance, validity, and provenance.

## Graph Storage

- `episodes`: summarized interactions and source message range.
- `memory_nodes`: inferred claims with optional 4096-dimensional embeddings.
- `memory_edges`: typed, confidence-scored relationships.
- `memory_evidence`: links nodes or edges to source messages and episodes.
- Every table is tenant-scoped by `user_id`.
- Retrieval uses exact pgvector search when embeddings are available, with trigram fallback and bounded one-hop expansion.

## Explainability

Every retrieved node can be traced through `memory_evidence` to the message IDs and episode that introduced it. Node confidence, importance, validity, and status remain explicit graph columns.

## Implementation Status

- ✅ PostgreSQL graph schema with tenant isolation
- ✅ Single structured extraction pass per eligible batch
- ✅ Graph retrieval with vector/text fallback and bounded expansion
- ✅ Evidence-backed provenance
- ✅ Global Knowledge remains separate and deterministic

## Categories

Memory nodes may use: Identity, Preference, Interest, Personality, Relationship, Experience, Goal, or Guideline.
