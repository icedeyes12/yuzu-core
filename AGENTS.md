# Yuzu Companion — Native Function Calling Guide

This is the compact operating guide for the current repository state.

## Architecture in one sentence

Native function calling is the only production tool-execution architecture.
The orchestrator consumes provider tool calls, executes them through `app/tools/registry.py`, persists `ToolEvent`-based results, and does not depend on XML tool invocation at runtime.

## Active production surfaces

- `app/orchestrator.py` — single message-entry pipeline
- `app/llm_client.py` — provider dispatch and streaming
- `app/prompts.py` and `app/prompt.md` — system prompt assembly
- `app/providers.py` — provider capability and tool-call parsing
- `app/tools/registry.py` — canonical tool execution
- `app/tools/schemas.py` — `ToolEvent` / `ToolResultEvent` types
- `app/stream_manager.py` — live stream buffering and persistence
- `app/db/queries.py` — SQL, schema bootstrap, and legacy-result cleanup helpers
- `static/js/renderer.js` and `static/js/chat.js` — streaming UI and ToolEvent rendering

## Legacy surface that may remain

`app/commands.py` is a legacy cleanup utility only. It may strip archived XML-style tool markup from stored content, but it is not a production protocol parser and must not be used as an execution path.

## Hard rules

1. Do not reintroduce XML tool invocation as an active protocol.
2. Do not teach legacy markup as a live tool format in prompts, docs, or UI text.
3. Do not route runtime execution through legacy command dispatch.
4. Keep `ToolEvent` / `ToolResultEvent` as the only production execution contract.
5. Keep SQL in `app/db/queries.py`; do not inline schema drift into business logic.
6. Keep stream ownership in `app/stream_manager.py`; do not add parallel streaming stacks.

## What to update when changing behavior

- Prompt text: `app/prompts.py`, `app/prompt.md`, `docs/prompt.md`
- Architecture docs: `docs/ARCHITECTURE.md`, `docs/BACKEND.md`, `docs/tools.md`, `docs/state-machine.md`
- Frontend rendering: `static/js/renderer.js`
- Legacy cleanup logic: `app/commands.py`, `app/db/queries.py`, `app/stream_manager.py`
- Tests: prefer native FC coverage and cleanup-behavior tests for legacy markup only

## Validation expectations

After changes that touch Python or JS:

- `ruff check .`
- `ruff format --check .`
- `pytest`
- `biome check static/js/`

## Current stance on old protocol terms

References to legacy XML tool markup, parser helpers, execution helpers, and `/command` are only acceptable in:

- historical migration notes
- cleanup utilities that strip old stored output
- tests that verify legacy cleanup behavior

They must not appear as active architecture in production docs or prompts.
