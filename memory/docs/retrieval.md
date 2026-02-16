# Memory Retrieval

This document describes how memories are selected and injected into
the LLM context.

Retrieval combines:

1. Semantic memory (facts)
2. Episodic memory (events)
3. Recent raw messages

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
4. Recent messages

---

## Semantic Retrieval

Selection rules:

- Sort by confidence (descending)
- Secondary sort: access_count
- Secondary sort: recency

Typical limits:

- 10–20 semantic facts

Example:

User prefers concise answers. User works mostly at night. User uses Python for backend work.

---

## Episodic Retrieval

Episodic memories represent:

- Important conversations
- Emotional shifts
- Decisions
- Shared events

Selection scoring:

score = importance_score * 0.5

retrievability * 0.3

recency_weight * 0.2


Typical limits:

- Top 5–10 episodes

---

## Recency Weight

Recency weight is derived from:

time_since_last_access

Newer or recently accessed memories are preferred.

---

## Recent Message Window

Always include:

- Last 10–20 raw messages

Purpose:

- Preserve conversational continuity
- Capture immediate context

---

## Final Context Layout

Example structure:

System message

[Semantic memory]

User prefers concise answers.

User works at night.


[Episodic memory]

Last week: user completed major refactor.

Yesterday: user expressed frustration with network issues.


[Recent messages] User: ... Assistant: ... User: ...

---

## Module Responsibilities

File: `memory/retrieval.py`

Responsibilities:

1. Retrieve top semantic facts
2. Retrieve top episodic memories
3. Assemble ranked memory lists

Primary functions:

- get_semantic_memories(session_id, limit)
- get_episodic_memories(session_id, limit)
- rank_episodic_memories(episodes)