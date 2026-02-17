docs/issues/post_tool_driven_additional_issues.md

# Post Tool-Driven Architecture – Additional Issues

This document tracks issues discovered after initial stabilization of the tool-driven architecture.

Scope: post-stability functional quality and retrieval correctness.

---

## 1. Memory Search Ignores Raw Message History (Critical)

Severity: Critical  
Area: memory_search tool  
Status: Reproducible

### Symptoms

User asks about older events:

- “momen paling memorable di bulan Desember”
- “menu minggu kemarin”
- “waktu kita bahas X dulu”

System:

- Only checks structured memory
- Returns incomplete or unrelated answers
- Ignores actual messages in the `messages` table

### Observations

- Structured memory currently contains only recent months.
- Older events exist in raw message history.
- Tool does not query `messages` table meaningfully.

### Root Cause

`memory_search`:

- Relies primarily on structured memory retrieval.
- Raw message search either:
  - Not implemented properly, or
  - Not triggered in real scenarios.

### Impact

- Assistant appears to “forget” real events.
- Memory system feels artificial and unreliable.
- Breaks continuity for long-term users.

---

## 2. Web Search Results Too Shallow (High)

Severity: High  
Area: web_search tool  
Status: Reproducible

### Symptoms

Example:

User:

cari harga kondom

Result:

- Generic description
- No concrete numbers
- No price ranges
- No actionable information

### Observations

Current flow:

query → top snippets → model summarizes

Tool:

- Only returns DuckDuckGo snippets.
- Does not open result pages.
- Does not extract structured information.

### Impact

- Answers feel vague and unhelpful.
- Tool is not useful for practical queries.
- Model cannot extract real data.

---

## 3. Direct Image URL Analysis Less Accurate (High)

Severity: High  
Area: image_analyze tool  
Status: Reproducible

### Symptoms

Input comparison:

| Input type     | Accuracy |
|----------------|----------|
| Upload file    | High     |
| Markdown image | High     |
| Direct URL     | Low      |

### Observations

- Upload and markdown paths go through:

download → cache → base64 → model

- Direct URL likely bypasses base64 conversion.

### Root Cause

Direct URLs:

- Not consistently routed through the cache + base64 pipeline.
- Sent as raw URLs to the model.

### Impact

- Vision accuracy inconsistent.
- Same image yields different answers depending on input format.
- Breaks user trust.

---

## 4. Tool Usage Behavior Not Fully Aligned (Medium)

Severity: Medium  
Area: system message / tool decision logic  
Status: Observed

### Symptoms

Model sometimes:

- Does not call memory_search when it should.
- Falls back to web_search unnecessarily.
- Does not fully utilize tools.

### Root Cause

System message:

- Tool awareness section too generic.
- Lacks concrete execution guidance.
- Not aligned with actual tool behavior.

### Impact

- Tools underutilized.
- Inconsistent responses.
- Suboptimal reasoning flow.

---

## Priority Summary

| Priority | Issue |
|----------|------|
| Critical | Memory search ignores raw messages |
| High     | Web search too shallow |
| High     | Direct URL image analysis inaccurate |
| Medium   | Tool usage behavior not aligned |