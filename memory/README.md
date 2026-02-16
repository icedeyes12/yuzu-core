Yuzu Memory System

The Yuzu memory system is a structured, long-term memory architecture designed to support persistent, evolving relationships between the user and the AI companion.

Unlike simple conversation history or flat summaries, this system models memory as layered cognitive structures:

Episodic memory for lived interactions

Semantic memory for stable facts and preferences

Retention dynamics inspired by human memory decay

Context retrieval that prioritizes relevance over recency alone


This approach enables more stable personality, emotional continuity, and long-term behavior shaping.


---

Core Principles

The memory system follows four key principles:

1. Separation of Memory Types

Different kinds of memory are stored differently:

Memory Type	Purpose

Episodic	Stores summarized interaction segments
Semantic	Stores stable facts and preferences
Working	Short-term recent conversation context



---

2. Memory as a First-Class System

Memory is not a post-processing step.
It is a dedicated subsystem with:

Its own tables

Its own scoring and decay logic

Its own retrieval pipeline



---

3. Importance-Driven Retention

Not all memories are equal.

Each memory receives:

Importance score

Emotional weight

Stability over time


Low-importance memories naturally fade.
High-importance memories become long-term anchors.


---

4. Context is Composed, Not Dumped

Instead of feeding raw history to the model:

Relevant episodic memories are retrieved

Stable semantic facts are injected

Recent messages provide short-term continuity


This produces a structured, efficient context.


---

Architecture Overview

High-level flow:

Conversation History
        ↓
Segmentation (memory/segmenter.py)
        ↓
Episodic Memory (memory/extractor.py)
        ↓
Semantic Extraction (memory/extractor.py)
        ↓
Retention & Decay (memory/review.py)
        ↓
Context Retrieval (memory/retrieval.py)
        ↓
LLM Context Builder (app.py)


---

Module Structure

```
memory/
    __init__.py          # Package init
    models.py            # Re-exports ORM models
    extractor.py         # Semantic + episodic extraction
    segmenter.py         # Conversation segmentation
    retrieval.py         # Memory retrieval pipeline
    review.py            # FSRS-style decay & reinforcement
    migrate_history.py   # Migration from old history
    README.md            # This file
    TODO.md              # Implementation tracker
    docs/                # Design documentation
```

---

Database Tables

### semantic_memories
Stores stable facts as (entity, relation, target) triples with confidence scoring.

### episodic_memories
Stores summarized interaction events with emotional weight and importance.

### conversation_segments
Stores chunked conversation groups with summaries.

All tables are created automatically on startup. Existing `messages` table is unchanged.


---

Memory Layers

Episodic Memory

Stores summarized interaction segments:

Emotional moments

Relationship shifts

Important technical events

Personal milestones


See:

episodic_memory.md



---

Semantic Memory

Stores stable facts derived from episodic memory:

Example:

{ entity: "User", relation: "Prefers", target: "concise answers" }
{ entity: "User", relation: "Uses", target: "Termux on phone" }

See:

semantic_memory.md



---

Segmentation

Splits long conversations into meaningful episodes before storage.

Prevents:

Oversized summaries

Irrelevant memory blending

Context pollution


See:

segmentation.md



---

Retrieval Pipeline

Selects which memories enter the model context.

Combines:

Recent conversation

Relevant episodic memories

Stable semantic facts


See:

retrieval.md



---

Retention Model (FSRS-Inspired)

Applies stability and decay dynamics:

Frequently reinforced memories become stable

Unused memories fade over time


Inspired by spaced repetition algorithms.

See:

fsrs.md



---

Implementation Status

All phases are complete:

- ✅ Phase 1: Database schema
- ✅ Phase 2: Memory extraction
- ✅ Phase 3: Conversation segmentation
- ✅ Phase 4: Retrieval pipeline
- ✅ Phase 5: Context builder integration
- ✅ Phase 6: Review & decay system
- ✅ Phase 7: Migration & fallback

See TODO.md for detailed task tracking.


---

Design Goals

This system aims to:

Preserve emotional continuity across sessions

Avoid context bloat from raw history

Support long-term personality evolution

Provide stable user preferences

Enable scalable memory beyond tens of thousands of messages



---

Contribution Notes

Before contributing:

1. Read the architecture overview above.

2. Review the memory subsystem docs:

episodic memory

semantic memory

segmentation

retrieval

retention model


3. Follow the implementation phases in TODO.md.


This ensures new changes remain consistent with the intended cognitive architecture.