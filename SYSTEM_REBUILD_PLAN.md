# System Rebuild Plan — Yuzu Companion TUI

> **Author:** Lead Architect  
> **Date:** 2026-06-10  
> **Target Version:** 4.0.0

---

## 1. Executive Summary

This document outlines the architecture and implementation plan for a **thin-client Terminal User Interface (TUI)** for Yuzu Companion. The system follows a strict separation of concerns:

- **Backend**: FastAPI server (`main.py`) — handles all database operations, LLM orchestration, and memory pipeline
- **Frontend**: Textual TUI client (`cli/`) — communicates exclusively via HTTP, never touches the database

---

## 2. Architecture Overview

### 2.1 System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         TERMINAL                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                     TEXTUAL TUI (cli/)                   │   │
│  │  ┌────────────────┐  ┌─────────────────────────────┐    │   │
│  │  │ SESSION LIST   │  │ CHAT LOG (Scrollable)       │    │   │
│  │  │ (Sidebar)      │  │ ┌─────────────────────────┐│    │   │
│  │  │                │  │ │ Yuzuki: Hi! How can I    ││    │   │
│  │  │ • default      │  │ │ help?                    ││    │   │
│  │  │ • work         │  │ │ You: What's the weather? ││    │   │
│  │  │ • project-x    │  │ │ Yuzuki: [streams...]    ││    │   │
│  │  │                │  │ └─────────────────────────┘│    │   │
│  │  └────────────────┘  └─────────────────────────────┘    │   │
│  │                       ┌─────────────────────────────┐    │   │
│  │                       │ INPUT BOX                   │    │   │
│  │                       │ > Type your message...    _ │    │   │
│  │                       └─────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP/SSE (httpx)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI Backend (main.py)                    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ API Routes (/api/*)                                      │   │
│  │  • POST /api/send_message_stream (SSE)                   │   │
│  │  • GET  /api/history                                     │   │
│  │  • GET  /api/sessions                                   │   │
│  │  • POST /api/session/create                             │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Orchestrator + Memory Pipeline + LLM Providers           │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ PostgreSQL + pgvector                                    │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Core Principles

| Principle | Enforcement |
|-----------|-------------|
| **Thin-Client** | CLI never imports `app.db.*`, `app.memory.*`, or `app.orchestrator` |
| **HTTP-Only Communication** | All data flows through FastAPI endpoints via `httpx` |
| **Separation of Concerns** | Backend owns state; TUI is a view/controller |
| **Standard Packaging** | `pyproject.toml` with `pip install -e .` — no `sys.path` hacks |
| **Default Linting** | No custom `ANN` rules — rely on existing ruff config that passes |

---

## 3. TUI Framework: Textual

### 3.1 Why Textual?

| Requirement | Textual Fit |
|-------------|-------------|
| Persistent full-screen TUI | ✅ Built for this paradigm |
| Async event loop | ✅ Native `asyncio` support |
| Real-time streaming updates | ✅ Widget updates without blocking |
| Layout system | ✅ CSS-like styling, flex containers |
| Input handling with history | ✅ `Input` widget with custom Message events |
| Markdown rendering | ✅ Rich integration for formatted responses |

### 3.2 Stack

```
cli.py (entry point)
├── textual.app.App
├── textual.widgets (Input, Static, ListView, etc.)
├── rich.markdown (Markdown rendering in widgets)
├── httpx.AsyncClient (HTTP communication)
└── asyncio (async event loop, native to Textual)
```

---

## 4. Directory Structure

```
yuzu-companion/
├── main.py                      # System backbone (FastAPI + lifespan)
├── cli.py                       # TUI entry point (launches YuzuTUI)
├── pyproject.toml               # Standard packaging
├── app/
│   ├── api/
│   │   ├── main.py             # Router registry
│   │   └── endpoints/
│   │       ├── chat.py
│   │       ├── sessions.py
│   │       └── stream.py
│   ├── db/
│   ├── memory/
│   ├── tools/
│   └── ...
├── cli/                         # TUI modules (NEW)
│   ├── __init__.py
│   ├── app.py                   # Main Textual App class
│   ├── client.py                # HTTP client wrapper (httpx)
│   ├── widgets/                 # Custom widgets
│   │   ├── __init__.py
│   │   ├── chat_log.py          # Scrollable chat history
│   │   ├── input_box.py         # User input with history
│   │   ├── session_list.py      # Session sidebar
│   │   └── status_bar.py        # Connection status footer
│   ├── screens/                 # Screen definitions
│   │   ├── __init__.py
│   │   └── chat_screen.py      # Main chat screen
│   ├── styles/                  # Textual CSS
│   │   └── app.tcss
│   └── utils/
│       ├── __init__.py
│       └── formatting.py        # Message formatting helpers
├── tests/
│   └── test_cli/                # CLI tests (NEW)
│       ├── __init__.py
│       ├── test_client.py
│       └── test_widgets.py
└── requirements.txt             # Add textual>=0.47.0, httpx>=0.27.0
```

---

## 5. Module Responsibilities

### 5.1 `cli.py` (Entry Point)

Launch function that instantiates and runs the Textual app. Entry point for `pyproject.toml` script.

### 5.2 `cli/app.py` (Main App)

- Define `YuzuTUI(App)` class
- Compose layout: Header, Container (ChatLog + SessionList), InputBox, Footer
- Handle Message events from InputBox
- Manage backend connection state
- Bind keys: `Ctrl+C` (quit), `Ctrl+N` (new session), `Ctrl+H` (history)

### 5.3 `cli/client.py` (HTTP Client)

- Async HTTP client wrapper using `httpx.AsyncClient`
- Methods:
  - `check_health()` — GET `/api/health` (or similar)
  - `send_message(session_id, message)` — POST `/api/chat` (sync)
  - `stream_message(session_id, message)` — POST `/api/send_message_stream` (SSE)
  - `get_history(session_id, limit)` — GET `/api/history`
  - `list_sessions()` — GET `/api/sessions`
- Error handling: connection refused, timeouts, HTTP errors

### 5.4 `cli/widgets/chat_log.py`

- Extend `ScrollableContainer`
- Auto-scroll to bottom on new messages
- Markdown rendering for AI responses (via `RichLog` or `Static` with Rich)
- Visual distinction: user messages vs AI responses

### 5.5 `cli/widgets/input_box.py`

- Extend `Input` widget
- Emit custom `MessageSubmitted` event on Enter
- Clear input after submission
- Optional: input history buffer (up/down arrows)

### 5.6 `cli/widgets/session_list.py`

- Extend `OptionList` or `ListView`
- Display available sessions
- Click to switch session
- Visual indicator for active session

---

## 6. Packaging Configuration

### 6.1 `pyproject.toml` (Minimal)

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "yuzu-companion"
version = "4.0.0"
description = "AI companion system with memory, multimodal, and multi-provider support"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.12"
authors = [
    {name = "icedeyes12", email = "banibaskara@gmail.com"}
]
dependencies = [
    # Core (from requirements.txt)
    "psycopg[binary,pool]>=3.1",
    "pycryptodome>=3.20.0",
    "python-dotenv>=1.0.0",
    "fsrs>=6.3.1",
    # Web Framework
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.8.0",
    "python-multipart>=0.0.9",
    "Jinja2>=3.1.0",
    # Terminal UI
    "rich>=13.0.0",
    "prompt-toolkit>=3.0.0",
    "textual>=0.47.0",
    # Networking
    "requests>=2.33.0",
    "httpx>=0.27.0",
]

[project.scripts]
yuzu = "cli.app:run_app"
yuzu-server = "main:app"

[tool.setuptools.packages.find]
where = ["."]
include = ["app*", "cli*"]
exclude = ["tests*", "scripts*"]
```

### 6.2 Install Command

```bash
pip install -e .
```

This makes `yuzu` command available globally, launching the TUI.

---

## 7. Implementation Phases

### Phase 1: Packaging Setup

**Goal:** Create `pyproject.toml` and verify editable install.

**Steps:**
1. Create `pyproject.toml` with minimal configuration
2. Add `textual>=0.47.0` and `httpx>=0.27.0` to dependencies
3. Run `pip install -e .`
4. Verify `yuzu` and `yuzu-server` entry points are registered

**Deliverable:** Working `pyproject.toml`, editable install succeeds.

---

### Phase 2: Scaffold `cli/` Directory

**Goal:** Create directory structure with `__init__.py` files.

**Steps:**
1. Create directories:
   - `cli/widgets/`
   - `cli/screens/`
   - `cli/styles/`
   - `cli/utils/`
   - `tests/test_cli/`
2. Create `__init__.py` in each directory
3. Commit scaffold

**Deliverable:** Empty `cli/` structure ready for implementation.

---

### Phase 3: Implement `cli/client.py`

**Goal:** Async HTTP client for backend communication.

**Steps:**
1. Implement `BackendClient` class with async context manager
2. Implement methods:
   - `check_health()`
   - `send_message(session_id, message)`
   - `stream_message(session_id, message)` (async generator)
   - `get_history(session_id, limit)`
   - `list_sessions()`
3. Add error handling for network failures
4. Write basic tests in `tests/test_cli/test_client.py`
5. Run lint: `ruff check cli/client.py` (must pass)
6. Commit

**Deliverable:** Tested HTTP client, lint passes.

---

### Phase 4: Implement `cli/app.py` (Base TUI)

**Goal:** Foundational Textual App with empty layout.

**Steps:**
1. Implement `YuzuTUI(App)` class
2. Compose basic layout: Header, Footer, empty Container
3. Add keybindings: `Ctrl+C` (quit)
4. Test launch: `python3 cli.py`
5. Run lint
6. Commit

**Deliverable:** TUI launches with Header/Footer, can be closed with Ctrl+C.

---

### Phase 5: Implement `cli/widgets/chat_log.py`

**Goal:** Scrollable chat history widget.

**Steps:**
1. Implement `ChatLog` widget extending `ScrollableContainer`
2. Add methods:
   - `add_message(role, content)` — append message, auto-scroll
   - `clear()` — clear history
3. Use Rich `Markdown` for rendering AI responses
4. Test in isolation (simple test script)
5. Run lint
6. Commit

**Deliverable:** Working `ChatLog` widget.

---

### Phase 6: Implement `cli/widgets/input_box.py`

**Goal:** Input widget with message submission.

**Steps:**
1. Implement `InputBox` widget extending `Input`
2. Define custom `MessageSubmitted` message
3. On Enter key, emit message, clear input
4. Test in isolation
5. Run lint
6. Commit

**Deliverable:** Working `InputBox` with event emission.

---

### Phase 7: Implement `cli/widgets/session_list.py`

**Goal:** Session sidebar widget.

**Steps:**
1. Implement `SessionList` widget extending `OptionList`
2. Add method: `update_sessions(sessions_list)`
3. Highlight active session
4. Emit `SessionSelected` message on click
5. Run lint
6. Commit

**Deliverable:** Working `SessionList` widget.

---

### Phase 8: Integrate Widgets into `cli/app.py`

**Goal:** Complete TUI layout.

**Steps:**
1. Update `compose()` to include:
   - Header
   - Container with `ChatLog` and `SessionList`
   - `InputBox`
   - Footer
2. Handle `MessageSubmitted` → call `BackendClient.send_message()`
3. Update `ChatLog` with response
4. Handle `SessionSelected` → switch active session
5. Test end-to-end: send message, see response
6. Run lint
7. Commit

**Deliverable:** Working chat TUI with session sidebar.

---

### Phase 9: Implement Streaming

**Goal:** Real-time streaming responses via SSE.

**Steps:**
1. Use `BackendClient.stream_message()` for async generator
2. Update `ChatLog` incrementally as chunks arrive
3. Handle connection errors gracefully
4. Test streaming with real backend
5. Run lint
6. Commit

**Deliverable:** Streaming responses in TUI.

---

### Phase 10: Polish & Testing

**Goal:** Final polish, tests, and documentation.

**Steps:**
1. Add CSS styling in `cli/styles/app.tcss`
2. Write comprehensive tests in `tests/test_cli/`
3. Update `AGENTS.md` with CLI architecture and usage
4. Update `README.md` with quick start for TUI
5. Run full test suite: `pytest tests/ -v`
6. Run lint: `ruff check .`
7. Commit and push

**Deliverable:** Production-ready TUI, documented.

---

### Phase 11: Merge & Release

**Goal:** Merge `dev` to `master` and tag v4.0.0.

**Steps:**
1. Create PR: `dev` → `master`
2. Review and merge
3. Tag release: `git tag v4.0.0`
4. Push: `git push origin master --tags`

**Deliverable:** Released v4.0.0.

---

## 8. Separation of Concerns (Critical)

### 8.1 What CLI CAN Import

- `textual.*`
- `rich.*`
- `httpx`
- `asyncio`
- `pydantic` (for models if needed)
- `app.logging_config` (logging only)

### 8.2 What CLI MUST NEVER Import

- `app.db.*`
- `app.memory.*`
- `app.orchestrator`
- `app.tools.*`
- `psycopg` or `pgvector`

### 8.3 Communication Contract

| Direction | Method | Data Format |
|-----------|--------|--------------|
| CLI → Backend | `POST /api/send_message_stream` | `{session_id, message}` |
| Backend → CLI | SSE stream | `data: {"content": "..."}` |
| CLI → Backend | `GET /api/history` | Query params |
| Backend → CLI | JSON response | `{messages: [...]}` |

---

## 9. Success Criteria

| Criteria | Verification |
|----------|-------------|
| Lint passes | `ruff check .` exits 0 |
| Tests pass | `pytest tests/ -v` passes |
| TUI launches | `yuzu` command opens full-screen TUI |
| Backend communication | Sending message shows response in TUI |
| Streaming works | SSE responses appear incrementally |
| Sessions switchable | Sidebar allows session selection |
| Clean shutdown | Ctrl+C exits gracefully, no orphan processes |

---

## 10. Rollback Strategy

If any phase fails:

1. `git reset --hard HEAD` to clean working directory
2. Revert to last successful commit: `git reset --hard <commit-sha>`
3. Identify issue, fix, and proceed to next phase

---

*End of System Rebuild Plan*
