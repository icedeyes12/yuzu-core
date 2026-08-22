# File and execution boundaries

## Verified current state

- `app/services/conversation_service.py` wrote uploads to `static/uploads`.
- `app/tools/image_generate.py` and `image_edit.py` wrote generated files to `static/generated_images`.
- `app/api/static.py` authenticated requests but authorized only by filename, not owner.
- `app/tools/registry.py` exposed local `terminal`, Python, SQL, and filesystem execution.
- `shell_exec.py` used `create_subprocess_shell` in the production process.
- titit-3 is Android 5.15, native Termux control plane, Debian PRoot workloads.
- Durable `/data/user/0` filesystem had 220,195,224 KiB available and 12,633,634 free inodes during audit.
- `prlimit`, `timeout`, and `setsid` exist. Bubblewrap, firejail, Docker, and Podman were absent.
- PRoot is not a hostile-code security boundary. `yuzu-sandbox` phase one permits controlled allowlisted executables only.

## Storage

Production setting:

```text
YUZU_STORAGE_ROOT=/root/home/yuzu-data
YUZU_SANDBOX_ROOT=/root/home/yuzu-sandbox-workspaces
```

Persistent layout:

```text
users/<owner UUID>/<uploads|attachments|generated|artifacts|exports>/<object UUID>
```

`file_objects` is canonical metadata. Each reservation locks the owning `profiles` row, sums pending and ready bytes, then inserts a pending row in one transaction. Limit: 536870912 bytes. No preallocation. Failed writes remove pending metadata. A later reconciliation command must compare ready rows and physical objects before destructive cleanup.

Sandbox workspaces are separate. Initial implementation has structured `argv`, timeout, output cap, clean environment, process-group kill, regular-file manifests. It has no hard filesystem or network isolation on this host. Do not run arbitrary hostile code.

## Rollout

1. Apply schema and set `YUZU_STORAGE_ROOT` on staging.
2. Keep `YUZU_USER_EXECUTION_ENABLED=false`.
3. Run legacy inventory. Migrate only owner-known files.
4. Register the example sandbox manifest without public routing.
5. Add SandboxManager dispatch and artifact import after review.
6. Remove legacy static private-image routes after verified cutover.

No production deployment or migration was performed by this change.