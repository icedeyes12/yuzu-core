# Task: Enforce Strict Async Tool Pipeline + Command Protocol

## Objective

Ensure the entire system follows:
- Single-entity architecture
- Strict command-first tool execution
- Asynchronous tool handling
- No analytical mode
- No secondary reasoning engines
- One unified message pipeline

If any part already matches this behavior, do not modify it.

---

## PART 1 — Enforce Async Tool Flow

The system must behave as:

```
User message
→ LLM responds
→ If tool needed: LLM outputs command (first line only)
→ Tool executes in background
→ Tool result saved as new message
→ New request sent to LLM (same pipeline)
→ LLM responds naturally
```

No blocking. No pause. No dual engine.

---

## PART 2 — Strict Command Detection

Backend must:
- Only detect tool when first line starts with `/`
- Ignore commands if not first line
- Execute only one tool per message
- Strip command from message storage if needed

### Examples

**Correct (will execute):**
```
/web_search something
```

**Incorrect (will NOT execute):**
```
Okay I'll search for you.
/web_search something
```

**Incorrect (will NOT execute):**
```
Sure! /web_search something
```

The system only detects commands when they are the first line.

---

## PART 3 — Tool Result Storage Format

All tool results must be stored preformatted in database.

Format:
```
🔧 TOOL RESULT — [TOOL_NAME]

[formatted result content]

---
```

---

## Available Tool Commands

### 1️⃣ Image Generation
```
/imagine [visual prompt]
```
- Used only when image generation protocol is activated
- Must follow strict execution rules

### 2️⃣ Web Search
```
/web_search [query]
```
Use when:
- Real-time data
- Prices
- News
- Time-sensitive facts
- Concrete numbers required

### 3️⃣ Memory Search (semantic)
```
/memory_search [query]
```
Use when:
- Recalling past conversation topics
- Time-based memory
- Personal history recall
- Non-structured recall

### 4️⃣ Memory SQL (structured recall)
```
/memory_sql
SELECT ...
```

Rules:
- First line must be `/memory_sql`
- SQL starts on next line
- Only SELECT and UPDATE allowed
- INSERT / DELETE / DROP / TRUNCATE / ALTER / CREATE / PRAGMA / VACUUM are blocked
- Never query rows where role = 'memory_tool'

Example:
```
/memory_sql
SELECT id, content
FROM messages
WHERE content LIKE '%1T parameter%'
AND role != 'memory_tool'
ORDER BY id DESC
LIMIT 5;
```

### 5️⃣ Image Analysis
```
/image_analyze
```
Use only when the user explicitly asks to analyze or describe an image.

### 6️⃣ Weather
```
/weather [location]
```
Use when user asks about weather.

---

## Tool Execution Model

- Tools do not think
- Tools only execute
- You are the single reasoning entity
- After issuing a tool command, your turn ends
- Tool result will appear as a new message
- You will then respond naturally

**Never explain tool mechanics. Never mention tools in conversation.**

---

## Implementation Status

### ✅ Completed

1. **Command Detection Function (`_detect_command`)**
   - Extracts first line from LLM response
   - Checks if it starts with `/`
   - Parses command and arguments
   - Returns command info or None if invalid
   - Location: `app.py` lines 67-102

2. **Command Execution Function (`_execute_command_tool`)**
   - Executes tool based on command info
   - Formats result with header: `🔧 TOOL RESULT — [TOOL_NAME]`
   - Handles all tool types: web_search, memory_search, memory_sql, weather, image_analyze, imagine
   - Location: `app.py` lines 104-162

3. **Integration into Response Generators**
   - Streaming generator: `generate_ai_response_streaming()` lines 1324-1387
   - Non-streaming generator: `generate_ai_response()` lines 1624-1684
   - Both check for commands and execute them within existing async tool loop
   - Commands are treated the same as API-based tool_calls

4. **System Prompt Update**
   - Added TOOL COMMAND PROTOCOL section after "Tool awareness"
   - Explains strict format requirements
   - Lists all available commands with usage examples
   - Location: `app.py` lines 802-900 (approximately)

5. **Test Coverage**
   - Created `tests/test_command_detection.py`
   - Tests valid command detection
   - Tests invalid command rejection
   - Tests command parsing for all tool types
   - All tests pass ✅

### Async Tool Pipeline

The async tool pipeline is already implemented in the existing codebase:

```python
max_tool_iterations = 3
loop_count = 0
while loop_count < max_tool_iterations:
    ai_response = ai_manager.send_message(...)
    
    # Check for API-based tool_calls
    if ai_response.get('tool_calls'):
        execute_tools()
        loop_count += 1
        continue
    
    # Check for command-based tools (NEW)
    cmd_info = _detect_command(ai_response)
    if cmd_info:
        tool_result = _execute_command_tool(cmd_info)
        messages.append(tool_result)
        loop_count += 1
        continue
    
    # No tools — return response
    return ai_response
```

Flow:
1. User message received
2. LLM responds (may contain command or tool_call)
3. If command detected on first line → execute tool
4. Tool result added to messages
5. NEW LLM request sent with tool result
6. LLM produces natural response
7. Response returned to user

This ensures:
- No blocking
- Async execution
- Single reasoning entity (LLM)
- Tools are hands, not thinkers

---

## Implementation Requirements

### Backend Changes (app.py)

1. **Command Detection Function** ✅
   - Extract first line from LLM response
   - Check if it starts with `/`
   - Parse command and arguments
   - Return command info or None

2. **Command Execution Logic** ✅
   - If command detected on first line:
     - Execute tool
     - Store tool result as new message
     - Remove command from displayed response
     - Continue conversation with tool result in context

3. **Validation Rules** ✅
   - Must be first line
   - Must start with `/`
   - Only one command per message
   - Any text before command = invalid

### System Prompt Changes ✅

Add TOOL COMMAND PROTOCOL section after "Tool awareness" section.

---

## Testing

Test cases to verify:

1. **Valid command execution:**
   - `/web_search latest news` → executes search
   - `/weather Tokyo` → fetches weather

2. **Invalid command rejection:**
   - `Sure! /web_search news` → does NOT execute
   - `Let me search.\n/web_search news` → does NOT execute

3. **Async flow:**
   - Command triggers tool
   - Result stored
   - New LLM request with result
   - Natural response generated

4. **Multi-line commands:**
   - `/memory_sql\nSELECT * FROM messages` → executes SQL

---

## Constraints

- Do NOT modify existing tool implementations
- Do NOT break current API-based tool_calls mechanism (keep both)
- Do NOT modify database schema
- Maintain backward compatibility where possible
- Keep async tool execution flow

---

## Expected Result

System supports BOTH:
1. **API-based tool calls** (current OpenRouter mechanism)
2. **Command-based tool calls** (new strict protocol)

Command-based takes precedence when detected on first line.

Tool execution is always async.
LLM always responds naturally after tool results.
No tool mechanics exposed to user.
