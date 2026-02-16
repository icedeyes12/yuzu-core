# Semantic Memory

Semantic memory stores long-term, generalized knowledge about the user,
the assistant, and their relationship.

Unlike episodic memory, which stores specific events, semantic memory
represents stable facts extracted from repeated interactions.

Example:

{ entity: "User", relation: "Prefers", target: "concise answers" }
{ entity: "User", relation: "Uses", target: "dark mode" }

---

## Purpose

Semantic memory exists to:

1. Reduce prompt size by replacing raw history with facts.
2. Preserve stable user preferences.
3. Represent relationship traits.
4. Provide consistent long-term behavior.

---

## Data Model

Table: `semantic_memory`

Columns:

- id (INTEGER, PK)

Triple:
- entity (TEXT)
- relation (TEXT)
- target (TEXT)

Confidence:
- confidence (REAL)

Source tracking:
- source_episodic_ids (TEXT, JSON array)

Usage:
- access_count (INTEGER, default 0)
- last_accessed_at (TEXT)

Metadata:
- created_at (TEXT)

Indexes:
- entity
- relation
- confidence

---

## Semantic Triples

Each semantic memory is stored as a triple:

(entity, relation, target)

Example categories:

### User preferences
User — Prefers — concise answers  
User — Prefers — dark theme  
User — Uses — Python  

### Relationship traits
User — Treats — assistant as partner  
Assistant — Role — companion  

### Behavioral patterns
User — Often works — at night  
User — Asks — technical questions  

---

## Confidence Model

Each fact has a confidence score:

Range:

0.0 – 1.0

Interpretation:

| Confidence | Meaning |
|-----------|--------|
| 0.0–0.3 | Weak signal |
| 0.3–0.6 | Probable pattern |
| 0.6–0.85 | Strong preference |
| 0.85–1.0 | Stable long-term fact |

---

## Fact Creation

Facts are extracted from:

- High-importance episodic memories
- Repeated patterns across multiple episodes

Conditions for fact creation:

1. Episode importance_score above threshold
2. Clear preference or behavioral pattern
3. Not a one-off or emotional spike

---

## Fact Merging

If a new fact matches an existing triple:

Instead of creating a new row:

- Increase confidence
- Update source_episodic_ids
- Update last_accessed_at

---

## Decay and Stability

Semantic memory is not permanent.

Confidence may:

Decrease when:
- Not referenced for long periods
- Contradicted by new facts

Increase when:
- Reinforced by new episodes
- Frequently retrieved

---

## Retrieval Role

Semantic memory is always retrieved before episodic memory.

Typical usage:

- Top 10–20 highest-confidence facts
- Sorted by:
  - confidence
  - access_count
  - recency

---

## Module Responsibilities

File: `memory/semantic.py`

Responsibilities:

1. Extract facts from episodic memory
2. Merge or update existing facts
3. Manage confidence
4. Provide semantic retrieval API

Primary functions:

- extract_semantic_facts(episode)
- merge_or_insert_fact(triple)
- get_top_semantic_memories(limit)