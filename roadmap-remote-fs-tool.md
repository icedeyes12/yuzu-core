# Remote Filesystem Tool - Roadmap

## Overview

Tool baru untuk Yuzuki yang memungkinkan akses file di Zo container melalui file server di port 8080. Koneksi via SSH tunnel + Tailscale (private network).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    TAILSCALE NETWORK                        │
│                      (100.x.x.x)                            │
│                                                             │
│  ┌──────────────────┐         ┌──────────────────────────┐ │
│  │   Bani's Termux  │         │    Zo Container          │ │
│  │   (yuzu-companion)│◄───────┤    (File Server :8080)   │ │
│  │                  │  SSH    │                          │ │
│  │  - Yuzuki AI     │ Tunnel  │  - /home/workspace       │ │
│  │  - Tool: fs_*    │         │  - Token auth            │ │
│  └──────────────────┘         └──────────────────────────┘ │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Components

### 1. File Server (Zo Container)

**Location:** `/home/workspace/yuzu-companion/app/tools/remote_fs_server.py`

Standalone FastAPI server that runs on port 8080:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/read` | GET | Read file content |
| `/list` | GET | List directory |
| `/stat` | GET | File metadata (size, mtime, sha256) |
| `/search` | GET | Search file contents |
| `/patch` | POST | Apply patch (safe edit) |
| `/write` | POST | Write new file (restricted) |

**Security:**
- Token auth via `X-Yuzu-Token` header
- Path traversal protection with `os.path.realpath()`
- Separate read/write roots
- Logging for all operations

### 2. Tool Definition (yuzu-companion)

**Location:** `/home/workspace/yuzu-companion/app/tools/fs_remote.py`

Tool yang dipanggil oleh Yuzuki untuk akses file server:

| Tool | Description |
|------|-------------|
| `fs_read` | Read file from remote |
| `fs_list` | List directory |
| `fs_stat` | Get file metadata |
| `fs_search` | Search file contents |
| `fs_patch` | Apply patch to file |
| `fs_write` | Write new file |

### 3. Client Library (Shared)

**Location:** `/home/workspace/yuzu-companion/app/tools/fs_client.py`

Shared client code yang dipake sama server (untuk testing) dan tool.

---

## Implementation Phases

### Phase 1: Core Server (READ-ONLY)

**Goal:** Basic file access dengan token auth

- [ ] Create `remote_fs_server.py` with FastAPI
- [ ] Implement token validation (constant-time compare)
- [ ] Implement `/read` endpoint
- [ ] Implement `/list` endpoint
- [ ] Implement `/stat` endpoint
- [ ] Path traversal protection
- [ ] Request logging

**Deliverable:** Yuzuki bisa baca file dan list directory

### Phase 2: Search & Discovery

**Goal:** File discovery tanpa recursive listing

- [ ] Implement `/search` endpoint dengan ripgrep
- [ ] Line number + preview in results
- [ ] Pagination support

**Deliverable:** Yuzuki bisa search file contents efficiently

### Phase 3: Safe Editing (PATCH)

**Goal:** Edit file tanpa full overwrite

- [ ] Implement `/patch` endpoint
- [ ] Exact match enforcement (0 or >1 = reject)
- [ ] Dry-run mode (`?dry_run=1`)
- [ ] Backup before patch
- [ ] Patch logging with diff

**Deliverable:** Yuzuki bisa edit file dengan aman

### Phase 4: Tool Integration

**Goal:** Tool definition untuk Yuzuki

- [ ] Create `fs_remote.py` tool module
- [ ] Register in `registry.py`
- [ ] Test via chat interface
- [ ] Documentation

**Deliverable:** Yuzuki bisa pake tools langsung dari chat

### Phase 5: Polish & Safety

**Goal:** Production-ready

- [ ] Error handling
- [ ] Rate limiting
- [ ] Health check endpoint
- [ ] Metrics (optional)
- [ ] Integration tests

---

## Security Considerations

### Token Auth

```bash
# Zo container (server)
export YUZU_FS_TOKEN="random-secret-string"

# Termux (client)
export YUZU_FS_TOKEN="random-secret-string"
```

### Path Restriction

```python
# READ access
READ_ROOTS = ["/home/workspace"]

# WRITE access (more restricted)
WRITE_ROOTS = ["/home/workspace/yuzu-companion"]

# Protection
def validate_path(path: str, roots: list[str]) -> str:
    real = os.path.realpath(path)
    for root in roots:
        base = os.path.realpath(root)
        if real.startswith(base + os.sep):
            return real
    raise PermissionError(f"Path outside allowed roots: {path}")
```

### Patch Safety

```python
def apply_patch(content: str, old: str, new: str) -> str:
    # Exact match count
    count = content.count(old)
    if count == 0:
        raise ValueError("Pattern not found")
    if count > 1:
        raise ValueError(f"Pattern found {count} times, must be unique")
    
    # Apply exactly once
    return content.replace(old, new, 1)
```

---

## File Structure

```
yuzu-companion/
├── app/
│   └── tools/
│       ├── fs_remote.py          # Tool definitions for Yuzuki
│       ├── fs_client.py          # Shared client library
│       └── remote_fs_server.py   # Standalone file server
├── scripts/
│   └── start_fs_server.sh        # Server startup script
└── docs/
    └── roadmap-remote-fs-tool.md # This file
```

---

## Success Criteria

1. ✅ Yuzuki bisa baca file di `/home/workspace`
2. ✅ Yuzuki bisa list directory
3. ✅ Yuzuki bisa search file contents
4. ✅ Yuzuki bisa patch file dengan aman
5. ✅ Semua operasi logged
6. ✅ Path traversal protected
7. ✅ Token auth required
8. ✅ Existing tools tetap berfungsi

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Token leaked | Rotate via env var, no git commit |
| Path traversal | `os.path.realpath()` check |
| Race condition | File locking for writes |
| AI hallucination | Exact match for patches, dry-run mode |
| Breaking existing tools | Separate module, lazy registration |

---

## Notes

- File server jalan sebagai **separate process** di Zo container
- Bukan bagian dari yuzu-companion FastAPI (port 5000)
- Tool definition ada di yuzu-companion untuk Yuzuki panggil
- Server start manual dulu, nanti bisa jadi systemd service

---

## Timeline

| Phase | Est. Time | Dependencies |
|-------|-----------|--------------|
| Phase 1 | 2-3 hours | None |
| Phase 2 | 1-2 hours | Phase 1 |
| Phase 3 | 2-3 hours | Phase 1 |
| Phase 4 | 1-2 hours | Phase 1-3 |
| Phase 5 | 2-3 hours | Phase 4 |

**Total:** ~8-13 hours

---

## CLI Usage (yuzu_cli.py)

### Basic Usage

```bash
# Send message to Yuzuki
python3 scripts/yuzu_cli.py --session 37 "your message here"

# Show last N messages
python3 scripts/yuzu_cli.py --session 37 -H 10
```

### Signature & Seal

```bash
# With signature prefix [maintainer]
python3 scripts/yuzu_cli.py --session 37 --sig "maintainer" "message"

# With signature + digital seal (IP, location, timestamp)
python3 scripts/yuzu_cli.py --session 37 --sig "maintainer" --seal "message"
```

**Important:**
- Don't include `[signature]` in the message content if using `--sig` flag (will duplicate)
- `--seal` appends JSON with dynamic IP geolocation at the end

### Format Output

Message format with both flags:
```
[signature] message content {"signature":{"identity":"...","location":"...","ip":"...","timestamp":"...","hash":"..."}}
```

### Timeout Options

```bash
# Custom timeout for GET (history) and POST (send message)
python3 scripts/yuzu_cli.py --session 37 --timeout 30 --post-timeout 120 "message"
```