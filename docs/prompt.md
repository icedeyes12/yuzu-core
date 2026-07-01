# Prompt Guide

This document describes the current native function calling prompt contract.

## Core rule

Native function calling is the only production tool protocol.

- Tool execution comes from provider `tool_calls`
- The runtime dispatches tools through `app/tools/registry.py`
- Tool results are represented with `ToolEvent` / `ToolResultEvent`
- Legacy XML-style tool markup is cleanup text only and must not be taught as an active protocol

## Tool execution guidance

When writing or updating prompts:

1. Describe tools by their canonical names and schemas.
2. Refer to native function calling, not XML tags or command blocks.
3. Never instruct the model to emit legacy tool tags or XML markup.
4. Keep any legacy cleanup references clearly labeled as historical or archival.

## Current prompt surfaces

- `app/prompts.py`
- `app/prompt.md`
- `docs/prompt.md`

These files should stay aligned with the native function calling architecture.

## Minimal example language

Use wording like this:

- "Use native function calling to invoke the tool."
- "The runtime will dispatch tool calls from the provided schemas."
- "Produce plain assistant text; the system will manage tool execution."

## Avoid

- XML tool examples
- `/command` syntax
- legacy cleanup examples
- fallback language that implies a second execution protocol
