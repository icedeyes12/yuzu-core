# Yuzu Companion — Termux Tools Roadmap

> **Version:** 1.0.0 · **Created:** 2026-05-15
> **Target Environment:** Termux (Android)
> **Purpose:** Tools untuk akses filesystem, shell execution, Python, dan database di environment Termux via slash commands.

---

## Target Environment Context

```bash
# Termux Environment
Shell: /data/data/com.termux/files/usr/bin/bash
PATH: /data/data/com.termux/files/usr/bin
Home: /data/data/com.termux/files/home
Workspace: ~/workspace (yuzu-companion, icedeyes12)

# Available Tools
psql: 18.2
python: 3.13.13
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     YUZU COMPANION                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ prompts.py   │    │ commands.py  │    │ registry.py  │  │
│  │ (system      │───▶│ (detect      │───▶│ (execute     │  │
│  │  prompt)     │    │  /command)   │    │  tool)       │  │
│  └──────────────┘    └──────────────┘    └──────┬───────┘  │
│                                                  │           │
│  ┌──────────────────────────────────────────────▼───────┐  │
│  │                    TOOLS LAYER                        │  │
│  ├──────────────┬──────────────┬──────────────┬─────────┤  │
│  │ fs_operations│ shell_exec   │ python_exec  │ db_query│  │
│  │ (read/write/ │ (/bash)      │ (/python)    │ (/sql)  │  │
│  │  ls)         │              │              │         │  │
│  └──────────────┴──────────────┴──────────────┴────┬────┘  │
│                                                     │        │
│  ┌──────────────────────────────────────────────────▼────┐ │
│  │              SYNTHESIS PASS (2nd LLM Call)            │ │
│  │  _run_synthesis() / _stream_synthesis()               │ │
│  │  - Consumes tool markdown                             │ │
│  │  - Generates narration around tool result             │ │
│  │  - Can detect nested commands (recursive)             │ │
│  └───────────────────────────────────────────────────────┘ │
│                         │                                  │
│  ┌──────────────────────▼──────────────────────────────┐  │
│  │              TERMUX ENVIRONMENT                      │  │
│  │  - Filesystem (/data/data/com.termux/...)           │  │
│  │  - Shell (bash)                                      │  │
│  │  - Python (3.13)                                     │  │
│  │  - PostgreSQL (psql 18.2)                            │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

---

## Tool Output & Synthesis Integration

### Execution Flow dengan Synthesis

```
1. LLM generates response containing /command
2. detect_command() finds and parses the command
3. execute_tool() runs the tool, returns result dict
4. Tool result → markdown format
5. _persist_tool_result() saves tool markdown to DB
6. SYNTHESIS PASS:
   - LLM called with empty user_message (tool context in history)
   - LLM generates narration/acknowledgment around tool result
   - Nested commands detected → recursive execution
7. Final response = tool markdown + synthesis narration
```

### Tool Output Format untuk Synthesis

Tool **HARUS** return format ini:

```python
{
    "ok": True,                    # Boolean success flag
    "data": { ... },               # Structured result data
    "markdown": "<details>...</details>"  # Human-readable output
}
```

**Kenapa `markdown` field penting untuk synthesis:**

1. **Synthesis consumes markdown** — LLM membaca tool markdown dari chat history
2. **Nested command detection** — `_strip_nested_commands()` mencegah infinite loop
3. **Image tools** — `parse_image_path()` extracts image for visual context
4. **DB persistence** — `_persist_tool_result()` saves markdown as tool role message

### Markdown Formatting Rules

```markdown
<details>
<summary>🔧 Tool: /bash ls -la</summary>

```
total 48
drwxr-xr-x  12 user user 4096 Jan 15 10:00 .
drwxr-xr-x   5 user user 4096 Jan 15 09:30 ..
```

</details>
```

**Struktur:**
- `<details>` block untuk collapsible output
- `<summary>` dengan emoji + tool name + arguments
- Content dalam fenced code block (```)
- Error: `<summary>❌ Tool Error: /bash</summary>`

### Synthesis Behavior

| Tool Type | Synthesis Output |
|-----------|-----------------|
| **Read file** | Narration tentang isi file |
| **Write file** | Konfirmasi file tersimpan |
| **Shell command** | Interpretasi output jika perlu |
| **Python code** | Penjelasan hasil execution |
| **SQL query** | Analysis atau summary data |
| **Error** | Penjelasan error + saran perbaikan |

### Nested Commands di Synthesis

Synthesis bisa generate nested commands (e.g., `/imagine` after `/read` image):

```python
def _run_synthesis(...):
    # ...
    nested = detect_command(cleaned)
    if nested:
        log.info("executing nested command: /%s", nested["command"])
        tool_name, nested_result = execute_command(nested, session_id)
        # Recursive handling
```

**Supported nested prefixes:** `/request`, `/imagine`

---

## Tool Specifications

### 1. File System Operations (`fs_operations.py`)

| Command | Description | Example |
|---------|-------------|---------|
| `/read <path>` | Baca file di Termux | `/read ~/workspace/config.json` |
| `/write <path> <content>` | Tulis file (single line) | `/write ~/test.txt hello world` |
| `/write <path> <<EOF` | Tulis file via heredoc | `/write ~/test.txt <<EOF\nline1\nline2\nEOF` |
| `/ls [path]` | List direktori | `/ls ~/workspace` |
| `/mkdir <path>` | Buat direktori | `/mkdir ~/projects/new` |
| `/rm <path>` | Hapus file/direktori | `/rm ~/old_file.txt` |

**Return Format:**
```python
{
    "ok": True,
    "data": {
        "path": "/absolute/path",
        "content": "file content",
        "size": 1024
    },
    "markdown": "<details><summary>📄 File: path</summary>\n\ncontent\n</details>"
}
```

---

### 2. Shell Execution (`shell_exec.py`)

| Command | Description | Example |
|---------|-------------|---------|
| `/bash <command>` | Eksekusi shell command | `/bash ls -la ~/workspace` |
| `/bash <<EOF` | Multi-line script via heredoc | `/bash <<EOF\ncd ~/workspace\npwd\nEOF` |

**Security:**
- Timeout: 30 detik
- Output limit: 10KB
- Blocklist: `rm -rf /`, `mkfs`, `dd if=/dev/zero`, `:(){ :|:& };:`
- Whitelist approach untuk dangerous operations

**Return Format:**
```python
{
    "ok": True,
    "data": {
        "command": "ls -la",
        "exit_code": 0,
        "stdout": "total 48\ndrwxr-xr-x...",
        "stderr": "",
        "duration_ms": 42
    },
    "markdown": "<details><summary>🔧 Shell: ls -la</summary>\n\n```\noutput\n```\n</details>"
}
```

---

### 3. Python Execution (`python_exec.py`)

| Command | Description | Example |
|---------|-------------|---------|
| `/python <code>` | Single-line Python | `/python print(2+2)` |
| `/python ```python` | Multi-line code block | `/python ```python\nimport os\nprint(os.getcwd())\n``` ` |

**Security:**
- Timeout: 60 detik
- Output limit: 50KB
- Sandbox: No file write without explicit path validation
- Restricted imports: `os.system`, `subprocess.Popen` (require explicit allow)

**Return Format:**
```python
{
    "ok": True,
    "data": {
        "code": "print(2+2)",
        "output": "4\n",
        "error": "",
        "duration_ms": 15
    },
    "markdown": "<details><summary>🐍 Python Output</summary>\n\n```\n4\n```\n</details>"
}
```

---

### 4. Database Query (`db_query.py`)

| Command | Description | Example |
|---------|-------------|---------|
| `/sql <query>` | Single-line SQL | `/sql SELECT * FROM profiles LIMIT 5` |
| `/sql ```sql` | Multi-line SQL | `/sql ```sql\nSELECT p.name,\nCOUNT(*) as count\nFROM profiles p\n...;\n``` ` |
| `/sql --write <query>` | Allow INSERT/UPDATE | `/sql --write INSERT INTO logs VALUES (...)` |

**Security:**
- Default: READ-ONLY mode
- `--write` flag required for INSERT/UPDATE/DELETE
- Transaction wrapper untuk write operations
- Connection from env: `PG_HOST`, `PG_PORT`, `PG_DBNAME`, `PG_USER`, `PG_PASSWORD`

**Return Format:**
```python
{
    "ok": True,
    "data": {
        "query": "SELECT * FROM profiles LIMIT 5",
        "rows": [...],
        "row_count": 5,
        "columns": ["id", "name", "created_at"],
        "duration_ms": 12
    },
    "markdown": "<details><summary>📊 SQL Result (5 rows)</summary>\n\n| id | name | created_at |\n|---|---|---|\n| 1 | test | 2026-01-01 |\n</details>"
}
```

---

## Roadmap

### PHASE 1: Foundation — File System Tools

- [x] **Task 1.1: Buat `app/tools/fs_operations.py`**
  - [x] Sub-task 1.1.1: Implement `TOOL_DEFINITION` untuk `/read`, `/write`, `/ls`, `/mkdir`, `/rm`
  - [x] Sub-task 1.1.2: Implement `execute()` dengan path validation (prevent traversal)
  - [x] Sub-task 1.1.3: Handle errors dengan `error_result()`
  - [x] Sub-task 1.1.4: Return structured result dengan `ok_result()`
  - [x] Sub-task 1.1.5: Support heredoc untuk `/write` (pending Phase 5)

- [x] **Task 1.2: Register di `app/tools/registry.py`**
  - [x] Sub-task 1.2.1: Tambah import `fs_operations` di `_collect_definitions()`
  - [x] Sub-task 1.2.2: Tambah import di `_load_tool_module()`

- [x] **Task 1.3: Register di `app/commands.py`**
  - [x] Sub-task 1.3.1: Tambah entry di `_STRING_ARG_TOOLS`: `"read"`, `"ls"`, `"mkdir"`, `"rm"`
  - [x] Sub-task 1.3.2: Special handling untuk `/write` di `_parse_args()`

- [x] **Task 1.4: Update system prompt di `app/prompts.py`**
  - [x] Sub-task 1.4.1: Tambah dokumentasi tools di section "AVAILABLE TOOLS & EXECUTION"

- [ ] **Task 1.5: Validasi**
  - [x] Sub-task 1.5.1: `ruff check app/tools/fs_operations.py` ✓
  - [x] Sub-task 1.5.2: `python3 -m py_compile app/tools/fs_operations.py` ✓
  - [ ] Sub-task 1.5.3: Test manual via CLI: `/read`, `/write`, `/ls`

---

### PHASE 2: Shell Execution Tool

- [ ] **Task 2.1: Buat `app/tools/shell_exec.py`**
  - [ ] Sub-task 2.1.1: Implement `TOOL_DEFINITION` untuk `/bash`
  - [ ] Sub-task 2.1.2: Implement `execute()` dengan `subprocess.run()`
  - [ ] Sub-task 2.1.3: Timeout protection (max 30s)
  - [ ] Sub-task 2.1.4: Output truncation (max 10KB)
  - [ ] Sub-task 2.1.5: Security: implement blocklist untuk dangerous commands
  - [ ] Sub-task 2.1.6: Support heredoc untuk multi-line scripts

- [ ] **Task 2.2: Register di `registry.py` dan `commands.py`**
  - [ ] Sub-task 2.2.1: Tambah import di `_collect_definitions()` dan `_load_tool_module()`
  - [ ] Sub-task 2.2.2: Tambah `"bash"` di `_STRING_ARG_TOOLS`

- [ ] **Task 2.3: Update system prompt**
  - [ ] Sub-task 2.3.1: Tambah dokumentasi `/bash` dengan contoh

- [ ] **Task 2.4: Validasi**
  - [ ] Sub-task 2.4.1: `ruff check app/tools/shell_exec.py`
  - [ ] Sub-task 2.4.2: `python3 -m py_compile app/tools/shell_exec.py`
  - [ ] Sub-task 2.4.3: Test manual: `/bash ls -la`, `/bash pwd`

---

### PHASE 3: Python Execution Tool

- [ ] **Task 3.1: Buat `app/tools/python_exec.py`**
  - [ ] Sub-task 3.1.1: Implement `TOOL_DEFINITION` untuk `/python`
  - [ ] Sub-task 3.1.2: Implement `execute()` dengan `subprocess.run()` ke `python -c`
  - [ ] Sub-task 3.1.3: Support multi-line code blocks (```python ... ```)
  - [ ] Sub-task 3.1.4: Timeout protection (max 60s)
  - [ ] Sub-task 3.1.5: Output capture (stdout + stderr)
  - [ ] Sub-task 3.1.6: Security: restricted imports check

- [ ] **Task 3.2: Register di `registry.py` dan `commands.py`**
  - [ ] Sub-task 3.2.1: Tambah import di `_collect_definitions()` dan `_load_tool_module()`
  - [ ] Sub-task 3.2.2: Tambah `"python"` di `_STRING_ARG_TOOLS`

- [ ] **Task 3.3: Update system prompt**
  - [ ] Sub-task 3.3.1: Tambah dokumentasi `/python` dengan contoh

- [ ] **Task 3.4: Validasi**
  - [ ] Sub-task 3.4.1: `ruff check app/tools/python_exec.py`
  - [ ] Sub-task 3.4.2: `python3 -m py_compile app/tools/python_exec.py`
  - [ ] Sub-task 3.4.3: Test manual: `/python print('hello')`, `/python 2+2`

---

### PHASE 4: Database Query Tool

- [ ] **Task 4.1: Buat `app/tools/db_query.py`**
  - [ ] Sub-task 4.1.1: Implement `TOOL_DEFINITION` untuk `/sql`
  - [ ] Sub-task 4.1.2: Implement `execute()` dengan `psql` subprocess
  - [ ] Sub-task 4.1.3: Support multi-line SQL queries (```sql ... ```)
  - [ ] Sub-task 4.1.4: Format output sebagai markdown table
  - [ ] Sub-task 4.1.5: Security: READ-ONLY mode by default
  - [ ] Sub-task 4.1.6: Implement `--write` flag for INSERT/UPDATE
  - [ ] Sub-task 4.1.7: Read DB connection from environment variables

- [ ] **Task 4.2: Register di `registry.py` dan `commands.py`**
  - [ ] Sub-task 4.2.1: Tambah import di `_collect_definitions()` dan `_load_tool_module()`
  - [ ] Sub-task 4.2.2: Tambah `"sql"` di `_STRING_ARG_TOOLS`

- [ ] **Task 4.3: Update system prompt**
  - [ ] Sub-task 4.3.1: Tambah dokumentasi `/sql` dengan contoh dan security notes

- [ ] **Task 4.4: Validasi**
  - [ ] Sub-task 4.4.1: `ruff check app/tools/db_query.py`
  - [ ] Sub-task 4.4.2: `python3 -m py_compile app/tools/db_query.py`
  - [ ] Sub-task 4.4.3: Test manual: `/sql SELECT 1`, `/sql SELECT * FROM profiles LIMIT 1`

---

### PHASE 5: Heredoc & Multi-line Support

- [ ] **Task 5.1: Extend command parser untuk heredoc**
  - [ ] Sub-task 5.1.1: Parse heredoc syntax di `_parse_args()` atau new helper function
  - [ ] Sub-task 5.1.2: Support format: `/write path <<EOF\ncontent\nEOF`
  - [ ] Sub-task 5.1.3: Support code block format: `/python ```python\ncode\n``` `
  - [ ] Sub-task 5.1.4: Support SQL block format: `/sql ```sql\nquery\n``` `

- [ ] **Task 5.2: Update tools untuk handle multi-line input**
  - [ ] Sub-task 5.2.1: `fs_operations.write` handle heredoc content
  - [ ] Sub-task 5.2.2: `python_exec` handle code block input
  - [ ] Sub-task 5.2.3: `db_query` handle multi-line SQL
  - [ ] Sub-task 5.2.4: `shell_exec` handle multi-line scripts

- [ ] **Task 5.3: Update system prompt**
  - [ ] Sub-task 5.3.1: Dokumentasikan heredoc syntax untuk setiap tool

- [ ] **Task 5.4: Validasi**
  - [ ] Sub-task 5.4.1: Test heredoc parsing dengan berbagai format
  - [ ] Sub-task 5.4.2: Test multi-line code blocks
  - [ ] Sub-task 5.4.3: Test edge cases (empty content, special chars)

---

### PHASE 6: Testing & Documentation

- [ ] **Task 6.1: Unit tests**
  - [ ] Sub-task 6.1.1: Buat `tests/test_fs_operations.py`
  - [ ] Sub-task 6.1.2: Buat `tests/test_shell_exec.py`
  - [ ] Sub-task 6.1.3: Buat `tests/test_python_exec.py`
  - [ ] Sub-task 6.1.4: Buat `tests/test_db_query.py`

- [ ] **Task 6.2: Integration tests**
  - [ ] Sub-task 6.2.1: Test end-to-end via chat interface (non-streaming)
  - [ ] Sub-task 6.2.2: Test end-to-end via streaming mode
  - [ ] Sub-task 6.2.3: Test batch tool execution

- [ ] **Task 6.3: Update documentation**
  - [ ] Sub-task 6.3.1: Update `AGENTS.md` dengan tool baru di section Tool System Rules
  - [ ] Sub-task 6.3.2: Update `README.md` dengan daftar tools
  - [ ] Sub-task 6.3.3: Tambah contoh penggunaan di `TOOLS_ROADMAP.md`

- [ ] **Task 6.4: Final validation**
  - [ ] Sub-task 6.4.1: `ruff check .` — must pass
  - [ ] Sub-task 6.4.2: `python3 -m py_compile app/tools/*.py` — must pass
  - [ ] Sub-task 6.4.3: `python3 -m pytest tests/ -v` — all tests pass
  - [ ] Sub-task 6.4.4: Manual smoke test via CLI

---

## Implementation Notes

### Security Considerations

1. **Path Traversal Prevention**
   - Normalize paths dengan `os.path.normpath()`
   - Reject paths containing `..` atau starting with `/` (unless explicitly allowed)
   - Define allowed base directories

2. **Command Injection Prevention**
   - Use `subprocess.run()` dengan `shell=False` when possible
   - Escape user input properly when shell is required
   - Implement blocklist untuk dangerous commands

3. **Database Safety**
   - Default to READ-ONLY mode
   - Require explicit `--write` flag for mutations
   - Use parameterized queries when building SQL dynamically

4. **Resource Limits**
   - Timeout untuk semua subprocess calls
   - Output truncation untuk prevent memory issues
   - Maximum file size untuk read operations

### Coding Standards

```python
# File header template
# FILE: app/tools/<tool_name>.py
# DESCRIPTION: <short description>
#              <additional context if needed>

from __future__ import annotations

# ... imports ...

from app.logging_config import get_logger
from app.tools.schemas import ToolDefinition, error_result, ok_result

log = get_logger(__name__)

TOOL_DEFINITION: dict[str, ToolDefinition] = {
    "tool_name": {
        "name": "tool_name",
        "description": "Short description",
        "parameters": {
            "param_name": {
                "type": "string",
                "description": "Parameter description",
                "required": True,
            }
        },
    }
}

def execute(arguments: dict, session_id: int | None = None) -> dict:
    """Execute the tool and return result dict."""
    # Implementation
    pass
```

### Testing Template

```python
# tests/test_<tool_name>.py

from __future__ import annotations

from app.tools.<tool_name> import execute, TOOL_DEFINITION


def test_tool_definition_exists():
    assert "tool_name" in TOOL_DEFINITION


def test_execute_success():
    result = execute({"param": "value"})
    assert result["ok"] is True
    assert "markdown" in result


def test_execute_error():
    result = execute({"param": "invalid"})
    assert result["ok"] is False
    assert "error" in result
```

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-05-15 | 1.0.0 | Initial roadmap creation |

---

## References

- `app/tools/registry.py` — Tool dispatch mechanism
- `app/tools/schemas.py` — Tool definition schema
- `app/commands.py` — Command detection and parsing
- `app/prompts.py` — System prompt with tool documentation
- `AGENTS.md` — Architecture constraints and rules
