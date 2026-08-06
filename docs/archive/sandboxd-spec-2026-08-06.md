# Spec: yuzu-sandboxd

Status: Draft (Active Development)
Target: v4.3
Component: Sandbox Node Runtime

## Overview

`yuzu-sandboxd` is a lightweight, dedicated execution agent that runs on every
sandbox node (e.g., worker phones, VPS, mini-PCs). It isolates the orchestrator
(Yuzu Core) from privileged, untrusted execution (terminal, Python, files).

Yuzu Core NEVER connects to a user shell or executes Python directly. It talks
to `yuzu-sandboxd`.

## Responsibilities

- **Lifecycle:** Create, start, stop, reset, and destroy sandboxes (PRoot/chroot instances).
- **Execution:** Run one-off commands (Python, bash, git) inside the sandbox.
- **Terminal:** Manage persistent PTY sessions for interactive shells.
- **State:** Report sandbox status and stream logs back to Yuzu Core.

## Execution Model: Phase 1 (SSH / CLI)

To prioritize stability and easy debugging, Phase 1 uses SSH over Tailnet.
Yuzu Core invokes `yuzu-sandboxd` via SSH commands. The CLI outputs JSON.

```bash
# General CLI syntax
yuzu-sandboxd <command> [args] --json

# 1. Lifecycle
yuzu-sandboxd create <sandbox_id>    # provisions rootfs from template
yuzu-sandboxd destroy <sandbox_id>   # deletes rootfs and workspace
yuzu-sandboxd reset <sandbox_id>     # destroys + creates fresh
yuzu-sandboxd status <sandbox_id>    # returns { state: "running|stopped|ready" }

# 2. Execution (Stateless)
yuzu-sandboxd exec <sandbox_id> --cmd "python3 script.py"
# -> returns { exit_code, stdout, stderr }

# 3. Terminal PTY (Stateful / Interactive)
yuzu-sandboxd pty open <sandbox_id> <pty_id>
yuzu-sandboxd pty write <sandbox_id> <pty_id> --data "ls\n"
yuzu-sandboxd pty read <sandbox_id> <pty_id>
yuzu-sandboxd pty close <sandbox_id> <pty_id>
```

## Execution Model: Phase 2 (HTTP / WebSocket)

Once stable, the transport shifts to a persistent HTTP/WS server running
on the node, bound to the Tailscale IP. SSH overhead is eliminated.

```http
POST /sandbox/{id}/create
POST /sandbox/{id}/reset
DELETE /sandbox/{id}
GET  /sandbox/{id}/status

POST /sandbox/{id}/exec
{ "command": ["python3", "script.py"], "env": {...}, "timeout": 30 }

# WebSocket for Terminal (direct binary/text frames)
WS /sandbox/{id}/pty/{pty_id}
```

## Architecture on Node

```
/data/data/com.termux/files/home (or equivalent)
  |-- yuzu-sandboxd         (the binary/script)
  |-- sandboxes/
        |-- template/       (minimal debian rootfs)
        |-- users/
              |-- <sandbox_id>/
                    |-- rootfs/       (PRoot root filesystem)
                    |-- workspace/    (User files, mounted into rootfs)
                    |-- home/         (User home, mounted into rootfs)
                    |-- metadata.json (State, owner, creation time)
```

## Bootstrap Flow

When a new node comes online, a bootstrap script does:
1. Installs minimal dependencies (`python3`, `curl`, `proot`).
2. Downloads the `template/` rootfs tarball.
3. Downloads the `yuzu-sandboxd` executable.
4. (Phase 2) Registers itself via heartbeat to Yuzu Core's API.

## Implementation Details

- **Language:** Python (simple deployment) or Go/Rust (zero-dependency binary).
- **Isolation:** PRoot is used on Android Termux nodes. On full Linux (VPS), `bwrap` or chroot may be used, abstracting the difference behind the sandboxd interface.
- **Data transfer:** Instead of SFTP, Phase 1 can use `cat` or `base64` over SSH; Phase 2 will use `GET/PUT /sandbox/{id}/workspace/{path}`.
