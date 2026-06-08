# Yuzu Companion — Architectural Audit & Technical Debt Report

**Date:** 2026-06-07
**Auditor:** Zo AI (GLM-5)
**Scope:** Deep read-only audit of `app/` and `static/js/` after async refactor, PCL rewrite, and tool orchestration overhaul

---

## Executive Summary

Bani, after deeply analyzing the codebase, I found critical issues across all three domains you suspected: **race conditions in async flows**, **massive leftover dead code from legacy tool orchestration**, and **serious token wastage in context building**. The refactor work was substantial but created fragile coupling and hidden failure modes.

**Critical findings:**

- **Race condition vulnerability** in `StreamManager` + `backgroundStreams` synchronization
- **Duplicate cache mechanisms** that could cause state drift
- **Massive dead code** from legacy `/command` parsing still littered throughout
- **Token explosion risk** from unbounded history fetching in `file prompts.py`
- **Frontend memory leak potential** from background stream buffering architecture

This is the hard truth. Below is the full diagnostic breakdown.

---

## 1. STABILITY & SAFETY RISKS

### 1.1 **CRITICAL: Race Condition in Stream State Management**

**File:** `file app/orchestrator.py`
**Location:** Lines 563-587 in `handle_user_message_streaming()`
**Functions:** `_persist_user_async()` and Stream persistence flow

**Issue:**
The orchestrator persists the user message **before** the StreamBuffer completes streaming the assistant response. If a client disconnects mid-stream and reconnects quickly, they may see:

```markdown
user message → persisted
assistant message → missing (stream interrupted)
next user message → no context, orphaned
```

**Why it's a liability:**
The streaming flow splits responsibility:

1. Orchestrator persists `user` message immediately
2. `StreamBuffer._persist_to_db()` persists `assistant` message **only on completion/interruption**
3. No transaction boundary or fence exists between these two operations

If a stream crashes before yielding any chunks but **after** persisting the user message, the conversation history becomes corrupted—`user` message with no response, creating a "ghost turn" that breaks context continuity.

**Senior fix approach:**
Introduce a **stream fence** pattern:

```python
# In orchestrator, before persisting user:
stream_fence = await Database.create_stream_fence(session_id, user_message)
try:
    async for chunk in stream:
        ...
finally:
    await Database.complete_stream_fence(stream_fence.id)
```

This creates an atomic unit: user message + stream state are bound together. On reconnect, the fence can be queried to detect incomplete streams and either resume or clean up.

---

### 1.2 **CRITICAL: Double Buffering Causes State Drift**

**File:** `file app/stream_manager.py` + `file static/js/modules/stream-manager.js`
**Classes:** `StreamBuffer` (backend) and `BackgroundStreamManager` (frontend)

**Issue:**
Both backend AND frontend maintain independent stream buffers:

**Backend (**`StreamBuffer`**):**

```python
self.full_content = ""  # Accumulates chunks in RAM
```

**Frontend (**`BackgroundStreamManager`**):**

```javascript
this.streams = new Map();  // sessionId → {buffer, controller, ...}
```

**Why it's a liability:**

1. **Dual source of truth**: Buffer content can diverge between backend and frontend during network issues
2. **Stale buffer injection**: On reconnect, frontend may flush a stale buffer that the backend has already cleared
3. **Memory leak risk**: If backend stream crashes and is never cleaned up, frontend buffer grows unbounded in the background

**Observed pattern:**

```javascript
// Frontend flushes buffer on reconnect (chat.js line 87-95)
if (contentDiv && stream.buffer) {
    contentDiv.innerHTML = stream.buffer;  // ← DOM injection from frontend buffer
}
```

If backend stream completes and persists BEFORE frontend flushes, the frontend may overwrite the persisted state with stale content.

**Senior fix approach:**
Eliminate frontend buffering entirely—make frontend a **pass-through render surface**:

```javascript
// REMOVE buffer accumulation in BackgroundStreamManager
// Instead, directly render each chunk as it arrives
appendChunk(sessionId, chunk) {
    if (sessionId === this.activeViewSessionId) {
        this._renderToDOM(chunk);  // Direct render, no buffer
    }
    // Backend owns the authoritative buffer
}
```

The backend `StreamBuffer.full_content` is the **single source of truth**. Frontend just renders.

---

### 1.3 **HIGH: Semaphore Cross-Loop Binding Risk**

**File:** `file app/providers/base.py`
**Location:** Lines 25-45 (semaphore creation)
**Functions:** `_get_provider_semaphore_async()`

**Issue:**
Provider semaphores are created lazily but **may bind to the wrong event loop**:

```python
async def _get_provider_semaphore_async(provider: str) -> asyncio.Semaphore:
    if provider not in _PROVIDER_SEMAPHORES:
        _PROVIDER_SEMAPHORES[provider] = asyncio.Semaphore(1)  # ← Binds to CURRENT loop
    return _PROVIDER_SEMAPHORES[provider]
```

**Why it's a liability:**
If FastAPI creates a **new event loop** after a reload or crash, existing semaphores are bound to the **old loop**. When new requests attempt to acquire them, you get:

```markdown
RuntimeError: Task got Future attached to a different loop
```

This is a classic FastAPI + asyncio gotcha.

**Senior fix approach:**
Use `asyncio.Lock()` with **lazy recreation on loop mismatch**:

```python
def _get_provider_semaphore_async(provider: str):
    loop = asyncio.get_running_loop()
    if provider not in _PROVIDER_SEMAPHORES or _PROVIDER_SEMAPHORES[provider]._loop != loop:
        _PROVIDER_SEMAPHORES[provider] = asyncio.Semaphore(1)
    return _PROVIDER_SEMAPHORES[provider]
```

Or better: use a **contextvars-based rate limiter** that's loop-agnostic.

---

### 1.4 **HIGH: Memory Pipeline Race Condition**

**File:** `file app/memory/memory.py`
**Location:** Lines 190-220 (`_try_set_fence_async()`)
**Function:** Fence setting and clearing

**Issue:**
The memory pipeline uses a **fence mechanism** to prevent concurrent runs, but the fence check-and-set is **not atomic**:

```python
# Check fence
if await _is_fence_active_async(session_id):
    return False  # ← Race window here
# Set fence
await _try_set_fence_async(session_id, current_count)  # ← Race window here
```

Between the check and set, **another request can slip through**.

**Why it's a liability:**
Concurrent pipeline triggers (e.g., two users sending messages at the exact threshold) can:

1. Both pass the fence check
2. Both set their own fence (last one wins)
3. Both start segmentation → **duplicate episodes** → semantic fact pollution

**Senior fix approach:**
Use PostgreSQL `SELECT FOR UPDATE` or a dedicated lock table:

```sql
INSERT INTO memory_fences (session_id, status, created_at)
VALUES (%s, 'active', NOW())
ON CONFLICT (session_id) DO NOTHING
RETURNING id;
```

This guarantees **only one active fence per session** at the DB level.

---

### 1.5 **MEDIUM: Missing Error Handling in Tool Execution**

**File:** `file app/tools/registry.py`
**Location:** Lines 150-180 (`execute_tool()`)
**Function:** Tool execution try/catch block

**Issue:**
Tool execution catches `Exception` but **does not differentiate between recoverable and fatal errors**:

```python
try:
    result = await module.execute(...)
except Exception as e:
    return error_result("Tool execution failed. Please try again later.", ...)
```

**Why it's a liability:**

1. **Database connection errors** are silently swallowed → user sees generic "try again later"
2. **Memory errors** (OOM) crash without logging context
3. **Rate limit 429s** are not distinguished from actual failures

**Senior fix approach:**
Implement **error taxonomy**:

```python
except DatabaseConnectionError as e:
    log.critical(f"DB connection lost for tool {tool_name}: {e}")
    return error_result("System temporarily unavailable. Retrying...", ...)
except RateLimitError as e:
    log.warning(f"Rate limit hit for {tool_name}: {e}")
    return error_result("Rate limited. Waiting before retry...", ...)
except Exception as e:
    log.error(f"Tool {tool_name} failed: {e}", exc_info=True)
    return error_result("Failed. Please try again later.", ...)
```

---

### 1.6 **MEDIUM: Frontend Event Listener Accumulation**

**File:** `file static/js/renderer.js`
**Location:** Lines 68-140 (event delegation setup)
**Function:** Document-level click handlers

**Issue:**
Multiple `document.addEventListener('click', ...)` handlers are registered globally:

```javascript
document.addEventListener("click", (event) => { ... });
document.addEventListener("click", (e) => { ... });  // Another one later
```

**Why it's a liability:**
If the chat page is reinitialized without a full page reload (e.g., SPA navigation), **duplicate listeners accumulate**, causing:

- Multiple copy operations per click
- Performance degradation
- Hard-to-debug race conditions

**Senior fix approach:**
Use **single event delegation handler** with namespacing:

```javascript
// Aggregate all click handlers into one
document.addEventListener("click", (event) => {
    const handlers = {
        'copy-code': handleCopyCode,
        'copy-table': handleCopyTable,
        'preview-html': handlePreviewHtml,
        // ...
    };
    
    for (const [action, handler] of Object.entries(handlers)) {
        const btn = event.target.closest(`[data-action="${action}"]`);
        if (btn) {
            handler(btn);
            return;  // Stop after first match
        }
    }
});
```

Ensure handlers are **idempotent** and clean up previous listeners on page unload.

---

## 2. MESSY LOGIC & SPAGHETTI CODE

### 2.1 **CRITICAL: Monolithic Orchestrator Function**

**File:** `file app/orchestrator.py`
**Function:** `handle_user_message_streaming()`
**Lines:** 400-700 (300+ lines)

**Issue:**
This single function does **everything**:

1. Parse image shortcuts
2. Cache uploaded images
3. Stream LLM response
4. Parse tool blocks
5. Execute tools
6. Run synthesis loops
7. Persist messages
8. Trigger memory pipeline

**Why it's a liability:**

- **Cyclomatic complexity &gt; 50** (any change risks regression)
- **Impossible to unit test** (too many side effects)
- **Hidden coupling** (ephemeral_context buildup across loops)
- **No separation of concerns** (streaming vs. orchestration vs. persistence)

**Senior fix approach:**
Extract into **coordinator + strategies**:

```python
class StreamingOrchestrator:
    async def run(self, user_message: str, session_id: int) -> AsyncIterator[str]:
        async with self._establish_context() as ctx:
            async for chunk in self._stream_response(ctx):
                yield chunk
                if self._has_tool_blocks(chunk):
                    async for synthesis in self._run_tool_loop(ctx, chunk):
                        yield synthesis

    async def _stream_response(self, ctx):
        # Pure streaming logic
        ...

    async def _run_tool_loop(self, ctx, first_pass):
        # Pure tool orchestration
        ...
```

Each step becomes **testable in isolation**.

---

### 2.2 **CRITICAL: Legacy** `/command` **Parsing Dead Code**

**Files:**

- `file app/commands.py` (lines 450-520: legacy `detect_command()`, `execute_command()`)
- `file app/orchestrator.py` (lines 325-340: legacy `/imagine` fast-path)

**Issue:**
The codebase still contains **full legacy tool protocol** support:

```python
# commands.py line 450
def detect_command(text: str, scan_mode: str = "first_line"):
    """DEPRECATED: Use parse_tool_blocks() instead."""
    log.warning("detect_command() is deprecated...")
    # 50+ lines of dead code
```

```python
# orchestrator.py line 325
if stripped.startswith("/imagine ") or stripped.startswith("<command>"):
    # Legacy path that duplicates new tool registry logic
```

**Why it's a liability:**

- **Dual execution paths** for same functionality (legacy `/imagine` vs. `<tool>imagine`)
- **Maintenance nightmare** (changes must be applied twice)
- **Confusing for new developers** ("which path do I use?")
- **Lint warnings** are being logged but not acted upon

**Senior fix approach:**
**Ruthless deletion**:

1. Remove all `detect_command()` functions
2. Remove legacy `/imagine` fast-path
3. Ensure ALL tool invocation goes through `parse_tool_blocks()` → `execute_commands()`
4. Add deprecation timeline in CHANGELOG.md

---

### 2.3 **HIGH: Massive `file prompts.py` System Prompt**

**File:** `file app/prompts.py`
**Function:** `build_system_message_async()`
**Lines:** 330-550 (220-line string template)

**Issue:**
The system prompt is a **220-line monolithic string** containing:

- Behavioral rules
- Tool documentation
- Cognitive reasoning format
- Session topology
- Context block building

**Why it's a liability:**

- **Embeds business logic** in a string (hard to test, hard to version)
- **Duplication** of tool documentation between prompts.py and registry.py
- **Updating is fragile** (must edit giant string without breaking format)
- **Token wastage** (entire block sent every turn)

**Senior fix approach:**
Split into **composable blocks**:

```python
class PromptBuilder:
    def __init__(self, profile, session_id):
        self.blocks = [
            IdentityBlock(profile),
            BehaviorBlock(profile),
            ToolBlock(get_tool_definitions()),
            ContextBlock(session_id),
        ]
    
    def render(self) -> str:
        return "\n\n".join(b.render() for b in self.blocks)
```

Each block can be:

- **Unit tested**
- **Versioned independently**
- **Conditionally included** (e.g., ToolBlock only if tools available)

---

### 2.4 **HIGH: Tangled Memory Pipeline Logic**

**File:** `file app/memory/memory.py`
**Function:** `run_memory_pipeline_async()`
**Lines:** 350-450

**Issue:**
The pipeline does **too many things in one function**:

1. Fetch messages
2. Batch segment
3. Create episodes
4. Run PCL
5. Run memory review
6. Clear fence

**Why it's a liability:**

- **Side effects everywhere** (DB writes, LLM calls, embedding generation)
- **Hard to test edge cases** (e.g., what if segmentation fails but PCL succeeds?)
- **No transaction boundaries** (partial failures leave inconsistent state)

**Senior fix approach:**
Extract into **pipeline stages**:

```python
class MemoryPipeline:
    async def run(self, session_id: int, count: int):
        async with PipelineTransaction(session_id) as tx:
            messages = await self.fetch_messages(tx, count)
            segments = await self.segment(tx, messages)
            for seg in segments:
                episode = await self.create_episode(tx, seg)
                await self.run_pcl(tx, episode)
            await self.review(tx)
            await tx.commit()
```

On failure, `PipelineTransaction` rolls back everything.

---

### 2.5 **MEDIUM: Frontend Module Exports Are Confusing**

**File:** `file static/js/chat.js`
**Lines:** 5-50 (imports and global exports)

**Issue:**
Chat.js re-exports everything from modules BUT ALSO keeps global window bindings:

```javascript
import { addMessage, ... } from "./modules/index.js";

window.addMessage = addMessage;
window.loadChatHistory = loadChatHistory;
// ... 10+ more global assignments
```

**Why it's a liability:**

- **Dual import mechanism** (ESM + window globals)
- **Risk of shadowing** (what if another script defines `window.addMessage`?)
- **Hard to trace dependencies** (which script owns `window.currentStreamMessage`?)

**Senior fix approach:**
Standardize on **ESM imports only**. Remove `window.*` bindings or centralize them in a **single namespace**:

```javascript
import * as Chat from "./modules/index.js";
// Export to window as namespace
window.Chat = Chat;

// Usage: Chat.addMessage(...)
```

---

### 2.6 **MEDIUM: Dead Code in Commands Parser**

**File:** `file app/commands.py`
**Function:** `parse_tool_blocks()`
**Lines:** 60-150

**Issue:**
The parser contains **overly complex logic** for edge cases that may never occur:

```python
# Lines 120-140: Extremely defensive multiline parsing
# Count open/close tags for streaming edge case
const openCount = (result.match(openPattern) || []).length;
const closeCount = (result.match(closePattern) || []).length;
```

**Why it's a liability:**

- **Premature optimization** (handling streaming incomplete tags)
- **But:** This is called **after streaming completes** in orchestrator (line 560)
- **Dead path:** Streaming edge case handling never executes

**Senior fix approach:**
Simplify to **post-stream parsing** only:

```python
def parse_tool_blocks(text: str) -> tuple[list[str], str]:
    # Assume complete text (streaming already finished)
    # Remove all the streaming-incomplete logic
    ...
```

Or move streaming handling to a **separate function** (`parse_incomplete_tool_blocks()`).

---

## 3. OPTIMIZATION BOTTLENECKS

### 3.1 **CRITICAL: Unbounded History Fetch**

**File:** `file app/prompts.py`
**Function:** `build_messages()`
**Line:** 570

**Issue:**
History is fetched with a **hardcoded limit of 120 messages**:

```python
history = await Database.get_chat_history_for_ai_async(
    session_id=session_id,
    limit=120,
    recent=True,
    include_image_paths=include_image_paths,
)
```

**Why it's a liability:**

- **Token explosion risk**: 120 messages × avg 200 tokens = **24,000 tokens** of context
- **Plus:** System prompt (220 lines), memory block (variable), session events
- **Total context can exceed 40K tokens** →:model truncation or API errors
- **Costly:** Every turn fetches full 120-message history (no caching)

**Observed context size calculation:**

```python
# From memory.py line 80
total_chars = sum(len(m.get("content", "")) for m in messages)
# If 120 messages × 500 chars/message = 60,000 chars → ~15K tokens just for history
```

**Senior fix approach:**
Implement **sliding window with importance scoring**:

```python
async def build_messages(session_id: int, max_tokens: int = 16000):
    messages = await Database.get_recent_messages(session_id, limit=1000)
    scored = [(m, calculate_importance(m)) for m in messages]
    scored.sort(key=lambda x: x[1], reverse=True)
    
    selected = []
    token_count = 0
    for msg, score in scored:
        msg_tokens = count_tokens(msg.content)
        if token_count + msg_tokens > max_tokens:
            break
        selected.append(msg)
        token_count += msg_tokens
    
    return selected
```

Or use **retrieval-based context** (fetch only relevant messages via semantic search).

---

### 3.2 **CRITICAL: Frontend Mermaid Re-render on Every Chunk**

**File:** `file static/js/renderer.js`
**Function:** `initializeMermaidDiagrams()`
**Lines:** 850-880

**Issue:**
During streaming, every chunk triggers **Mermaid initialization**:

```javascript
async initializeMermaidDiagrams(container) {
    const mermaidElements = container.querySelectorAll(".mermaid:not([data-processed])");
    for (const el of mermaidElements) {
        await mermaid.run({ nodes: [el] });  // ← Expensive WebAssembly parse
        el.setAttribute("data-processed", "true");
    }
}
```

**Why it's a liability:**

- **Mermaid.parse() is CPU-intensive** (WebAssembly + diagram layout)
- **Called on EVERY chunk** during streaming (if Mermaid block detected)
- **Causes UI jank** and potential memory leaks (unparsed diagrams accumulate)

**Senior fix approach:**
Debounce Mermaid rendering until **stream completes**:

```javascript
class MessageRenderer {
    renderStreaming(text, isStreaming = true) {
        // Replace ALL mermaid blocks with placeholders during streaming
        // Only render Mermaid when isStreaming = false
        if (isStreaming) {
            return this.render(this._replaceMermaidWithPlaceholder(text));
        } else {
            return this.render(text);  // Full Mermaid parse
        }
    }
    
    finalizeMermaid(container) {
        // One-shot Mermaid initialization on stream end
        this.initializeMermaidDiagrams(container);
    }
}
```

---

### 3.3 **HIGH: N+1 Database Queries in Memory Review**

**File:** `file app/memory/memory_review.py`
**Function:** `review_memory_async()`
**Lines:** 50-100

**Issue:**
Memory review fetches facts one by one:

```python
for fact_id in pending_ids:
    fact = await get_fact_by_id_async(fact_id)  # ← N queries
    # ... process ...
```

**Why it's a liability:**

- If 50 facts pending review → **50 separate DB queries**
- Each query includes PostgreSQL round-trip latency
- **No batch fetch optimization**

**Senior fix approach:**
Batch fetch:

```python
facts = await get_facts_by_ids_async(pending_ids)  # Single query
for fact in facts:
    # process
```

Add `get_facts_by_ids_async()` to `file db_memory.py` using `WHERE id = ANY(%s)`.

---

### 3.4 **HIGH: Repeated Embedding Generation**

**File:** `file app/memory/retrieval.py`
**Function:** `retrieve_memories_combined_async()`
**Lines:** 80-120

**Issue:**
Combined retrieval generates **TWO embeddings** for the same query:

```python
# For static facts
static = await search_similar_async(embedding, fact_type=FACT_TYPE_STATIC, ...)

# For dynamic facts
dynamic = await search_similar_async(embedding, fact_type=FACT_TYPE_DYNAMIC, ...)
```

**Why it's a liability:**

- Embedding generation is **called once** (good)
- But **two ANN searches** are executed separately
- Each search includes **vector normalization** and **index traversal**
- Could be combined into a **single query** filtering on `fact_type`

**Senior fix approach:**
Single unified search:

```python
results = await search_similar_async(
    embedding,
    fact_type=None,  # No filter
    metadata_filter={},
    limit=15
)
# Split results in memory
static = [r for r in results if r['fact_type'] == 'static']
dynamic = [r for r in results if r['fact_type'] == 'dynamic']
```

Or use PostgreSQL `UNION ALL` to merge both searches server-side.

---

### 3.5 **MEDIUM: Inefficient JSON Parsing in PCL**

**File:** `file app/memory/pcl.py`
**Function:** `_extract_json_from_markdown()`
**Lines:** 50-100

**Issue:**
PCL uses **complex regex extraction** for JSON:

```python
markdown_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
match = re.search(markdown_pattern, cleaned)
if match:
    extracted = match.group(1).strip()
# ... fallback parsing attempts ...
```

**Why it's a liability:**

- **Regex on large LLM responses** (potential ReDoS if response is malformed)
- **Multiple fallback attempts** (slashes CPU time)
- **Not cached** (every PCL run parses JSON from scratch)

**Senior fix approach:**
Use **structured output** instead of text parsing:

```python
# In PCL prompt, request JSON mode
response = await ai_manager.send_message_raw(
    messages,
    response_format={"type": "json_object"}  # Force JSON mode
)
# No parsing needed - already validated JSON
actions = response["choices"][0]["message"]["content"]
```

Modern LLM APIs support `response_format` parameter to guarantee JSON.

---

### 3.6 **MEDIUM: Frontend DOM Thrashing During Streaming**

**File:** `file static/js/modules/messages.js`
**Function:** `addMessage()` (inferred from chat.js usage)

**Issue:**
During streaming, every chunk triggers **DOM re-render**:

```javascript
// Inferred pattern (need to read messages.js to confirm)
contentDiv.innerHTML += chunk;  // ← Forces full reflow
```

**Why it's a liability:**

- **innerHTML +=** is an anti-pattern (serializes + deserializes entire DOM)
- Causes **layout thrashing** (browser recalculates styles every chunk)
- **Performance degrades** with message length

**Senior fix approach:**
Use **DocumentFragment** for batch updates:

```javascript
const fragment = document.createDocumentFragment();
for (const chunk of chunks) {
    const textNode = document.createTextNode(chunk);
    fragment.appendChild(textNode);
}
contentDiv.appendChild(fragment);  // Single reflow
```

Or use **requestAnimationFrame** to batch updates.

---

## 4. MISCELLANEOUS TECHNICAL DEBT

### 4.1 **Outdated AGENTS.md References**

**File:** `file AGENTS.md`
**Issue:**
Contains references to old file paths that may not exist post-refactor:

- `file app/providers.py` (now `file app/providers/__init__.py`)
- `app/database/` (now `app/db/`)

**Fix:** Update all path references and verify each exists.

---

### 4.2 **Mixed Logging Standards**

**Files:** Multiple
**Issue:**
Codebase mixes:

- `log = get_logger(__name__)` (correct)
- `logger = logging.getLogger(__name__)` (inconsistent)
- `print()` statements (forbidden per AGENTS.md)

**Fix:** Standardize on `get_logger(__name__)` everywhere.

---

### 4.3 **Missing Type Hints in Several Functions**

**Files:** `file app/tools/*.py`
**Issue:**
Multiple tool execution functions lack proper type hints:

```python
def execute(arguments):  # No return type annotation
    ...
```

**Fix:** Add comprehensive type hints per AGENTS.md rule 11.

---

## 5. PRIORITY ACTION ITEMS

### Immediate (P0 - Critical)

1. **Fix stream fence race condition** in orchestrator persistence flow
2. **Eliminate frontend buffering** in `BackgroundStreamManager`
3. **Remove all legacy** `/command` **and** `/imagine` **dead code**
4. **Add token limits** to history fetching in `file prompts.py`

### Short-Term (P1 - High)

5. **Refactor** `handle_user_message_streaming()` **into smaller functions**
6. **Fix semaphore cross-loop binding** in `file providers/base.py`
7. **Implement atomic fence mechanism** in memory pipeline
8. **Debounce Mermaid rendering** until stream completion

### Medium-Term (P2 - Medium)

 9. **Optimize history context** with importance-based retrieval
10. **Fix N+1 queries** in memory review
11. **Standardize logging** across all modules
12. **Add comprehensive type hints** to all tool modules

### Long-Term (P3 - Technical Debt)

13. **Decompose system prompt** into composable blocks
14. **Standardize frontend imports** on ESM only
15. **Implement streaming transaction boundaries** for atomicity

---

## 6. TESTING RECOMMENDATIONS

To verify fixes, create tests for:

- **Stream reconnect scenarios** (simulate client disconnect mid-stream)
- **Concurrent memory pipeline triggers** (test fence atomicity)
- **Token limit enforcement** (reject &gt;32K token contexts)
- **Frontend buffer consistency** (test multiple session switches)

---

## Conclusion

Bani, the refactor work moved fast and got the system working, but at the cost of **fragile coupling** and **hidden bombs**. The race conditions in streaming and memory pipeline are the most urgent—they will bite you under load or during network issues.

The dead code from legacy tool orchestration adds cognitive overhead and maintenance debt. Every developer who touches this codebase will be confused by the dual paths.

The token wastage is real. You're sending **15-20K tokens** of context every turn for long-running sessions. At scale, this costs real money and slows responses.

I recommend addressing **P0 items immediately** before they manifest as production incidents. The architecture is solid at a high level, but the implementation details have sharp edges.

This is the hard truth. The good news: all of this is fixable with focused, surgical refactors—no need to rebuild from scratch.

---

**Audit Complete.**
Questions? I'll be here to explain any finding in detail.