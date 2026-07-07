# Open questions

- Do we remove the legacy replay shims for pre-existing `<tools>` rows in the same cleanup pass, or keep them read-only until the data is no longer needed?
- Do tool modules keep a presentation-only `summary` field for UI display, or do we render structured `data` directly everywhere?

## Task checklist

- ☐ Phase 1: replace the markdown tool contract with structured tool results
- ☐ Phase 2: remove `ToolDefinition.role` and legacy role maps/helpers
- ☐ Phase 3: delete legacy cleanup-only parsers and compatibility shims
- ☐ Verification: run phase-specific tests + repo lint checks

## Phase 1 — Replace the markdown tool contract with structured tool results

**Status:** TODO

**Target commit message:** `refactor(tools): remove markdown tool contract from runtime`

**Rollback:** `git revert <phase-1-commit>`

**Verification:**

- `python -m pytest tests/test_fc_orchestrator.py tests/test_prompts_runtime.py -q`
- `ruff check .`

**Affected files**

- `app/tools/schemas.py` — replace `build_tool_contract()`/`ok_result()`/`error_result()` output with structured tool-result data; keep `ToolCallEvent`/`ToolResultEvent`.
- `app/tools/registry.py` — dispatch tools into structured results only; stop manufacturing `<tools>` wrapper strings.
- `app/tools/*.py` — update tool executors to return structured result payloads instead of markdown contracts.
- `app/orchestrator.py` — persist and forward structured tool results directly; stop depending on contract-shaped output.
- `app/prompts.py` and `app/prompt.md` — remove `<tools>` guidance from system prompt text.
- `static/js/renderer.js` — remove `<tools>` parsing and the tool-contract pre-parser.
- `static/js/modules/messages.js` — render canonical tool rows/events instead of legacy `*_tools` message roles.
- `static/css/marked.css` and `static/css/components/messages.css` — remove styles that only exist for the markdown tool contract.
- `tests/test_fc_orchestrator.py` and `tests/test_prompts_runtime.py` — assert native structured tool results and prompt text no longer mention the contract.

**Checklist**

- ☐ Remove `<tools>` generation from tool result helpers.
- ☐ Stop parsing `<tools>` in the browser renderer.
- ☐ Keep tool result presentation separate from runtime execution data.
- ☐ Update prompt text so the model is not taught the retired contract.

## Phase 2 — Remove `ToolDefinition.role` and legacy role maps/helpers

**Status:** TODO

**Target commit message:** `refactor(tools): remove legacy role labels from tool definitions`

**Rollback:** `git revert <phase-2-commit>`

**Verification:**

- `python -m pytest tests/test_db_queries.py tests/test_fc_provider.py -q`
- `ruff check .`

**Affected files**

- `app/tools/schemas.py` — drop `ToolDefinition.role` as a runtime concept; keep only canonical tool name/description/parameters.
- `app/tools/*.py` — remove `role="*_tools"` from tool definitions and result builders.
- `app/db/queries.py` — remove `TOOL_ROLES`, `ALL_TOOL_ROLES`, `tool_role_for()`, and the legacy role fallback branch for new writes.
- `app/db/__init__.py` and `app/db/models_async.py` — stop re-exporting dead role helpers.
- `app/orchestrator.py` — stop using `get_tool_role()` on any path.
- `tests/test_db_queries.py` — rewrite assertions around canonical `tool` rows and remove legacy role-mapping expectations.

**Checklist**

- ☐ Make tool schema generation independent of storage-role labels.
- ☐ Persist new tool results only as canonical `role="tool"` rows.
- ☐ Remove helper APIs that exist only to translate tool names into legacy role strings.
- ☐ Keep `tool_call_id` / `turn_id` as the only write-path linkage.

## Phase 3 — Delete legacy cleanup-only parsers and compatibility shims

**Status:** TODO

**Target commit message:** `chore: remove legacy tool contract cleanup shims`

**Rollback:** `git revert <phase-3-commit>`

**Verification:**

- `python -m pytest tests/test_fc_orchestrator.py tests/test_db_queries.py tests/test_fc_registry.py -q`
- `ruff check .`

**Affected files**

- `app/db/queries.py` — delete `extract_command_from_markdown_contract()` and `extract_raw_result_from_markdown_contract()` once nothing consumes legacy tool-contract text.
- `app/db/__init__.py` — stop exporting the cleanup-only parsers.
- `app/prompts.py` — remove any remaining text that teaches legacy command or tool-contract syntax.
- `app/providers/chutes.py` — remove provider-specific message normalization if canonical OpenAI-style payloads are sufficient.
- `static/js/renderer.js` and `static/js/modules/messages.js` — remove any remaining fallback logic for old tool-contract history rows.
- `tests/test_db_queries.py` — rewrite/remove tests that only assert legacy cleanup behavior; keep only tests for canonical native-FC rows.
- `app/README.md` and related docs — remove references to legacy role labels, `<tools>` contracts, and cleanup-only parsing as runtime behavior.

**Checklist**

- ☐ Delete cleanup-only parsers that are no longer part of runtime behavior.
- ☐ Remove provider-specific normalization that is not technically required.
- ☐ Rewrite docs/tests so the repo only teaches canonical native function calling.
- ☐ Keep the final codebase on structured tool events end-to-end.
