/memory/docs/segmentation.md

# Episodic Segmentation

Segmentation converts raw message streams into structured
episodic memory units.

An episode represents a coherent interaction segment.

---

## Purpose

Segmentation exists to:

- Reduce raw message volume
- Create structured memory units
- Enable importance scoring
- Support long-term memory formation

---

## What Is an Episode

An episode is:

A bounded segment of conversation that represents:

- A task
- A discussion
- An emotional exchange
- A decision
- A meaningful interaction

---

## Initial Strategy (Phase 1)

Use fixed window segmentation.

Rule:

Every 20–40 messages → create one episode

Steps:

1. Select message window
2. Summarize messages
3. Score importance and surprise
4. Store as episodic memory

---

## Future Strategies (Phase 2+)

Dynamic boundary detection:

Episode breaks triggered by:

- Topic shift
- Emotional spike
- Tool usage
- Long time gaps
- Explicit decisions

---

## Episode Summary

Each episode contains:

- start_message_id
- end_message_id
- summary text
- importance score
- surprise score

---

## Importance Signals

Examples:

High importance:

- Major decisions
- Emotional conflict
- New preferences
- Relationship shifts

Low importance:

- Routine chatter
- Repeated questions
- Small talk

---

## Module Responsibilities

File: `memory/segmentation.py`

Responsibilities:

1. Select message windows
2. Detect episode boundaries
3. Create episodic memory entries

Primary functions:

- segment_messages(session_id)
- create_episode(message_range)