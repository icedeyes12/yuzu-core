# Roadmap: Command Detection Refactor

> **Version:** 2.0 · **Created:** 2026-05-13
> **Status:** Planning — awaiting approval

---

## Problem Statement

LLM kadang ignore instruksi system prompt yang bilang:

> "Respond with `/imagine [detailed prompt]` as the VERY FIRST line of your response. Do NOT reply with 'Sure!' or 'Let me...' — just the command."

Hasilnya, LLM ngomong dulu baru kirim `/imagine` di baris berikutnya:

```markdown
"Manja banget sih hari ini... tapi aku suka. Kali ini aku kasih pose yang lebih santai ya, biar kamu makin betah liatin aku." 🤍

/imagine Yuzuki Aihara, a young woman, soft brown eyes, ....
```

Saat ini:

- `detect_command()` **hanya cek first line**
- `StreamFilter` **hanya cek first line**
- Command gak ke-detect → tool gak ke-execute
- **Hanya support 1 command per response**

---

## Constraints (HARD)

1. **NO new functions** — Extend/fix existing `detect_command()` and `StreamFilter`
2. **NO new files** — Edit in-place
3. **NO blind patching** — Every change must be traced to a specific behavioral requirement
4. **Naked commands only** — `/imagine` inside:
   - Fenced code blocks (` ``` `)
   - Inline code (`` ` ``)
   - Blockquotes (`>`)
   
   ...must NOT trigger execution

5. **Single source of truth** — Command detection logic harus centralized, bukan duplikasi
6. **Batch execution** — Multiple commands must be executed in batch, not first-wins

---

## Current Architecture

### `file app/commands.py`

```markdown
detect_command(text) → dict | None
├── Split by newline → first line only
├── Check if starts with "/"
└── Parse command + args
```

### `StreamFilter` class

```markdown
feed(chunk):
├── Buffer chunks until newline
├── Check if first non-whitespace char is "/"
├── If "/" → wait for newline, parse command, suppress first line
└── If not "/" → flush buffer, pass through all subsequent chunks
```

### `file app/orchestrator.py`

Two entry points:

1. `handle_user_message()` — Non-streaming, calls `detect_command(text_response)`
2. `handle_user_message_streaming()` — Streaming, uses `StreamFilter` + fallback `detect_command()`

Current flow:
```
LLM Response → Detect 1 command → Execute → Synthesis
```

---

## Proposed Architecture (Batch)

### New Flow

```
LLM Response → Detect ALL commands → Execute ALL in batch → Collect ALL results → 2nd pass Synthesis
```

### Phase 1: Extend `detect_command()` → Support multiple commands

**File:** `file app/commands.py`

```python
def detect_command(
    response_text: str | None,
    scan_mode: str = "first_line",  # "first_line" | "any_naked" | "all_naked"
) -> dict[str, str] | list[dict[str, str]] | None:
```

**Behavior:**

- `scan_mode="first_line"` (default) → Existing behavior, returns `dict | None`
- `scan_mode="any_naked"` → Returns first naked command as `dict | None`
- `scan_mode="all_naked"` → Returns LIST of all naked commands as `list[dict] | None`

**Return type:**
- Single command mode → `dict | None`
- Batch mode → `list[dict] | None` (empty list = `None`)

**"Naked" definition:**

- Line starts with `/` (after stripping leading whitespace)
- Line is NOT inside:
  - Fenced code block (between ` ``` ` lines)
  - Inline code (between backticks on same line)
  - Blockquote (line starting with `>`)

**Implementation approach:**

1. Parse text line-by-line
2. Track state: `in_fenced_block`, `in_blockquote`
3. For each line, check if it's "exposed" (not in any protected context)
4. If exposed line starts with `/`, parse and collect
5. Return based on `scan_mode`:
   - `"first_line"` → first line check only (backward compatible)
   - `"any_naked"` → first match as dict
   - `"all_naked"` → all matches as list

---

### Phase 2: Add batch execution support

**File:** `file app/commands.py`

Extend existing `execute_command()` logic to support batch:

```python
def execute_commands_batch(
    commands: list[dict[str, str]],
    profile: dict[str, Any],
    session_id: int,
) -> list[dict[str, Any]]:
    """
    Execute multiple commands in batch.
    Returns list of results, one per command.
    """
    results = []
    for cmd in commands:
        result = execute_command(cmd, profile, session_id)
        results.append({
            "command": cmd,
            "result": result,
        })
    return results
```

**Alternative:** Modify `execute_command()` to accept `list | dict`:

```python
def execute_command(
    command_info: dict[str, str] | list[dict[str, str]] | None,
    profile: dict[str, Any],
    session_id: int,
) -> dict[str, Any] | list[dict[str, Any]] | None:
    if isinstance(command_info, list):
        return execute_commands_batch(command_info, profile, session_id)
    # ... existing single-command logic
```

---

### Phase 3: Update `StreamFilter` → Support batch detection

**File:** `file app/commands.py`

```python
class StreamFilter:
    # ... existing ...
    
    def get_commands(self, scan_mode: str = "first_line") -> dict | list[dict] | None:
        """Return detected command(s), with optional full-text scan."""
        if self.command and scan_mode == "first_line":
            return self.command
        if scan_mode in ("any_naked", "all_naked") and self.full_text:
            return detect_command(self.full_text, scan_mode=scan_mode)
        return None
```

---

### Phase 4: Update orchestrator → 2-pass synthesis

**File:** `file app/orchestrator.py`

#### Non-streaming path (`handle_user_message`)

```python
# Pass 1: Detect ALL commands
commands = detect_command(text_response, scan_mode="all_naked")

if commands:
    # Execute ALL in batch
    tool_results = execute_command(commands, profile, session_id)  # returns list
    
    # Build tool markdown from all results
    tool_markdowns = []
    for result in tool_results:
        tool_markdowns.append(result["markdown"])
    
    combined_tool_markdown = "\n\n".join(tool_markdowns)
    
    # Pass 2: Single synthesis with all results
    synthesis = _run_synthesis(profile, session_id, interface, combined_tool_markdown)
    
    # Final response: all tool results + synthesis
    final_response = f"{combined_tool_markdown}\n\n{synthesis}"
```

#### Streaming path (`handle_user_message_streaming`)

More complex — need to handle streaming narration first, then batch execute, then synthesis.

```python
# Stream LLM response
for chunk in llm_stream:
    # ... yield chunks to user ...
    full_response += chunk

# Post-stream: detect ALL commands
commands = sf.get_commands(scan_mode="all_naked")

if commands:
    # Execute ALL in batch
    for result in execute_command(commands, profile, session_id):
        yield f"\n\n{result['markdown']}"
    
    # Then synthesis (if needed)
```

---

## Edge Cases

### Case 1: Multiple `/command` in same response

```markdown
/imagine a cat

/imagine a dog
```

**Decision:** ALL detected and executed in batch.

**Order:** Sequential execution (preserve text order).

**Synthesis:** Single synthesis pass after ALL tools complete.

### Case 2: Mixed text + multiple commands

```markdown
Here are two images for you:

/imagine a sunset

/imagine a beach
```

**Decision:** Both commands executed. Text before commands sudah ke-stream/yield.

### Case 3: Same command multiple times

```markdown
/imagine cat
/imagine cat
```

**Decision:** Both executed (no deduplication). Let tools handle idempotency.

### Case 4: Command inside markdown structure

```markdown
Here's what I can do:

- Generate images with `/imagine`
- Fetch URLs with `/request`
```

**Decision:** NOT detected (inside list item, not naked).

### Case 5: Fenced code block with command inside

````markdown
```python
command = "/imagine test"
```
````

**Decision:** NOT detected.

### Case 6: Inline code with command

```markdown
Type `/imagine` to generate images
```

**Decision:** NOT detected.

### Case 7: Blockquote with command

```markdown
> The user said: /imagine a cat
```

**Decision:** NOT detected.

---

## Implementation Checklist

### Phase 1: `detect_command()` extension

- [ ] Add `scan_mode` parameter: `"first_line"` | `"any_naked"` | `"all_naked"`
- [ ] Implement line-by-line parser dengan state tracking
- [ ] Track: `in_fenced_block`, `in_blockquote`
- [ ] Per-line inline-code detection
- [ ] Return `list[dict]` for `"all_naked"` mode
- [ ] Maintain backward compatibility (`"first_line"` returns `dict | None`)

### Phase 2: Batch execution

- [ ] Extend `execute_command()` to accept `list | dict`
- [ ] Implement batch execution logic
- [ ] Return `list[dict]` for batch mode
- [ ] Error handling: continue on single command failure

### Phase 3: `StreamFilter` extension

- [ ] Add `get_commands(scan_mode)` method
- [ ] Support `"all_naked"` mode
- [ ] Delegate to `detect_command()` (no logic duplication)

### Phase 4: orchestrator integration

- [ ] Update `handle_user_message()` → use `scan_mode="all_naked"`
- [ ] Implement batch execution + 2-pass synthesis
- [ ] Update `handle_user_message_streaming()` → post-stream batch detection
- [ ] Handle streaming edge cases (narration before commands)

### Phase 5: Validation

- [ ] Run `ruff check app/`
- [ ] Run `python3 -m py_compile app/commands.py app/orchestrator.py`
- [ ] Unit tests for batch detection
- [ ] Unit tests for batch execution
- [ ] Manual test dengan MiniMax provider
- [ ] Git commit dengan co-author

---

## Rollback Plan

Jika refactor causes regression:

```bash
git restore app/commands.py app/orchestrator.py
```

Semua perubahan dalam 2 file saja, mudah di-rollback.

---

## Design Decisions (FINAL)

1. **Max batch size: 3 commands per response**
   - Prevent DoS / accidental spam
   - Commands beyond 3rd are ignored
   - Log warning when truncated

2. **Execution: Sequential**
   - Preserve text order dari LLM response
   - Predictable result order
   - Simpler error handling

3. **Synthesis: Single synthesis**
   - One synthesis pass setelah semua tools selesai
   - All tool results sebagai context untuk synthesis
   - Jangan per-command synthesis (terlalu verbose)

---

## Approval

Sebelum eksekusi, user harus approve:

- [ ] Batch execution approach (execute all, not first-wins)
- [ ] 2-pass synthesis (all results → single synthesis)
- [ ] Edge case decisions
- [ ] Max batch size: 3
- [ ] Execution order: sequential

---

*This roadmap is the contract for the refactor. No deviation without explicit user approval.*