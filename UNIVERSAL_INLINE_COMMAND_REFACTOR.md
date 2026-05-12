# Roadmap: Universal Inline Command + 2-Pass Synthesis (v3.1.0)

> **Status:** 📋 PLANNING — Ready for implementation  
> **Version:** 3.1.0  
> **Last Updated:** 2026-05-12  
> **Branch:** `refactor/universal-inline-command` (to be created from `dev`)

---

## Executive Summary

Refactor tool execution from **dual-path** (native tool calls + inline `/command`) to **single universal inline path** with proper UX flow:

```
User Message → LLM First Pass → Placeholder → Tool Execution → Result → Synthesis
```

### Goals

| Goal | Current | Target |
|------|---------|--------|
| Tool invocation | Dual: native API calls + `/command` | Single: inline `/command` only |
| Tool result storage | Per-tool roles (`image_tools`, etc.) | Single `tools` role |
| Placeholder during execution | ❌ None | ✅ Immediate placeholder |
| First pass persistence | ❌ Not stored | ✅ Stored as `assistant` |
| UX flow | Silent during tool execution | Visible placeholder → result |

### Non-Goals

- No new tools
- No frontend rewrite (only add placeholder handling)
- No database schema changes

---

## Current Architecture Audit

### Files Involved

| File | Current Role | Changes Needed |
|------|--------------|----------------|
| `orchestrator.py` | Dual-path execution, synthesis | Remove native path, add placeholder |
| `commands.py` | `/command` detection, StreamFilter | Add XML parsing, placeholder emission |
| `tools/schemas.py` | Markdown contract (`<details>`) | Add XML format, dual output |
| `tools/registry.py` | Tool dispatch | Add XML result formatting |
| `database/db_queries.py` | Tool roles, history formatting | Add `tools` role, dual-path reader |
| `providers.py` | Native tool call support | Remove tool call parsing |
| `prompts.py` | System prompt | Add tool instructions |
| `llm_client.py` | LLM calls with tools[] | Remove tools[] parameter |
| `static/js/chat.js` | Frontend | Add placeholder handling |

### Current Execution Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ handle_user_message() / handle_user_message_streaming()         │
└─────────────────────────────────────────────────────────────────┘
         │                                           │
         ▼                                           ▼
┌─────────────────────┐                 ┌─────────────────────┐
│ PATH 1: Native      │                 │ PATH 2: Inline      │
│ _parse_raw_tool_    │                 │ detect_command()    │
│ calls()             │                 │                     │
│ _execute_tool_      │                 │ execute_command()   │
│ calls()             │                 │                     │
└─────────────────────┘                 └─────────────────────┘
         │                                           │
         └─────────────────┬─────────────────────────┘
                           ▼
              _persist_tool_result()
                           │
                           ▼
              _run_synthesis() / _stream_synthesis()
```

### Problems Identified

| # | Problem | Impact |
|---|---------|--------|
| 1 | Dual execution paths | Complexity, drift risk |
| 2 | No placeholder during tool execution | Silent UX gap |
| 3 | First pass not stored | Incomplete history |
| 4 | Per-tool roles (`image_tools`, etc.) | Inconsistent storage |
| 5 | Markdown contract only | No structured data for synthesis |

---

## Target Architecture

### New Execution Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. USER MESSAGE                                                 │
│    Database.add_message("user", message)                        │
└─────────────────────────────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. LLM FIRST PASS (streaming)                                   │
│    "Baik, saya akan mencari memori tentang kucing..."           │
│    <tools>                                                      │
│      <name>memory_search</name>                                 │
│      <args><query>cats</query></args>                           │
│    </tools>                                                     │
└─────────────────────────────────────────────────────────────────┘
                           │
                           │ StreamFilter detects <tools>
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. EMIT PLACEHOLDER (immediate)                                 │
│    yield {"type": "tool_executing", "name": "memory_search",    │
│           "args": {"query": "cats"}}                            │
│    Frontend shows: 🔧 memory_search ⏳ Executing...             │
└─────────────────────────────────────────────────────────────────┘
                           │
                           │ Continue streaming first pass
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. STORE FIRST PASS                                             │
│    Database.add_message("assistant", first_pass_text)           │
│    (includes acknowledgment + <tools> block)                    │
└─────────────────────────────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. EXECUTE TOOL                                                 │
│    result = execute_tool("memory_search", {"query": "cats"})    │
│    xml_result = format_tool_result_xml(result)                  │
└─────────────────────────────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. EMIT RESULT (replace placeholder)                            │
│    yield {"type": "tool_result", "status": "ok",                │
│           "xml": "<tools>...</tools>"}                          │
│    Frontend updates placeholder: ✓ Found 3 memories             │
└─────────────────────────────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ 7. STORE TOOL RESULT                                            │
│    Database.add_message("tools", xml_result)                    │
└─────────────────────────────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ 8. SECOND PASS (synthesis)                                      │
│    Context: user + assistant(first) + tools                     │
│    LLM generates natural response                               │
│    Stream synthesis to frontend                                  │
└─────────────────────────────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ 9. STORE SYNTHESIS                                              │
│    Database.add_message("assistant", synthesis_text)            │
└─────────────────────────────────────────────────────────────────┘
```

### DB Message Sequence

| Step | Role | Content |
|------|------|---------|
| 1 | `user` | "Search my memories about cats" |
| 2 | `assistant` | "Baik, saya akan mencari...\n<tools>...</tools>" |
| 3 | `tools` | `<tools><name>memory_search</name>...</tools>` |
| 4 | `assistant` | "Saya menemukan 3 memori tentang kucing..." |

---

## Implementation Phases

### Phase 1: Infrastructure — XML Format & Storage

**Goal:** Add XML formatting without breaking existing markdown contract.

**Files:**

- [ ] `app/tools/schemas.py` — Add XML formatting functions
- [ ] `app/database/db_queries.py` — Add `TOOL_ROLE_UNIVERSAL`, dual-path reader

**Tasks:**

- [ ] 1.1 Add `sanitize_xml_value()` to `tools/schemas.py`
  - [ ] Escape XML entities: `&`, `<`, `>`, `"`, `'`
  - [ ] Strip control characters (0x00-0x1F except 0x09, 0x0A, 0x0D)
  - [ ] Remove NULL bytes

- [ ] 1.2 Add `format_tool_result_xml()` to `tools/schemas.py`
  - [ ] Input: `tool_name`, `result` dict
  - [ ] Output: XML string with `<tools>`, `<name>`, `<status>`, `<data>`, `<error>`
  - [ ] Use `sanitize_xml_value()` for all text content

- [ ] 1.3 Add `TOOL_ROLE_UNIVERSAL = "tools"` to `db_queries.py`
  - [ ] Update `tool_role_for()` to optionally use universal role

- [ ] 1.4 Add dual-path history reader to `db_queries.py`
  - [ ] `format_ai_history_rows()` handles both:
    - Old: `role="image_tools"`, content=`<details>...</details>`
    - New: `role="tools"`, content=`<tools>...</tools>`
  - [ ] Both expand to same AI context format

- [ ] 1.5 Write unit tests
  - [ ] `test_sanitize_xml_value()` — entities, control chars, NULL bytes
  - [ ] `test_format_tool_result_xml()` — ok result, error result
  - [ ] `test_format_ai_history_rows()` — old format, new format, mixed

**Verification:**

```bash
python -m pytest tests/test_tool_xml_format.py -v
ruff check app/tools/schemas.py app/database/db_queries.py
```

**Commit:** `feat(tools): Phase 1 - Add XML formatting and dual-path history reader`

---

### Phase 2: Registry — Dual Output Format

**Goal:** Tools return both XML and markdown for backward compatibility.

**Files:**

- [ ] `app/tools/registry.py` — Update `execute_tool()` return format

**Tasks:**

- [ ] 2.1 Update `execute_tool()` return format
  - [ ] Return: `{"ok": bool, "data": dict, "markdown": str, "xml": str}`
  - [ ] `xml` is new, `markdown` is kept for backward compat

- [ ] 2.2 Add `format_tool_result()` helper in registry
  - [ ] Wraps `ok_result()` and `error_result()` to add `xml` field
  - [ ] Uses `format_tool_result_xml()` from schemas

- [ ] 2.3 Update each tool to use new format
  - [ ] `image_generate.py` — verify returns `{"ok", "data", "markdown", "xml"}`
  - [ ] `http_request.py` — verify returns `{"ok", "data", "markdown", "xml"}`
  - [ ] `memory_store.py` — verify returns `{"ok", "data", "markdown", "xml"}`
  - [ ] `memory_search.py` — verify returns `{"ok", "data", "markdown", "xml"}`

- [ ] 2.4 Write integration tests
  - [ ] `test_execute_tool_returns_both_formats()`
  - [ ] Verify each tool returns `xml` field

**Verification:**

```bash
python -m pytest tests/test_registry.py -v
ruff check app/tools/registry.py
```

**Commit:** `feat(registry): Phase 2 - Dual output format (XML + markdown)`

---

### Phase 3: StreamFilter — XML Parsing & Placeholder Emission

**Goal:** StreamFilter detects `<tools>`, emits placeholder, extracts tool call.

**Files:**

- [ ] `app/commands.py` — Rewrite `StreamFilter`

**Tasks:**

- [ ] 3.1 Add `StreamState` enum
  - [ ] `NORMAL` — yielding text immediately
  - [ ] `TOOL_DETECTED` — buffering `<tools>` block
  - [ ] `TOOL_EXECUTING` — waiting for result (placeholder shown)

- [ ] 3.2 Add XML parsing patterns
  - [ ] `_TOOLS_BLOCK_PATTERN` — regex to match `<tools>...</tools>`
  - [ ] `_parse_tools_block()` — extract name, args from XML

- [ ] 3.3 Rewrite `StreamFilter.feed()`
  - [ ] Character-by-character processing
  - [ ] Detect `<tools>` opening tag
  - [ ] Buffer until `</tools>` closing tag
  - [ ] On complete block: emit placeholder dict, store parsed tool call
  - [ ] Yield text before/after tools block immediately

- [ ] 3.4 Add `StreamFilter.tool_call` property
  - [ ] Returns `{"name": str, "args": dict}` after detection
  - [ ] Returns `None` if no tool detected

- [ ] 3.5 Add `StreamFilter.flush()` 
  - [ ] Handle incomplete tools block at stream end
  - [ ] Return any buffered text

- [ ] 3.6 Write unit tests
  - [ ] `test_normal_text_yields_immediately()`
  - [ ] `test_tools_block_detected()`
  - [ ] `test_tools_block_emits_placeholder()`
  - [ ] `test_text_after_tools_yields()`
  - [ ] `test_incomplete_tools_block_flush()`

**Verification:**

```bash
python -m pytest tests/test_stream_filter.py -v
ruff check app/commands.py
```

**Commit:** `feat(commands): Phase 3 - StreamFilter XML parsing & placeholder`

---

### Phase 4: Orchestrator — Single Path Flow

**Goal:** Remove native tool call path, implement single inline path with placeholder.

**Files:**

- [ ] `app/orchestrator.py` — Major refactor

**Tasks:**

- [ ] 4.1 Remove native tool call functions
  - [ ] Delete `_parse_raw_tool_calls()`
  - [ ] Delete `_execute_tool_calls()`
  - [ ] Remove `tool_calls` handling in `handle_user_message()`

- [ ] 4.2 Update `handle_user_message_streaming()` flow
  - [ ] Remove native tool call branch
  - [ ] After stream ends, check `sf.tool_call`
  - [ ] If tool detected:
    - [ ] Store first pass: `Database.add_message("assistant", first_pass_text)`
    - [ ] Emit placeholder event (already done by StreamFilter)
    - [ ] Execute tool
    - [ ] Emit result event
    - [ ] Store tool result: `Database.add_message("tools", xml_result)`
    - [ ] Run synthesis
    - [ ] Store synthesis: `Database.add_message("assistant", synthesis_text)`
  - [ ] If no tool:
    - [ ] Store response: `Database.add_message("assistant", text)`

- [ ] 4.3 Update `_persist_tool_result()` signature
  - [ ] Accept `xml: str` parameter
  - [ ] Use `TOOL_ROLE_UNIVERSAL` for storage role

- [ ] 4.4 Add synthesis context builder
  - [ ] Include first pass text in context
  - [ ] Include tool result XML

- [ ] 4.5 Remove `tools[]` array from LLM calls
  - [ ] Verify `generate_ai_response_streaming()` doesn't pass tools

- [ ] 4.6 Write integration tests
  - [ ] `test_tool_execution_flow()` — full flow with DB verification
  - [ ] `test_no_tool_flow()` — plain response
  - [ ] `test_synthesis_after_tool()` — verify synthesis happens

**Verification:**

```bash
python -m pytest tests/test_orchestrator.py -v
ruff check app/orchestrator.py
```

**Commit:** `feat(orchestrator): Phase 4 - Single path flow with placeholder`

---

### Phase 5: Providers — Remove Tool Call Support

**Goal:** Clean up providers, remove native tool call parsing.

**Files:**

- [ ] `app/providers.py` — Remove tool call methods
- [ ] `app/llm_client.py` — Remove tools[] parameter

**Tasks:**

- [ ] 5.1 Remove `parse_tool_calls()` from `AIProvider` base class
  - [ ] Delete method and all overrides

- [ ] 5.2 Remove `tools` parameter handling in providers
  - [ ] `OpenRouterProvider.send_message()` — remove `tools = kwargs.get('tools')`
  - [ ] `ChutesProvider.send_message()` — remove tools from payload
  - [ ] Other providers as needed

- [ ] 5.3 Update `llm_client.py`
  - [ ] Remove `_unique_tool_schemas()`
  - [ ] Remove `tools=schemas` from `_send_to_provider()` calls

- [ ] 5.4 Remove native tool call references in docstrings
  - [ ] Update `AIProvider.send_message()` docstring

- [ ] 5.5 Write regression tests
  - [ ] Verify providers still work without tools parameter
  - [ ] Test with multiple providers (Ollama, OpenRouter, Chutes)

**Verification:**

```bash
python -m pytest tests/test_providers.py -v
ruff check app/providers.py app/llm_client.py
```

**Commit:** `cleanup(providers): Phase 5 - Remove native tool call support`

---

### Phase 6: Prompts — Tool Instructions

**Goal:** Add inline command documentation to system prompt.

**Files:**

- [ ] `app/prompts.py` — Add tool instructions

**Tasks:**

- [ ] 6.1 Add tool instructions section to system prompt
  - [ ] Document each available tool with `/command` syntax
  - [ ] Examples: `/imagine cat`, `/memory_search query`
  - [ ] Format rules: command on its own line

- [ ] 6.2 Add synthesis prompt template
  - [ ] Template for second pass context
  - [ ] Include tool result XML
  - [ ] Instruction to acknowledge naturally

- [ ] 6.3 Remove tools[] array construction
  - [ ] Verify no `get_tool_definitions()` call for LLM context

- [ ] 6.4 Write manual tests
  - [ ] Verify LLM outputs `/command` format
  - [ ] Test with different providers

**Verification:**

```bash
python -c "from app.prompts import build_system_message; print(build_system_message({'display_name': 'Test', 'partner_name': 'Yuzu'}, '')[:500])"
ruff check app/prompts.py
```

**Commit:** `feat(prompts): Phase 6 - Add inline tool instructions`

---

### Phase 7: Frontend — Placeholder Handling

**Goal:** Frontend shows placeholder during tool execution.

**Files:**

- [ ] `static/js/chat.js` — Add placeholder handling
- [ ] `static/css/chat.css` — Placeholder styles

**Tasks:**

- [ ] 7.1 Add placeholder message type
  - [ ] `addMessage("tool_executing", data)` — shows loading state
  - [ ] `updateToolMessage(id, result)` — replaces placeholder with result

- [ ] 7.2 Handle streaming events
  - [ ] Parse `{"type": "tool_executing", ...}` from stream
  - [ ] Show placeholder immediately
  - [ ] Parse `{"type": "tool_result", ...}` from stream
  - [ ] Replace placeholder with result

- [ ] 7.3 Add placeholder styles
  - [ ] `.tool-placeholder.executing` — loading spinner
  - [ ] `.tool-placeholder.success` — checkmark, collapsible details
  - [ ] `.tool-placeholder.error` — error icon, message

- [ ] 7.4 Handle old `<details>` format (backward compat)
  - [ ] Detect `<details>` in message
  - [ ] Render as collapsible block (existing behavior)

- [ ] 7.5 Write manual tests
  - [ ] Test `/imagine` — shows placeholder, then image
  - [ ] Test `/memory_search` — shows placeholder, then results
  - [ ] Test tool error — shows error in placeholder

**Verification:**

```bash
# Manual: Open browser, test tool commands
ruff check static/js/chat.js  # if applicable
```

**Commit:** `feat(frontend): Phase 7 - Placeholder handling`

---

### Phase 8: Cleanup & Migration

**Goal:** Remove old code, update documentation.

**Files:**

- [ ] All files — Final cleanup
- [ ] `docs/roadmap-history/` — Archive roadmap

**Tasks:**

- [ ] 8.1 Remove markdown contract helpers (optional)
  - [ ] Consider keeping for backward compat
  - [ ] Or remove `build_tool_contract()` if sure all old data migrated

- [ ] 8.2 Update `AGENTS.md`
  - [ ] Document new tool execution flow
  - [ ] Update architecture diagram
  - [ ] Add rules for tool development

- [ ] 8.3 Move roadmap to history
  - [ ] `mv UNIVERSAL_INLINE_COMMAND_REFACTOR.md docs/roadmap-history/`

- [ ] 8.4 Final verification
  - [ ] All tests pass
  - [ ] Ruff clean
  - [ ] Manual testing with all providers

- [ ] 8.5 Merge PR
  - [ ] Squash commits or keep separate
  - [ ] Update CHANGELOG.md

**Verification:**

```bash
python -m pytest tests/ -v
ruff check .
git status
```

**Commit:** `docs: Phase 8 - Cleanup and finalize v3.1.0`

---

## Risk Mitigation

### Rollback Points

| Phase | Rollback Command |
|-------|-----------------|
| After Phase 1 | `git revert HEAD` |
| After Phase 2 | `git revert HEAD~2` |
| After Phase 3 | `git revert HEAD~3` |
| After Phase 4+ | Feature flag: `USE_LEGACY_TOOL_PATH=true` |

### Feature Flags (Optional)

```python
# app/config.py
USE_UNIVERSAL_TOOL_PATH = os.getenv("USE_UNIVERSAL_TOOL_PATH", "true").lower() == "true"
```

### Backward Compatibility

| Aspect | Strategy |
|--------|----------|
| Old messages in DB | Dual-path reader handles both formats |
| Frontend | Handles both `<details>` and `<tools>` |
| Tool results | Returns both `markdown` and `xml` fields |

---

## Testing Checklist

### Unit Tests

- [ ] `test_tool_xml_format.py` — XML sanitization, formatting
- [ ] `test_stream_filter.py` — XML detection, placeholder emission
- [ ] `test_orchestrator.py` — Full flow, DB persistence
- [ ] `test_registry.py` — Dual output format

### Integration Tests

- [ ] Test with Ollama provider
- [ ] Test with OpenRouter provider
- [ ] Test with Chutes provider
- [ ] Test with Cerebras provider

### Manual Tests

- [ ] `/imagine cat` — image generation
- [ ] `/memory_search cats` — memory search
- [ ] `/memory_store fact="test"` — memory storage
- [ ] `/request https://example.com` — HTTP request
- [ ] Tool error handling — network timeout, invalid args

---

## Timeline Estimate

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Phase 1 | 1 day | None |
| Phase 2 | 1 day | Phase 1 |
| Phase 3 | 1-2 days | Phase 1 |
| Phase 4 | 2 days | Phase 2, 3 |
| Phase 5 | 0.5 day | Phase 4 |
| Phase 6 | 0.5 day | Phase 4 |
| Phase 7 | 1 day | Phase 4 |
| Phase 8 | 0.5 day | All phases |

**Total:** ~7-9 days

---

## Success Criteria

- [ ] All tests pass
- [ ] Ruff check clean
- [ ] Manual testing with all providers successful
- [ ] No regression in existing functionality
- [ ] Placeholder shown during tool execution
- [ ] Tool results stored as `tools` role
- [ ] Synthesis pass always runs after tool execution
- [ ] Frontend displays tool results correctly

---

## References

- `file 'yuzu-companion/AGENTS.md'` — Project architecture
- `file 'yuzu-companion/app/orchestrator.py'` — Current execution flow
- `file 'yuzu-companion/app/commands.py'` — Current StreamFilter
- `file 'yuzu-companion/app/tools/schemas.py'` — Current tool schema
- `file 'yuzu-companion/app/database/db_queries.py'` — Current tool roles

---

*Document prepared for implementation approval.*
