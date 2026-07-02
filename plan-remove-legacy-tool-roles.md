# Open questions

- Keep `format_ai_history_rows()` normalization for historical rows only, or remove the legacy-role fallback in the same cleanup pass once write-path canonicalization is done?
- Keep Chutes-only normalization only if canonical OpenAI messages still break that provider, or delete it once the adapter accepts canonical payloads end-to-end?

## Task checklist

- ☑ Phase 1: canonicalize streaming tool-result persistence
- ☑ Phase 2: update prompt image detection to stop depending on legacy tool-role labels
- ☐ Phase 3: deprecate `ToolDefinition.role` as a write-path concept
- ☐ Phase 4: remove legacy role constants/helpers and read-path shims
- ☐ Phase 5: remove Chutes-specific message normalization if canonical payloads are sufficient
- ☑ Verification: run phase-specific tests + repo lint checks

## Phase 1 — Canonicalize streaming tool-result persistence

**Status:** DONE

**Target commit message:** `fix(streaming): persist tool results with role="tool" and tool_call_id`

**Commit:** `TBD`

**Rollback:** `git revert <phase-1-commit>`

**Verification:**

- `python -m pytest tests/test_fc_orchestrator.py tests/test_db_queries.py -q`
- `ruff check .`

**Affected files**

- `file 'app/orchestrator.py'` — persist streaming tool results with provider call IDs via the new helper and keep the legacy fallback only for non-native paths.
- `file 'app/db/models_async.py'` — keep `tool_call_id` / `turn_id` round-trippable in the message insert path.
- `file 'app/db/queries.py'` — preserve canonical `tool` writes and replay metadata in message formatting.
- `file 'tests/test_fc_orchestrator.py'` — assert streaming tool results persist as `role="tool"` with `tool_call_id`.
- `file 'tests/test_db_queries.py'` — assert new writes replay as canonical `tool` messages.

**Checklist**

- ☑ Ensure streaming tool results are persisted with `role="tool"`.
- ☑ Keep `tool_call_id` as the join key between assistant tool calls and tool results.
- ☑ Remove the streaming write-path dependency on `get_tool_role()`.
- ☑ Add regression coverage for canonical persistence.

## Phase 2 — Update prompt image detection

**Status:** DONE

**Target commit message:** `fix(prompts): detect images by image_paths, not legacy tool roles`

**Rollback:** `git revert <phase-2-commit>`

**Verification:**

- `python -m pytest tests/test_prompts_runtime.py -q`
- `ruff check .`

**Affected files**

- `file 'app/prompts.py'` — make image detection content/path-based instead of role-based.
- `file 'tests/test_prompts_runtime.py'` — verify the prompt no longer relies on legacy tool-role labels.

**Checklist**

- ☐ Detect image-bearing tool outputs via `image_paths` and/or `tool_call_id`.
- ☐ Stop relying on `image_tools` / `image_edit` as prompt-time role sentinels.
- ☐ Keep the native-FC prompt text unchanged otherwise.

## Phase 3 — Deprecate `ToolDefinition.role`

**Status:** TODO

**Target commit message:** `refactor(tools): deprecate legacy role labels in tool definitions`

**Rollback:** `git revert <phase-3-commit>`

**Verification:**

- `python -m pytest tests/test_fc_registry.py tests/test_fc_provider.py -q`
- `ruff check .`

**Affected files**

- `file 'app/tools/schemas.py'` — treat `role` as deprecated metadata and stop using it as the user-facing contract header.
- `file 'app/tools/*.py'` — remove explicit dependency on `role="*_tools"` in tool definitions where feasible.
- `file 'app/tools/registry.py'` — keep schema generation canonical without depending on legacy role labels for new runtime behavior.
- `file 'tests/test_fc_registry.py'` — assert schema generation still works after deprecating the role field.

**Checklist**

- ☐ Make `ToolDefinition.role` non-essential to the runtime contract.
- ☐ Stop using legacy role names in any new tool-output construction path.
- ☐ Keep schema generation stable while the field is being phased out.

## Phase 4 — Remove legacy role constants/helpers and read-path shims

**Status:** TODO

**Target commit message:** `chore: remove legacy tool role constants and helpers`

**Rollback:** `git revert <phase-4-commit>`

**Verification:**

- `python -m pytest tests/test_db_queries.py tests/test_fc_orchestrator.py tests/test_fc_registry.py -q`
- `ruff check .`

**Affected files**

- `file 'app/db/queries.py'` — remove `TOOL_ROLES`, `ALL_TOOL_ROLES`, `tool_role_for()`, and the legacy `role in ALL_TOOL_ROLES` branch once the write-path is fully canonical.
- `file 'app/db/__init__.py'` — stop re-exporting dead helper symbols.
- `file 'app/db/models_async.py'` — remove any remaining re-export references to the dead helpers.
- `file 'app/tools/registry.py'` — drop helper functions that only exist to support legacy role mapping.
- `file 'tests/test_db_queries.py'` — rewrite or remove tests that only assert legacy role mapping for new writes; keep historical-row coverage only if needed.

**Checklist**

- ☐ Remove runtime use of legacy role constants and helper lookups.
- ☐ Keep only the minimum historical replay shim required for old rows, if any.
- ☐ Ensure new messages always persist as canonical `tool` rows.

## Phase 5 — Remove Chutes-specific message normalization

**Status:** TODO

**Target commit message:** `refactor(chutes): remove provider-specific message normalization`

**Rollback:** `git revert <phase-5-commit>`

**Verification:**

- `python -m pytest tests/test_fc_provider.py -q`
- `ruff check .`

**Affected files**

- `file 'app/providers/chutes.py'` — delete `_normalize_messages_for_chutes()` if canonical messages already satisfy Chutes; otherwise keep only the minimal adapter-only transformation.
- `file 'tests/test_fc_provider.py'` — verify the Chutes payload stays valid after normalization cleanup.

**Checklist**

- ☐ Compare canonical payloads against Chutes requirements before deleting the adapter shim.
- ☐ Remove any provider-specific normalization that is no longer justified by a real API requirement.
- ☐ Keep only transformations that are technically required by Chutes, not by old write-path assumptions.

## Final verification

- `python -m pytest tests/test_fc_provider.py tests/test_fc_orchestrator.py tests/test_db_queries.py tests/test_prompts_runtime.py tests/test_fc_registry.py -q`
- `ruff check .`
- `ruff format --check .`