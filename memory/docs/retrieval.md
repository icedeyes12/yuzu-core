# Memory Retrieval

This document describes how memories are selected and injected into
the LLM context.

Retrieval combines:
1. Semantic memory (facts)
2. Episodic memory (events)
3. Conversation segments
4. Recent raw messages

---

## Retrieval Goals

The retrieval system must:
- Keep context small
- Keep context relevant
- Preserve long-term consistency
- Avoid redundant information

---

## Retrieval Layers

Context is assembled in this order:
1. System message
2. Semantic memory
3. Episodic memory
4. Conversation segments
5. Recent messages

---

## Semantic Retrieval

**Scoring formula:**
```
score = cosine_sim × 0.6 + importance × 0.2 + confidence × 0.2
```

When no query embedding is available, falls back to: `importance × confidence`

**Selection rules:**
1. Sort by score (descending)
2. Limit: top 10–15 results

**Example output:**
```
Known preferences:
- User Prefers concise answers
- User Uses Python for backend
```

---

## Episodic Retrieval

**Scoring formula:**
```
score = cosine_sim × 0.5 + importance × 0.25 + recency × 0.25
```

Recency factor uses exponential decay with 24h half-life:
```
recency = exp(-hours_since_last_access / 24.0)
```

When no query embedding is available, falls back to:
```
score = importance + emotional_weight × 0.5 + recency
```

**Selection rules:**
1. Sort by score (descending)
2. Limit: top 5 results

---

## Segment Retrieval

**Scoring formula:**
```
score = cosine_sim × 0.5 + importance × 0.5
```

**Selection rules:**
1. Sort by score (descending)
2. Limit: top 5 results

---

## Recent Message Window

Always include:
- Last 10–20 raw messages

Purpose:
- Preserve conversational continuity
- Capture immediate context

---

## Final Context Layout

```
System message

[Semantic memory]
Known preferences:
- User Prefers concise answers
- User Works at night

[Episodic memory]
Recent important events:
- User completed a major refactor last week
- User expressed frustration with network issues yesterday

[Segments]
Relevant past context:
- User asked about deployment on 2026-03-20

[Recent messages]
User: ...
Assistant: ...
User: ...
```

---

## Module Responsibilities

File: `memory/retrieval.py`

Responsibilities:
1. Retrieve top semantic facts by hybrid score
2. Retrieve top episodic memories by hybrid score
3. Retrieve top conversation segments
4. Assemble and format memory bundle for context injection

Primary functions:
- `retrieve_semantic_memories(session_id, query, limit)`
- `retrieve_episodic_memories(session_id, query, limit)`
- `retrieve_segments(session_id, query, limit)`
- `retrieve_memory(session_id, query)` — returns dict with semantic, episodic, segments
- `format_memory(memory_bundle)` — formats for system message injection

Recency helper:
- `_recency_factor(last_accessed)` — returns 0.0–1.0, half-life 24h
