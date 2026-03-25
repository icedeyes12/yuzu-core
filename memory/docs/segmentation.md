# Episodic Segmentation

Segmentation converts raw message streams into structured memory units
(`conversation_segments` table), which are then summarized into episodic
memories.

---

## Purpose

Segmentation exists to:
- Reduce raw message volume into digestible units
- Create structured memory entries with boundaries
- Enable importance scoring per segment
- Support long-term memory formation (episodic → semantic)

---

## What Is a Segment

A segment is a bounded group of consecutive messages representing:
- A task or workflow
- A discussion topic
- An emotional exchange
- A decision
- A meaningful interaction

Segments are stored in the `conversation_segments` table and later
processed into episodic memories.

---

## Segmentation Rules

Two triggers for creating a new segment boundary:

### 1. Time Gap
If the gap between two consecutive messages exceeds **15 minutes**,
a boundary is inserted.

### 2. Message Count
If a segment exceeds **20 messages**, it is closed and a new one starts.

### 3. Minimum Size
Segments with fewer than **5 messages** are discarded (not stored)
unless they are the only messages in the session.

---

## Segmentation Algorithm

```
1. Fetch all unsegmented messages (id > last segmented end_message_id)
2. Iterate messages, building current_group
   - If time gap ≥ 15 min → close segment, start new group
   - If group size ≥ 20 → close segment, start new group
   - Otherwise → add message to current group
3. If final group has ≥ 5 messages → store as segment
4. Return count of segments created
```

---

## From Segments to Episodic Memory

Segmentation is the **first pass**. After segments are created:

1. `extractor.should_create_episodic()` evaluates each segment's messages
   - Emotional weight ≥ 0.3 → create episodic
   - Message count ≥ 10 → create episodic
   - Affection delta ≥ 20 → create episodic

2. `extractor.generate_episodic_summary()` (LLM-powered) produces 1-3 sentence summary

3. `extractor.create_episodic_memory()` stores the episodic with embedding

---

## Segment vs. Episodic

| | Segment | Episodic Memory |
|---|---|---|
| Table | `conversation_segments` | `episodic_memory` |
| Granularity | Message window | LLM summary of a window |
| Trigger | Time/size rules | Emotional weight / message count |
| Summary | Raw text truncation | LLM-generated |
| Use case | Raw context retrieval | Long-term event memory |

---

## Module Responsibilities

File: `memory/segmenter.py`

Primary functions:
- `_get_unsegmented_messages(session_id)` — fetch messages not yet in any segment
- `_detect_boundaries(messages)` — apply time-gap and size rules
- `_create_segment(session_id, group)` — store ConversationSegment record
- `segment_session(session_id)` — main entry, returns segments created

Key constants:
- `MAX_MESSAGES_PER_SEGMENT = 20`
- `TIME_GAP_MINUTES = 15`
