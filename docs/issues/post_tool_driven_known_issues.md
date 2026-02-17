Known Issues

This document summarizes issues discovered after integrating the tool-driven architecture.
Issues are grouped by severity and impact on system stability.


---

1. Empty AI Response on Normal Chat (Critical)

Severity: Critical
Area: Core chat pipeline
Status: Reproducible

Symptoms

Normal text messages such as:

“hai”

“ping”

“halo”


Sometimes return:

AI service failed to generate a response

Observations

The same model responds normally when tested directly via OpenRouter.

Occurs even when no tool call is involved.


Likely Cause

The tool-driven response loop expects a final assistant message.

If:

No tool is used, or

Tool/response parsing fails


The system may treat the response as empty and abort.

Impact

Core chat appears unstable.

System feels unresponsive despite model availability.

Breaks fundamental user interaction.



---

2. Tool Execution Returning Empty Assistant Message (Critical)

Severity: Critical
Area: Tool execution loop / response parsing
Status: Reproducible

Symptoms

After a tool call:

AI service failed to generate a response

Logs indicate:

empty assistant message

Likely Cause

Tool result format does not match expected parser structure.

Tool loop exits without producing a final assistant message.

Response structure becomes invalid after tool execution.


Impact

Tool-driven architecture becomes unstable.

All tools may be affected.

System reliability is compromised.



---

3. Image Generation Not Synced Between Interfaces (Critical)

Severity: Critical
Area: Message persistence / multi-interface consistency
Status: Reproducible

Symptoms

From terminal:

Image appears via timg.

Image is not visible in web chat history.


From web:

Image appears correctly.

After reload, image remains visible.


Likely Cause

Terminal flow:

generate image → render directly

But:

Image is not stored as a message in the database.

Web interface only renders images from message history.


Impact

State is inconsistent across interfaces.

Chat history becomes unreliable.

Breaks cross-device or cross-interface continuity.



---

4. Memory Search Only Uses Structured Memory (Medium)

Severity: Medium
Area: Memory retrieval
Status: Confirmed design limitation

Symptoms

Questions about past moments, such as:

“momen paling memorable di Desember”


System only checks:

Episodic memory

Structured memory


It does not search raw message history.

Problem

Important conversations often exist only in:

messages table

But are never used for retrieval.

Impact

Model appears to “forget” events that still exist in the database.

Memory feels unnatural and incomplete.



---

5. Weather Tool Only Supports Current State (Medium)

Severity: Medium
Area: Weather tool capability
Status: Functional limitation

Symptoms

User asks:

cuaca besok gimana?

System:

Does not use the weather tool.

Falls back to web search.


Current Behavior

Weather tool only supports:

Current weather (now)


It does not support:

Forecast

Hourly

Daily

Historical data


Impact

Tool feels incomplete.

Many weather-related intents cannot be handled directly.



---

6. Web Search Result Quality Too Generic (Medium)

Severity: Medium
Area: Web search tool / content retrieval
Status: Reproducible

Symptoms

Example query:

cari harga kondom

Result:

General description

No concrete numbers

No clear price range


Observations

Current tool:

Returns search snippets only.

Does not fetch actual page content.


Model behavior:

Summarizes snippet text.

Cannot extract concrete data.


Additional Issue

Results sometimes include:

Outdated information

Old articles (e.g., 2025 content)


Without time filtering.

Impact

Answers feel vague and impractical.

Not useful for real-world queries.



---

7. Web Search Recency Control Missing (Minor)

Severity: Minor
Area: Web search configuration
Status: Known limitation

Symptoms

Search results may include:

Old articles

Outdated data


Even when the user likely expects current information.

Cause

No support for:

Recency filter

Date constraints

Time-aware ranking


Impact

Occasional outdated answers.

Model must guess temporal relevance.



---

Priority Overview

Critical

1. Empty AI response on normal chat.


2. Tool execution returning empty message.


3. Image history not synced between terminal and web.



Medium

4. Memory search ignores raw message history.


5. Weather tool only supports current state.


6. Web search results too generic.



Minor

7. Web search lacks recency filtering.




---

Summary

Total issues: 7

Critical: 3

Medium: 3

Minor: 1


Core Root-Cause Clusters

1. Tool-driven loop stability.


2. Message persistence consistency.


3. Retrieval quality:

Memory

Web search