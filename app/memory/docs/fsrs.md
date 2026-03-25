# FSRS-Based Retention Model

This document describes how episodic and semantic memories decay and are
reinforced over time using an FSRS-inspired model.

FSRS: Free Spaced Repetition Scheduler — originally used in flashcard systems
to model memory retention.

---

## Purpose

The retention model:
- Prevents memory overload
- Simulates natural forgetting
- Reinforces frequently accessed memories
- Keeps context relevant over time

---

## Core Variables

Each memory contains:

| Variable | Semantic | Episodic | Description |
|---|---|---|---|
| `importance` | decays | decays | Primary score, × exp decay |
| `stability` | access_count-derived | access_count-derived | How resistant to decay |
| `difficulty` | — | tracked | How easily the memory fades |
| `emotional_weight` | — | yes | Triggers episodic creation |
| `access_count` | yes | yes | More access → higher stability |
| `last_accessed` | yes | yes | Used for recency factor |

---

## Decay Model

**Formula:**
```
importance = importance × exp(-hours_since_last_access / stability)
```

Stability is derived from access count:
- Semantic: `stability = max(24 × (1 + access_count × 0.5), 24h)`
- Episodic: `stability = max(48 × (1 + access_count × 0.3), 48h)`

Minimum importance clamped to 0.01 (memories never fully vanish).

---

## Reinforcement

When a memory is retrieved (in `retrieval.py`):

1. `access_count` increments
2. `last_accessed` updates to now
3. `importance` bumps by +0.05 (capped at 1.0)

---

## Retrievability

Retrievability is approximated by recency factor (in retrieval scoring):

```
recency = exp(-hours_since_last_access / 24.0)
```

This means:
- 0 hours old → recency ≈ 1.0
- 24 hours old → recency ≈ 0.37
- 48 hours old → recency ≈ 0.14
- 7 days old → recency ≈ 0.04

---

## Forgetting

Memories with very low importance (approaching 0.01) become effectively
invisible in retrieval — they sort to the bottom of results due to low
importance scores. No automatic deletion; full retention is preserved.

---

## Update Triggers

Memory updates occur:
1. When memory is **retrieved** — access_count++, importance bump, recency reset
2. **On session start** — `review.run_decay()` applies decay to all memories

---

## Module Responsibilities

File: `memory/review.py`

Primary functions:
- `_hours_since(dt)` — calculate hours since a datetime
- `decay_semantic_memories(session_id)` — apply FSRS decay to semantic layer
- `decay_episodic_memories(session_id)` — apply FSRS decay to episodic layer
- `reinforce_memory(memory_id, memory_type)` — bump importance on retrieval
- `run_decay(session_id)` — run full decay cycle; call on session start
