docs/tasks/stabilize_tool_driven_system.md

Task: Stabilize Tool-Driven System + SearXNG Migration


---

Goal

Stabilize the current tool-driven architecture and fix the remaining core issues:

1. Memory search cannot retrieve temporal conversational context.


2. Web search results are shallow and unreliable.


3. Visual context is not persistent across turns.


4. Image links produce less accurate vision results.


5. Tool usage flow is not fully natural or seamless.



Additionally:

Replace DuckDuckGo scraping with SearXNG-based search.

Improve web search depth and result quality.

Stabilize multimodal conversational context.



---

High-Level Principles

The system must behave like a natural companion, not a task bot.

Tool usage philosophy

Tools are invisible.

Tools serve conversation, not the other way around.

Image messages are still messages, not analysis requests.



---

Scope

Modify:

tools/memory_search.py

tools/web_search.py

tools/image_analyze.py

app.py (only where necessary)

system message (tool usage section only)


Allowed:

Database schema changes (if necessary for performance or indexing).


Do NOT modify:

structured memory tables

personality logic

chat message storage format

memory architecture core logic



---

Issue Set

Issue 1 — Temporal memory queries not working

Symptom

User asks:

> “Apa momen paling memorable di bulan Desember?”



System only checks:

semantic memory

episodic memory


It does NOT:

scan raw messages in the requested time window

analyze conversation context


Root cause

Current memory_search:

uses structured memory only

raw search is keyword-based

not time-window based

not analysis-driven



---

Issue 2 — Web search results too shallow

Symptom

Queries like:

> “harga kondom”



Result:

generic explanation

no price range

no concrete numbers


Root causes

Current implementation:

uses DuckDuckGo HTML scrape

only reads snippet

shallow extraction

no content parsing

no numeric extraction


Additional problem:

search results may be outdated

no recency awareness



---

Issue 3 — Visual context not persistent

Symptom

Flow:

User sends image
Assistant responds correctly

Next message:

> “Bedanya dari yang tadi?”



Assistant:

compares using text description

not actual visual data


Root cause

image path stored in history

not re-converted into visual context

no persistent visual memory window



---

Issue 4 — Direct image links less accurate

Symptom

Same image:

Markdown image → accurate

Upload → accurate

Direct URL → inaccurate


Root cause

Different pipelines:

Markdown → cached → base64

Upload → cached → base64

Direct URL → inconsistent processing



---

Phase 1 — Replace DuckDuckGo with SearXNG

Rationale

DuckDuckGo HTML scraping:

unstable

snippet-only

low information density

no structured results


SearXNG:

JSON API

multi-engine meta search

structured output

better relevance



---

Tool change

File:

tools/web_search.py

Replace:

DuckDuckGo HTML scraping logic.

With:

SearXNG JSON endpoint.

Example:

GET https://searx.be/search?q=QUERY&format=json

Parse:

Top results:

title
content
url

Return:

{
  "results": [
    { "title": "...", "content": "...", "url": "..." }
  ],
  "pages": [
    {
      "url": "...",
      "text": "extracted page text..."
    }
  ]
}


---

Deep fetch step

After retrieving top results:

1. Take top 3 URLs.


2. Fetch HTML.


3. Extract visible text.


4. Trim to ~3000–5000 chars.


5. Return as pages.




---

Best-practice requirements

The agent must:

Handle network errors gracefully.

Skip failed pages.

Never crash tool loop.


Optional improvements:

recency bias

number extraction

price extraction

structured result hints


Agent may implement any reasonable improvements.


---

Phase 2 — Temporal memory analysis

File:

tools/memory_search.py


---

New behavior

For queries containing:

month names

“kemarin”

“minggu lalu”

“bulan desember”

“last week”

“in december”

etc.


System must:

1. Detect time window.


2. Query messages table directly.


3. Fetch messages in that range.


4. Return them to the model for analysis.




---

Required retrieval logic

For temporal queries:

detect month or relative time

compute time window

query messages table:


Example:

SELECT content, timestamp
FROM messages
WHERE session_id = ?
AND timestamp BETWEEN start AND end
ORDER BY timestamp ASC
LIMIT 200

Return:

raw_messages: [
  {timestamp, content}
]


---

Output format

{
  "structured": { ... },
  "raw_messages": [ ... ],
  "time_window": {
    "start": "...",
    "end": "..."
  }
}


---

Important

Tool must:

return raw messages

NOT summarize

NOT interpret


The model will perform the analysis.


---

Phase 3 — Persistent visual context window

Goal:

Treat images like conversational context, not tasks.


---

New behavior

When:

assistant processes an image

image is analyzed into base64


Store:

last_visual_context = base64 image

For next N turns (N = 2–3):

If:

user references image

or comparison intent detected


Then:

automatically include visual context again

without requiring explicit tool call



---

Implementation location

In:

app.py

Add:

small visual context buffer

per-session state


Do NOT store base64 in database.

Only:

short-term runtime memory.



---

Phase 4 — Unify image processing pipeline

File:

tools/image_analyze.py


---

Required behavior

All inputs:

direct URL

markdown image

uploaded file

local path


Must follow identical pipeline:

source → download if needed
       → cache
       → load
       → encode base64
       → return

No special-case branches.


---

Phase 5 — System message refinement

Modify only the tool-usage section.


---

Add rules

Memory tool rule

If user asks about:

past events

memories

specific dates

comparisons over time


Always use:

memory_search

Even if structured memory exists.


---

Image behavior rule

If image is received:

Treat it as:

conversational visual context


Not:

an analysis task


Only analyze when:

user explicitly asks about the image.



---

Tool flow rule

For multi-step tool use:

Model must:

1. Call tool.


2. Receive result.


3. Continue reasoning.


4. Produce final natural answer.



Never stop after tool output.


---

Phase 6 — Tool loop stability

In app.py:

Ensure:

1. Tool results are validated.


2. If tool returns invalid/empty result:

log error

retry once



3. If still invalid:

fallback to normal model response




Never allow:

empty assistant message


---

Testing Scenarios

Memory

User:

> “Momen paling memorable di bulan Desember?”



Expected:

memory_search triggered

raw December messages returned

model analyzes and answers



---

Web search

User:

> “Harga kondom”



Expected:

web_search called

pages fetched

price range extracted

concrete answer



---

Visual continuity

Flow:

1. User sends bird photo.


2. Assistant responds.


3. User: “Yang tadi beda apa?”



Expected:

visual context reused

correct comparison



---

Direct URL image

User sends:

http://example.com/image.jpg

Expected:

same accuracy as upload/markdown



---

Constraints

Do NOT:

break tool architecture

change personality system

modify memory schema logic

add paid APIs

introduce heavy dependencies



---

Expected Result

After this task:

System becomes:

stable in normal chat

stable in tool loops

capable of deep memory recall

capable of contextual image conversations

using higher-quality web search


All:

seamless

multi-step

model-driven

companion-style