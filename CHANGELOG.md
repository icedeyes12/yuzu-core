# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [4.0.0] - 2025-06-10

### Major Architectural Shift

**Thin-Client Architecture**: Complete separation between backend (FastAPI) and frontend (Textual TUI). The CLI never touches the database — all communication via HTTP/SSE.

### Added

- **Persistent TUI Client** (`cli/`)
  - Textual-based terminal interface with real-time chat streaming
  - Session sidebar with history navigation
  - Scrollable chat log with Markdown rendering
  - Input box with message submission (`Enter` key)
  - Responsive layout: horizontal split (sidebar + chat area)

- **HTTP Client** (`cli/client.py`)
  - Async HTTP client using `httpx`
  - Health check endpoint
  - SSE streaming for responses
  - Session management endpoints

- **FastAPI Lifespan Management** (`main.py`)
  - Explicit DB pool initialization on startup
  - Graceful shutdown with pool cleanup
  - Health check integration

- **Standard Packaging** (`pyproject.toml`)
  - `setuptools` build backend
  - Entry points: `yuzu` (TUI), `yuzu-server` (backend)
  - Proper dependency management
  - Author metadata: `icedeyes12 <banibaskara@gmail.com>`

- **Styling** (`cli/styles/app.tcss`)
  - Minimalist UI with dark theme
  - Session sidebar (30% width) with subtle borders
  - Input box docked at bottom with top border
  - Professional color scheme

### Changed

- **`web.py` → `main.py`**: Renamed to reflect role as system backbone
- **Legacy CLI Removed**: Deleted broken stateless CLI (`main.py.legacy`)
- **Architecture**: From monolithic CLI to thin-client HTTP architecture
- **Import Structure**: Clean separation — no `sys.path` hacks

### Removed

- **Legacy Stateless CLI**: Old command-line interface with direct DB imports
- **ANN Lint Ignores**: Adopted strict linting with test fixture exemptions
- **`sys.path.insert`**: Replaced with proper package installation

### Developer Experience

- `pip install -e .` for editable install
- `yuzu` command launches TUI
- `yuzu-server` starts backend
- No manual PYTHONPATH configuration needed

---

## [3.2.0] - 2026-05-22

### Added

- Memory pipeline improvements
- FSRS decay for semantic facts
- PCL (Predict-Calibrate-Learning) integration

### Changed

- Streaming orchestration refactor
- Tool execution cleanup

---

## [3.1.0] - 2026-04-15

### Added

- Tool protocol v2: `<tool>...</tool>` blocks
- Streaming message persistence
- Background buffer management

### Removed

- Legacy `/command` syntax

---

## [3.0.0] - 2026-03-01

### Changed

- Flask → FastAPI migration
- Async database operations
- SSE streaming implementation

---

## [2.0.0] - 2025-12-15

### Added

- PostgreSQL + pgvector for semantic memory
- Multi-provider LLM support (Ollama, Cerebras, OpenRouter, Chutes)
- Image generation tools

---

## [1.0.0] - 2025-06-01

### Added

- Initial release
- Basic AI companion functionality
- Web interface
- Memory system
