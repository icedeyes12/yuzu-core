Tool-Driven Architecture + Contextual Memory + System Message Adaptation + UI Adaptation 

Goal

Refactor the assistant into a tool-driven architecture where:

The model decides when to use tools.

No manual vision toggle or special switches.

All tools are callable through a unified tool interface.

Memory retrieval becomes contextual and model-driven.


The system must support:

Web search

Weather

Contextual memory retrieval

Image analysis

Image generation


Core interaction flow

User → Model
Model decides tool (if needed)
→ tool call
→ tool result
→ model final answer

Or:

User → Model
→ direct answer (no tool needed)


---

Scope

Modify

app.py

providers.py

system message generation

config UI (weather location only)


Create

tools/
    __init__.py
    registry.py
    web_search.py
    weather.py
    memory_search.py
    image_generate.py
    image_analyze.py

Do NOT modify

Database schema

Markdown renderer

Memory architecture (tables, scoring, FSRS, etc.)

Existing chat message flow



---

Phase 1 — Tool System Refactor

1. Create tools/ directory

Move logic from tools.py into modular files.

Final structure:

tools/
    registry.py
    web_search.py
    weather.py
    memory_search.py
    image_generate.py
    image_analyze.py

After migration:

Remove old tools.py

Fix all imports to use tools.registry



---

2. Tool registry

Create:

tools/registry.py

Responsibilities:

Register tools

Provide tool schemas

Dispatch tool calls


Required functions:

def get_tool_schemas():
    ...

def execute_tool(tool_name, arguments, session_id=None):
    ...

Requirements:

Schemas must follow OpenRouter tool format

Centralize all tool definitions here

Avoid circular imports



---

Phase 2 — Implement Tools


---

Tool 1: web_search (DuckDuckGo)

File:

tools/web_search.py

Implementation:

Use DuckDuckGo HTML endpoint:

https://duckduckgo.com/html/?q=QUERY

Extract:

Title

Snippet

URL


Return top 3–5 results.

Schema:

{
  "name": "web_search",
  "input": {
    "query": "string"
  }
}

Output:

{
  "results": [
    { "title": "...", "snippet": "...", "url": "..." }
  ]
}

No API key.


---

Tool 2: weather (Open-Meteo)

File:

tools/weather.py

API:

https://api.open-meteo.com/

Input:

{
  "lat": float,
  "lon": float
}

Behavior:

If:

lat == 0 and lon == 0

Return:

{ "error": "location_not_set" }

Do NOT call API in this case.

Output:

{
  "temperature": float,
  "weather": string,
  "wind_speed": float
}


---

Tool 3: memory_search (Contextual Retrieval)

File:

tools/memory_search.py

This tool must support:

1. Structured memory retrieval


2. Contextual message search


3. Temporal memory lookup




---

Input schema

{
  "query": "string"
}


---

Retrieval pipeline

Step 1 — Structured memory

Call existing:

retrieve_memory(session_id, query)

Return:

semantic memories

episodic memories

segments



---

Step 2 — Contextual raw message search

Run only if:

Structured memory insufficient, OR

Query contains temporal/contextual cues


Examples:

kemarin

minggu lalu

waktu itu

terakhir

pas aku

last time

yesterday

last week


Then:

Search raw messages:

filter by session_id

limit: last 1000 messages

keyword match

optional time window


Return top 20 relevant messages.


---

Output format

{
  "structured": {
    "semantic": [...],
    "episodic": [...],
    "segments": [...]
  },
  "raw_messages": [
    {
      "timestamp": "...",
      "content": "..."
    }
  ]
}


---

Invocation rule

memory_search must be used only when:

User refers to past events

Information not in last 25 messages

Temporal or contextual cues present


The tool must NOT run automatically on every message.


---

Tool 4: image_generate

File:

tools/image_generate.py

Move logic from:

tools.generate_image()

No behavior change.


---

Tool 5: image_analyze

File:

tools/image_analyze.py

Responsibilities:

1. Detect image reference:

markdown image

local path

URL



2. Resolve to base64:

use cache if exists

download if remote



3. Return:



{
  "image_base64": "...",
  "mime": "image/png"
}

Do not modify caching logic.


---

Phase 3 — Tool Schemas in Provider

Modify:

providers.py

When calling OpenRouter:

tools = get_tool_schemas()

Pass tools to the API call.


---

Phase 4 — Tool Execution Loop

Modify response pipeline in:

app.py

New response flow

Pseudo-logic:

response = model.generate(messages, tools)

loop_count = 0

while response contains tool call and loop_count < 3:
    result = execute_tool(tool_name, args)
    append tool result to messages
    response = model.generate(messages, tools)
    loop_count += 1

return final response


---

Tool loop rules

Maximum tool loops per user message: 3

If same tool repeats with similar arguments:

stop loop

return best answer


If tool fails:

log error

return tool error as tool result

let model decide next step




---

Phase 5 — Remove Vision Toggle

Remove:

Vision mode switch (frontend + backend)

All manual vision logic


Vision must now be:

tool-driven via image_analyze


---

Phase 6 — System Message Adaptation

Goal

Adapt system message to:

Support tool-driven architecture

Teach tool usage

Preserve Yuzuki’s personality


Critical integration rule

Do NOT rewrite existing system message.

Do NOT remove or reorder sections.

Only append tool-awareness section near the end.

Preserve affection logic and persona behavior.



---

Tool awareness section to append

Tool awareness:

You have access to external tools.
Use them only when needed.

General rule:
- If you can answer naturally, answer directly.
- If you need outside data, call a tool.

Available tools:

1. web_search
   Use when:
   - Current events
   - Currency, prices, weather, news
   - Anything time-sensitive

2. memory_search
   Use when:
   - The user asks about past events
   - Personal history
   - Things not in recent messages
   - Time-based recollection

3. image_analyze
   Use when:
   - The user references an image
   - Visual details are required

4. weather
   Use when:
   - The user asks about weather

5. image_generate
   Use only when image generation protocol is activated.

Tool usage rules:

- Do not mention tools in conversation.
- Do not explain tool mechanics.
- Call tools silently when needed.
- After receiving tool results, respond naturally.


---

Phase 7 — Config UI Adjustment

In config page:

Add:

Latitude

Longitude


Default:

0.0
0.0

If not set:

weather tool returns location_not_set

no frontend errors



---

Phase 8 — Testing

Direct answer

User:

What is 2+2?

Expected:

No tool call

Direct answer



---

Web search

User:

USD to JPY rate

Expected:

web_search used

answer based on results



---

Weather

User:

How's the weather?

Case A:

location set

weather tool used


Case B:

location = 0,0

model asks for location



---

Memory search

User:

What did I cook last Thursday?

Expected:

memory_search used

structured + raw memory returned

correct contextual answer



---

Image analyze

User:

What color was the cat in that photo?

Expected:

image_analyze used

correct visual answer



---

Image generation

User:

Send pap

Expected:

image_generate used

protocol respected



---

Constraints

Do NOT:

Change memory schema

Break chat flow

Modify markdown renderer

Add paid APIs

Add heavy dependencies



---

Expected Result

System becomes:

Fully tool-driven

Multi-step capable

No manual vision switch

Contextual memory retrieval


Capabilities:

Search web

Recall contextual memory

Analyze images

Generate images

Fetch weather


All controlled by model decision logic.