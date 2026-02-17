Task: Replace SearXNG-based web search with DuckDuckGo snippet swarm

Background

Current web search implementation relies on SearXNG public instances.

Observed problems:

- Frequent "403" and "429" responses
- Unstable results depending on instance
- Requires infrastructure to be reliable (self-hosted SearXNG)
- Not suitable for current environment (Termux, no VPS)

Manual tests using DuckDuckGo HTML endpoint show:

- More stable responses
- Useful snippets already contain relevant information
- No need to fetch full pages
- Works without additional infrastructure

Because the tool-driven architecture only needs context for the LLM, not full-page scraping, a snippet swarm approach is more appropriate.

---

Goal

Replace the current SearXNG-based web search tool with a:

«DuckDuckGo HTML snippet swarm (20–30 results)»

The tool should:

1. Query DuckDuckGo HTML endpoint
2. Extract top 20–30 search results
3. Return:
   - title
   - url
   - snippet
4. Provide this as structured context to the LLM
5. Let the LLM synthesize the final answer

No page fetching is required.

---

Target Architecture

Old flow

LLM
 → web_search
     → SearXNG instance
         → upstream engines
 → results
 → LLM final answer

Problems: unstable, infra-dependent, frequent 403.

---

New flow

LLM
 → web_search
     → DuckDuckGo HTML
     → extract 20–30 snippets
 → snippet swarm
 → LLM final answer

Characteristics:

- Single request per search
- No page scraping
- No external infra required
- Faster and more stable

---

Functional Requirements

web_search tool must:

- Accept:
  - "query: str"
- Perform:
  - POST request to:
    https://html.duckduckgo.com/html/
- Extract:
  - up to 20–30 results
- For each result:
  - title
  - link
  - snippet
- Return structured list:

Example:

[
  {
    "title": "...",
    "url": "...",
    "snippet": "..."
  }
]

---

Non-Goals

Do NOT:

- Fetch individual pages
- Parse full article content
- Implement crawling
- Reintroduce SearXNG logic
- Add new infrastructure

---

Files Likely Affected

Copilot should inspect and update:

- "web.py"
- "tools.py"
- Any search provider abstractions
- Tool registry or dispatcher
- Config files referencing SearXNG
- Any fallback logic tied to SearXNG responses

Search for:

- "searx"
- "searxng"
- "search provider"
- "web search"
- "search engine"

---

Acceptance Criteria

1. "web_search" no longer references SearXNG.
2. Tool uses DuckDuckGo HTML endpoint.
3. Tool returns 20–30 snippets per query.
4. Tool output is correctly consumed by the LLM.
5. No page fetching logic remains.
6. End-to-end query produces relevant answers using snippet context.

---

Suggested Implementation Steps

1. Locate current web search provider code.
2. Remove or disable SearXNG integration.
3. Implement DuckDuckGo HTML search function.
4. Update tool interface if needed.
5. Ensure tool output format matches LLM expectations.
6. Test with queries like:
   - “latest Nvidia GPU release”
   - “how does CRDT work”
   - “Python asyncio vs threading”
   - “Samsung S24 specs”

---

Notes

This change is architectural, not just a small bug fix in "web.py".

Multiple modules may depend on the current search provider, so changes must be applied consistently across the codebase.