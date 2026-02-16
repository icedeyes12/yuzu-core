# FSRS-Based Retention Model

This document describes how episodic memories decay and are reinforced
over time using an FSRS-inspired model.

FSRS:
Free Spaced Repetition Scheduler

Originally used in flashcard systems to model memory retention.

---

## Purpose

The retention model:

- Prevents memory overload
- Simulates natural forgetting
- Reinforces important memories
- Keeps context relevant over time

---

## Core Variables

Each episodic memory contains:

- stability
- difficulty
- retrievability

---

## Stability

Represents how long the memory can survive without reinforcement.

High stability:
- Important events
- Frequently referenced memories

Low stability:
- Minor or forgotten events

---

## Difficulty

Represents how easily the memory fades.

High difficulty:
- Rarely referenced memories
- Weak emotional signals

Low difficulty:
- Strong emotional or repeated memories

---

## Retrievability

Represents the probability the memory can be recalled now.

Range:

0.0 – 1.0

Decay model:

Retrievability decreases over time.

Example:

R = exp(-time / stability)

---

## Reinforcement

When a memory is retrieved:

- stability increases
- difficulty may decrease
- retrievability resets higher

---

## Forgetting

Memories with:

- very low retrievability
- very low importance

may be:

- archived
- compressed
- or removed

---

## Update Triggers

Memory updates occur:

1. When memory is retrieved
2. Periodic background scheduler
3. When new related episodes appear

---

## Module Responsibilities

File: `memory/episodic.py`

Responsibilities:

1. Update retrievability over time
2. Reinforce memories when used
3. Apply decay model

Primary functions:

- update_retrievability(memory)
- reinforce_memory(memory)
- decay_memories(session_id)
