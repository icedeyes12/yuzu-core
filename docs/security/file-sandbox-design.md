# Controlled execution and user-file security

Status: foundation implemented; service inactive and not user-facing.

## Boundary

`yuzu-sandbox` is the service/domain name. `SandboxRunner` is a single-node controlled process runner. It is not a hostile-code sandbox. `SandboxManager` is the Core-side authority that creates `sandbox_jobs`, derives ownership, dispatches execution, imports artifacts, finalizes state, and cleans workspaces. Node registry, heartbeat, SSH, PTY, and distributed scheduling are deferred.

Canonical flow:

```text
authenticated owner -> sandbox_jobs -> SandboxManager -> localhost HTTP runner
-> bounded ephemeral workspace -> artifact manifest -> FileService
-> owner-scoped file_objects -> /api/v1/files/{fil_id}
```

`sandbox_jobs.id -> owner_id` is authoritative. `owner_id` in a runner request is derived metadata only. Artifact ownership is resolved again from the job row before persistence.

## Storage

Production configuration targets:

```text
YUZU_STORAGE_ROOT=/root/home/yuzu-data
YUZU_SANDBOX_ROOT=/root/home/yuzu-sandbox-workspaces
YUZU_STORAGE_RESERVE_BYTES=<operator-selected reserve>
YUZU_SANDBOX_RESERVE_BYTES=<operator-selected reserve>
```

Audit evidence: `/root/home` and `/tmp` resolve to `/dev/block/dm-61`; 20,130,296 KiB and 5,032,574 inodes were free during the latest check. Reserve defaults to `0` until the operator selects a value from current disk policy; no speculative threshold is hardcoded.

Persistent layout:

```text
users/<owner UUID>/<uploads|attachments|generated|artifacts|exports>/<object UUID>
```

`file_objects` is canonical metadata. Persistent quota is 536,870,912 bytes per owner. Reservations lock the profile row and count pending plus ready objects. Uploads, generated images, image edits, HTTP-downloaded images, and imported sandbox artifacts use `FileService`.

## Controlled-runner limits

- argv-only execution; no shell string contract;
- exact executable allowlist;
- clean environment allowlist;
- default 30-second timeout;
- default 256 MiB workspace allowance;
- bounded stdout and stderr capture; crossing either cap kills the process group;
- regular-file artifacts only, with count and per-file limits;
- process-group kill on timeout/cancellation;
- workspace cleanup is idempotent after every manager terminal path;
- low-disk reserve checked before persistent writes and job start.

Workspace allowance is enforced by periodic size measurement. Android/PRoot provides no reliable per-directory filesystem quota or cgroup boundary here. A process can overshoot between polls. This is acceptable only for controlled workloads. PRoot is not accepted for hostile arbitrary code.

Path validation uses relative-path, realpath containment, symlink, and regular-file checks. Descriptor-relative no-follow primitives remain mandatory for a future hostile-workload backend; phase-one retains documented TOCTOU residual risk.

## Lifecycle

Job states: `pending`, `running`, `succeeded`, `failed`, `cancelled`, `timed_out`. Terminal workspaces are removed after artifact import or failure. `SandboxManager.reap()` removes only workspaces selected from terminal DB rows older than retention. Cleanup is idempotent.

File deletion is owner-scoped: mark metadata deleted, then remove the physical object. Quota is released at logical deletion; reconciliation reports a deleted-row/file mismatch if physical removal failed. Existing legacy files with unknown ownership remain quarantine candidates, never automatic public compatibility data.

## Deployment state

`deploy/yuzu-sandbox.service.example.json` is preparation only. It binds localhost, uses authenticated requests, stdio logs, and `on-failure` restart semantics. It is not registered or started by this change. Direct user execution remains disabled by default.

No production deployment, schema execution, asset migration, Cloudflare, DNS, Wrangler, or public port change was performed.
