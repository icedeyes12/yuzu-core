Task: Unified Tool Architecture Refactor

Goal

Refactor the entire tool system so that:

- All tools use one unified pipeline
- No analytical mode
- No special send functions for tools
- LLM remains a single reasoning entity
- Model only switches for vision after image generation
- Image pipeline is consistent, auditable, and deterministic

---

Core Philosophy

Tools are not thinking entities.
Tools are only hands of the LLM.

The LLM is the single entity that:

- Reads context
- Decides tool usage
- Issues commands
- Continues reasoning
- Produces the final response

---

Unified Tool Flow (Global)

1. User message arrives
2. LLM decides tool is needed
3. LLM issues tool command
4. Tool executes
5. Tool result saved into history
6. System sends new request to LLM
   using the same pipeline
7. LLM reads tool result
8. LLM produces final natural response

---

Critical Rule: Same Pipeline After Tool

After any tool execution:

The system must send a new request to the LLM using:

- Same system message
- Same context builder
- Same memory injection
- Same recent history
- Tool result included in history

The system must NOT:

- Use a special send function
- Bypass context builder
- Send partial context
- Use analytical mode
- Use a different pipeline

---

Model Selection Rules

There is no analytical model.

Only:

Model| Usage
Default chat model| All tools and conversations
Vision model| Only after image generation

---

Model Switching Logic

if last_tool == image_tool:
    use vision_model
else:
    use default_chat_model

Everything else must remain identical:

- System prompt
- Context builder
- Message format
- Tool results
- History
- Tool schemas

---

Tool-Specific Flows

---

1. Web Search Tool

User asks factual question
→ LLM issues /web_search
→ Tool fetches results
→ Save role: web_tool
→ Send new request (default chat model)
→ LLM responds naturally

---

2. Memory Tool (SQL-Based)

LLM can send raw SQL queries.

Example

/memory_sql
SELECT id, content
FROM messages
WHERE content LIKE '%1T parameter%'
  AND role != 'memory_tool'
ORDER BY id DESC
LIMIT 5;

---

Flow

User asks about memory
→ LLM issues /memory_sql
→ Tool executes query
→ Save role: memory_tool
→ Send new request (default chat model)
→ LLM responds naturally

---

Memory Tool Security Rules

Allowed

- SELECT
- UPDATE

Blocked (Hardcoded)

- INSERT
- DELETE
- DROP
- TRUNCATE
- ALTER TABLE
- CREATE TABLE
- PRAGMA writable_schema
- VACUUM INTO

Principle:

Read + Edit only
No create, no delete, no destructive operations.

---

Memory Loop Prevention

All memory queries must automatically include:

AND role != 'memory_tool'

Hardcoded inside the memory tool.

---

3. Image Generation Tool

User requests image
→ LLM issues /imagine prompt
→ Image tool generates image
→ Save role: image_tool
→ Render image in chat
→ Send new request
   using vision model
→ LLM responds naturally

---

Image Tool Rules

After issuing "/imagine":

Assistant may:

- Stay silent
- Continue unrelated conversation

Assistant must NOT:

- Mention image links
- Mention file paths
- Mention placeholders
- Claim it generated the image

---

Image Tool Storage

role: image_tool
content: metadata + image path

---

Vision Follow-up

After image tool:

- Send new request
- Same pipeline
- Same system message
- Same context builder
- Same history

Only difference:

model = vision_model

---

Image Generation Pipeline Audit (Critical)

Currently there are two files:

/tools/multimodal.py
/tools/generate_image.py

There are signs that:

- "multimodal.py" still contains old image logic (Hunyuan)
- "generate_image.py" contains:
  - Hunyuan
  - Z Image Turbo

---

Required Refactor

Single Source of Truth

All image generation logic must exist only in:

/tools/generate_image.py

"multimodal.py" must NOT contain image generation logic.

If any exists, replace with:

# Image generation logic moved to tools/generate_image.py
# This module is now only for multimodal input processing.

---

Runtime Model Logging (Mandatory)

Each image generation must log:

[IMAGE TOOL]
Selected model: z_image_turbo
Endpoint: https://...

---

Config Consistency

Profile database must contain:

image_model
vision_model

No silent fallback allowed.

---

Vision / Multimodal Chronology

Visual context must remain chronological.

Correct:

msg1
msg2 + image
msg3 + image
msg4
msg5
msg6 + image

Incorrect:

msg1
msg2
msg3
msg4
msg5
msg6
visual_context

---

Image URL Handling

If user sends direct image URL:

download → base64 → multimodal pipeline

Must match direct upload pipeline.

---

Frontend Tool Result Rendering

All tool results must use collapsible blocks:

<details>
<summary>Tool result</summary>

```bash
tool command

«raw tool output»

</details>
```---

Frontend Image Bubble Fix

All image messages must be single unified bubbles:

Image only

[user bubble: image]

Text + image

[user bubble:
    text
    image
]

---

Acceptance Criteria

Image Pipeline

- Correct model used
- Correct log output
- No silent fallback
- No image logic in multimodal.py

---

Tool Flow

- Web tool → natural response
- Memory SQL → safe execution
- Image tool → vision follow-up
- No loops
- No analytical mode

---

Production Discipline (MANDATORY)

Before committing:

1. Run all tests
2. Verify image model logs
3. Check tool loop behavior
4. Test:
   - web search
   - memory SQL
   - image generation (both models)
   - vision follow-up
5. Perform code review
6. Audit the entire codebase
   - No duplicated tool logic
   - No hidden fallbacks
   - No hardcoded models
7. Confirm no regressions

Only then:

Commit changes when done.