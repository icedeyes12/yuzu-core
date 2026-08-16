# Spec: yuzu-sandboxd

Status: Draft (Active Development)
Target: v4.3
Component: Sandbox Node Runtime

## Overview

`yuzu-sandboxd` is a lightweight execution agent on each sandbox node. It isolates Yuzu Core from privileged or untrusted terminal, Python, file, and package operations.

Yuzu Core never connects directly to a user shell or executes Python on the orchestration host. It communicates with `yuzu-sandboxd` through the transport selected for the phase.

## Responsibilities

- **Lifecycle:** Create, start, stop, reset, and destroy sandboxes.
- **Execution:** Run commands inside a sandbox with explicit timeout and environment semantics.
- **Terminal:** Manage persistent PTY sessions and authorize every `sandbox_id` and `pty_id` operation.
- **State:** Report sandbox status and stream logs back to Yuzu Core.

## Security contract

Tailnet reachability is not authorization. Every request must authenticate the caller as Yuzu Core using a node-specific credential, and the daemon must authorize the requested `sandbox_id` against the authenticated owner and node assignment. SSH uses a dedicated restricted account or forced command; HTTP and WebSocket use authenticated requests with replay-resistant credentials. A PTY identifier is valid only while its owning sandbox and authenticated session are valid.

The owner-to-sandbox binding is established through either (a) a signed delegation claim (a token/claim signed by a trusted authority binding `sandbox_id` to owner and node), or (b) an authenticated server-side mapping that resolves each `sandbox_id` to its authorized owner and node assignment. This binding is required for all lifecycle, execution, and PTY requests. Authorization decisions must use this authenticated binding, never user-controlled request fields such as a client-supplied owner identifier.

The daemon rejects requests for unknown, stopped, or differently owned sandboxes. Credentials are never accepted from `sandbox_id`, workspace paths, or other user-controlled fields, and are not written to command output or logs.

## Execution model

Both transports use the same canonical request model:

```json
{
  "argv": ["python3", "script.py"],
  "shell": false,
  "env": {},
  "timeout_seconds": 30,
  "cwd": "/workspace"
}
```

When `shell` is false: `argv` is required and must be non-empty; `command` must not be set. `argv` is executed without shell expansion. When `shell` is true: `command` (a single string executed via the sandbox shell) is required and must be non-empty; `argv` must not be set. The two fields are mutually exclusive based on the `shell` flag. Environment variables are an explicit map, `cwd` is confined beneath the sandbox workspace, and timeouts are enforced by the daemon. Both Phase 1 CLI (via `--argv-json` or an equivalent `--command` flag for shell mode) and Phase 2 HTTP payloads must validate and enforce this same mutual-exclusivity consistently, rather than defining separate semantics per phase.

### Phase 1: SSH / CLI

```bash
yuzu-sandboxd create <sandbox_id> --json
yuzu-sandboxd exec <sandbox_id> --argv-json '["python3","script.py"]' --timeout 30 --json
yuzu-sandboxd status <sandbox_id> --json
```

CLI output is valid JSON with quoted keys, for example:

```json
{"state":"ready"}
{"exit_code":0,"stdout":"","stderr":""}
```

### Phase 2: HTTP / WebSocket

```http
POST /sandbox/{id}/create
POST /sandbox/{id}/reset
DELETE /sandbox/{id}
GET  /sandbox/{id}/status
POST /sandbox/{id}/exec
WS   /sandbox/{id}/pty/{pty_id}
```

The HTTP `exec` body uses the canonical JSON request above. WebSocket messages carry PTY input/output only after the authenticated session has been authorized for both identifiers.

## Workspace path confinement

For workspace read/write endpoints, reject absolute paths, empty paths, `.` or `..` traversal components, NUL bytes, and paths that resolve outside the sandbox workspace. Join the user path to the configured workspace root, canonicalize it, and verify it remains beneath that root before opening it. Resolve symlinks for existing paths and reject symlink escapes; do not follow an untrusted symlink during creation. Apply this check before every read, write, rename, archive, or delete operation.

This pre-check alone is insufficient due to TOCTOU races. Every filesystem operation must use race-resistant descriptor-relative no-follow APIs (such as `openat2` with `RESOLVE_NO_SYMLINKS` and `RESOLVE_BENEATH`, `O_NOFOLLOW` combined with walking path components via directory file descriptors, or an equivalent platform primitive) to ensure that path components validated during the pre-check cannot be replaced with symlinks before the actual operation executes.

## Node layout

```text
sandboxes/
  template/
  users/<sandbox-id>/
    rootfs/
    workspace/
    home/
    metadata.json
    state.json
```

## Bootstrap and artifact integrity

Bootstrap downloads must use a pinned version from a trusted HTTPS source. Before installation, verify a detached signature or a published SHA-256 checksum obtained through an independently trusted channel. Fail closed on a missing, mismatched, expired, or unexpected artifact; never extract or execute an unverified rootfs or daemon. Record the verified version and digest in node metadata for later audit and rollback.

## Isolation requirements

The backend must declare its guarantees before a node is accepted:

- **PRoot:** filesystem emulation only; not a privilege boundary. Use only for trusted workloads or with an explicit reduced-trust policy, no host-secret mounts, confined paths, restricted network access, and resource/time limits.
- **bwrap:** require a read-only base image, explicit workspace bind mounts, dropped capabilities, a private or explicitly allowed network namespace, no host home or device exposure, and resource limits.
- **chroot:** never treat chroot alone as sufficient isolation. Require a dedicated unprivileged account, dropped capabilities, no device exposure, read-only base image, confined mounts, network restrictions, and an additional kernel-level boundary where untrusted code is allowed.

A node is not `ready` for untrusted execution unless its selected backend satisfies the declared filesystem, privilege, capability, network, and resource controls. If it cannot, the daemon must reject the workload instead of silently weakening the contract.

## Bootstrap flow

1. Install only the pinned daemon and required runtime dependencies after verification.
2. Verify the rootfs artifact before extraction.
3. Register the node using an authenticated request and record its backend capabilities.
4. Create a sandbox lazily on first use.
5. Report heartbeat and readiness only after the security contract passes.

## Related references

- [`../roadmap/v4.3-roadmap.md`](../roadmap/v4.3-roadmap.md)
- [`../architecture/`](../architecture/)
- [`../README.md`](../README.md)
