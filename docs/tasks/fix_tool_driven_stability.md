docs/tasks/fix_tool_driven_stability.md

# Task: Tool-Driven Stability & Retrieval Quality Fix

## Goal

Stabilize and refine the tool-driven architecture by fixing:

1. Memory search realism
2. Web search depth
3. Image analysis consistency
4. Tool usage behavior

Primary objective:

Make the system feel **consistent, reliable, and context-aware** without breaking existing architecture.

---

## Scope

Modify:

- tools/memory_search.py
- tools/web_search.py
- tools/image_analyze.py
- app.py (only tool loop or system message parts)

Database schema:
- May be modified if necessary.

System message:
- May be refined for better tool usage.

Do NOT:

- Break structured memory system
- Change message storage format
- Rewrite personality logic
- Add paid APIs
- Introduce heavy dependencies

---

## Phase 1 — Memory Search: Hybrid Retrieval

### Goal

Make `memory_search` capable of:

- Structured memory retrieval
- Raw message retrieval
- Temporal recall

### Required behavior

Input:

{ "query": "string" }

### Step 1 — Structured memory

Call existing:

retrieve_memory(session_id)

Collect:

- semantic
- episodic
- segments

---

### Step 2 — Raw message search

Always perform raw search as fallback or supplement.

Query:

- Last 2000 messages max
- Filter by session_id
- Keyword match from query
- Optional time window if temporal cues detected

Temporal cues:

- kemarin
- minggu lalu
- bulan lalu
- waktu itu
- terakhir
- last time
- last week
- yesterday
- December
- January, etc.

Return:

Top 20 relevant messages.

---

### Output format

{ "structured": { "semantic": [...], "episodic": [...], "segments": [...] }, "raw_messages": [ { "timestamp": "...", "content": "..." } ] }

---

## Phase 2 — Web Search: Deep Result Extraction

### Goal

Upgrade web_search from:

snippet summarizer

to:

result → page fetch → text extract → structured data

---

### New pipeline

1. DuckDuckGo search
2. Get top 3 results
3. For each result:
   - Fetch page HTML
   - Extract visible text
   - Truncate to safe size
4. Aggregate text
5. Return to model

---

### Output format

{ "results": [ { "title": "...", "url": "...", "snippet": "...", "page_text": "..." } ] }

Constraints:

- Max 3 pages fetched
- Max 3000 characters per page
- Fail silently if page fails

---

## Phase 3 — Image Analyze: Unified Pipeline

### Goal

All image inputs must follow the same pipeline.

---

### Required behavior

For any input:

- upload
- markdown image
- direct URL

Flow:

resolve image → download or load → cache → encode base64 → return base64

Direct URLs must NOT:

- be sent to model as raw URLs
- bypass cache or base64

---

### Output

{ "image_base64": "...", "mime": "image/png" }

---

## Phase 4 — Tool Loop Safety (app.py)

### Goal

Ensure tool loop always ends with a valid assistant response.

Rules:

1. Max tool loops: 3
2. If tool returns empty or invalid result:
   - Log error
   - Remove tool call
   - Ask model to answer without tool
3. If final assistant content is empty:
   - Retry once without tools

No empty responses allowed.

---

## Phase 5 — System Message Tool Guidance

### Goal

Improve tool usage reliability without changing persona.

---

### Add or refine tool awareness section

Add:

Tool usage principles:

- Use memory_search for past events, personal history, or time-based questions.
- Use web_search for external or time-sensitive data.
- Prefer memory_search over web_search when the question is about personal conversations.
- Always analyze images through image_analyze before answering visual questions.
- Do not guess visual details without image analysis.

Execution behavior:

- If a tool is clearly required, call it immediately.
- Do not answer from assumptions when a tool can provide concrete data.

Do not change:

- Emotional tone
- Persona logic
- Closeness system

---

## Phase 6 — Testing

### Memory tests

1.
User:

momen paling memorable di bulan Desember

Expected:
- memory_search called
- raw message retrieval used
- correct answer

---

### Web search tests

1.
User:

harga kondom durex berapa

Expected:

- web_search used
- page_text extracted
- answer includes concrete numbers

---

### Image consistency tests

Use same image:

1. Upload
2. Markdown
3. Direct URL

Expected:

- Same visual description
- Same color/object result

---

### Tool stability test

1.
User:

hai

Expected:

- No tool call
- Normal response
- No empty message

---

## Expected Result

System becomes:

- Stable in normal chat
- Realistic memory recall
- Useful web search results
- Consistent image analysis
- Proper tool decision behavior