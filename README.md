# [PROJECT: HKKM - Yuzu Companion]

---

## What Even Is This?

Honestly, what are you looking for here? This is just another AI project. 

You know what's more interesting? Mending scroll **[Fesnuk](https://www.facebook.com/groups/programmerhandal/)**. Or maybe some cat videos on YouTube.

Seriously, go scroll some social media. This code isn't going to entertain you like that latest meme trend.

---

## No Really, What Does It Do?

It's an AI companion. It talks. It remembers things. Sometimes it generates images. 

But let's be real - you're probably just here because you're bored. Might as well go watch some TikTok.

---

## Architecture (v4.0.0)

**Thin-Client Architecture:**
```
┌─────────────────────┐
│  Textual TUI        │  ← Persistent terminal UI (cli/app.py)
│  (yuzu)             │     HTTP/SSE only, no DB access
└─────────┬───────────┘
          │ HTTP/SSE
          ▼
┌─────────────────────┐
│  FastAPI Backend    │  ← System backbone (main.py)
│  (yuzu-server)      │     DB, memory, tools, LLM
└─────────────────────┘
```

**Separation of Concerns:**
- **Backend**: FastAPI server handles DB, memory pipeline, LLM providers, tool execution
- **TUI Client**: Textual-based terminal interface communicates via HTTP only
- **No direct DB access from CLI** — all backend communication through REST/SSE

---

## Installation

If you insist on actually installing this, go read [INSTALL.md](INSTALL.md) for instructions.

But honestly, just ask ChatGPT. It will explain it better.

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -e .
```

Or manually:
```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file in the project root:

```env
# PostgreSQL (required)
PGHOST=localhost
PGPORT=5432
PGDATABASE=yuzu
PGUSER=postgres
PGPASSWORD=your_password

# LLM Provider (optional)
AI_PROVIDER=ollama
AI_MODEL=yuzuki
```

### 3. Start the Backend

```bash
# Option A: Using the entry point
yuzu-server

# Option B: Direct uvicorn
uvicorn main:app --host 0.0.0.0 --port 5000 --reload
```

Backend runs at `http://localhost:5000` by default.

### 4. Launch the TUI

```bash
# Option A: Using the entry point
yuzu

# Option B: Direct module
python -m cli.app
```

The TUI connects to the backend at `http://localhost:5000` by default. Override with:
```bash
yuzu --backend-url http://your-server:5000
```

---

## Usage

### Starting a Chat Session

1. **Launch backend**: `yuzu-server`
2. **Launch TUI**: `yuzu`
3. **Type message**: Use the input box at the bottom, press `Enter` to send
4. **Switch sessions**: Click a session in the sidebar or use `Tab` to navigate

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+C` | Quit |
| `Tab` | Focus next widget |
| `Shift+Tab` | Focus previous widget |
| `Enter` | Send message (when input focused) |
| `↑` / `↓` | Scroll chat history / navigate sessions |

### Session Management

- **New session**: Automatically created on first message
- **Switch session**: Click sidebar item or navigate with arrows
- **Session history**: Load previous conversations from PostgreSQL

---

## For the 3 People Actually Reading This

If you're still here, congratulations on your attention span. This is an intimate AI companion system with:

- Emotional bonding protocols
- Multimodal interaction (text + images)
- Session-based memory with pgvector semantic search
- Encrypted API keys (ChaCha20-Poly1305)
- Persistent TUI with real-time streaming
- Thin-client architecture (FastAPI + Textual)

But honestly, you could have just asked ChatGPT to explain it.

---

## Project Structure

```
yuzu-companion/
├── main.py              # FastAPI backend (system backbone)
├── cli/
│   ├── app.py           # TUI application entry point
│   ├── client.py        # HTTP client
│   ├── widgets/
│   │   ├── chat_log.py      # Scrollable message history
│   │   ├── input_box.py     # User input widget
│   │   └── session_list.py  # Session sidebar
│   └── styles/
│       └── app.tcss         # TUI styling
├── app/
│   ├── api/             # FastAPI routes
│   ├── db/              # PostgreSQL connection pool
│   ├── memory/          # Memory pipeline
│   └── tools/           # Tool execution
└── pyproject.toml       # Packaging config
```

---

## Disclaimer

All code is AI-generated. The developer just pressed some buttons and prayed.

Now go away and do something more productive. Like scrolling through memes.

---

## Author

### Project Lead
- [Bani Baskara](https://github.com/icedeyes12/)

### Team
- [DeepSeek](https://www.deepseek.com/)
- [GPT](https://chatgpt.com/)
- [Claude](https://www.anthropic.com/)
- [Moonshot ai](https://www.moonshot.cn/)
- [Qwen](https://github.com/QwenLM/Qwen3-Coder)
- [GitHub Copilot](https://github.com/features/copilot)
- [KiloCode](https://kilocode.ai/)
- [Aihara](https://github.com/icedeyes12/yuzu-companion)

---

©2025-2026 [HKKM project](https://github.com/icedeyes12/yuzu-companion) | Built with love 💕
