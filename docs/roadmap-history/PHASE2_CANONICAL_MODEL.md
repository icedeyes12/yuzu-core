# Canonical Message Model Design (Phase 2)

## 1. Current State Inventory
The current architecture lacks a canonical definition of a "message". State is represented differently at every layer, requiring continuous translation and patching.

**Representations in use:**
1. **DB Row (`parse_message_row`):** Dictionary with `id`, `session_id`, `role`, `content`, `image_paths`, `tool_calls`, `tool_call_id`, `turn_id`, `timestamp`.
   *Owner:* `app/db/queries.py`
2. **Provider Payload:** Dictionaries conforming loosely to OpenAI spec (`role`, `content`, `tool_calls`, `tool_call_id`). Images are patched in as base64 URLs at runtime.
   *Owner:* `app/prompts.py:build_messages()`
3. **API Request (`MessageRequest`):** Pydantic model (`message`, `interface`, `session_id`, `image_paths`, `provider`, `model`).
   *Owner:* `app/api/endpoints/chat.py`
4. **Tool Events:** `ToolCallEvent` (id, name, args, turn_id) and `ToolResultEvent` (call_id, name, ok, data, error, turn_id).
   *Owner:* `app/tools/schemas.py`
5. **SSE Envelope (`StreamToolEvent`):** Union mapping to JSON (`{"type": "token"|"tool_call"|"tool_result"|"done", "data": ...}`).
   *Owner:* `app/tools/schemas.py`
6. **Frontend State:** Ad-hoc DOM element properties + `window.chatHistory` objects populated asynchronously.

**Core Mismatches:**
- A single "assistant turn" is currently split across three distinct states (the text, the tool call, the tool result).
- Images are a loosely attached array (`image_paths`) rather than proper attachments belonging strictly to a specific event.

## 2. The Canonical Model Proposal

We propose modeling conversation as an ordered sequence of immutable `ConversationEvent` objects. We avoid accumulating 30 optional properties on a single God object by using composition.

### 2.1 The Event Hierarchy

```python
from pydantic import BaseModel, Field
from typing import Literal, Any

class Attachment(BaseModel):
    """An external asset attached to an event."""
    id: str
    type: Literal["image", "audio", "file"]
    path: str   # Server-side absolute path
    url: str    # Client-facing URL

class BaseEvent(BaseModel):
    """The root of all conversation events."""
    id: str
    session_id: str
    turn_id: str
    timestamp: float
    attachments: list[Attachment] = Field(default_factory=list)

class SystemEvent(BaseEvent):
    """Context, instructions, or internal observability."""
    role: Literal["system"] = "system"
    content: str
    is_visible: bool = False

class UserEvent(BaseEvent):
    """Input originating from the human."""
    role: Literal["user"] = "user"
    content: str

class AssistantEvent(BaseEvent):
    """Output originating from the AI."""
    role: Literal["assistant"] = "assistant"
    content: str | None = None
    tool_calls: list['ToolCall'] = Field(default_factory=list)

class ToolCall(BaseModel):
    """A tool invocation requested by the Assistant."""
    id: str
    name: str
    arguments: dict[str, Any]

class ToolResultEvent(BaseEvent):
    """The execution output of a requested tool."""
    role: Literal["tool"] = "tool"
    tool_call_id: str
    name: str
    ok: bool
    data: dict[str, Any]
    error: str | None = None
```

## 3. Ownership Matrix

| Field | Owner | Persistent? | Transport Only? |
| :--- | :--- | :--- | :--- |
| `id` / `session_id` | Database | Yes | No |
| `turn_id` | Orchestrator (groups multi-step loops) | Yes | No |
| `attachments` | Originating Event (User or ToolResult) | Yes | No |
| `content` | Originating Entity | Yes | No |
| `tool_calls` | AssistantEvent | Yes | No |

**Critical Attachment Rule:**
If the user uploads an image, it belongs to the `UserEvent.attachments`.
If a tool generates an image, it belongs to the `ToolResultEvent.attachments`.
*It is never injected into the System Prompt or retroactively assigned to the Assistant.*

## 4. Serialization Boundary Matrix

| Layer | Responsibility | Output Shape |
| :--- | :--- | :--- |
| **Database** | Stores events losslessly. | Rows map 1:1 to Event primitives. |
| **Orchestrator** | Enforces chronologies. Creates Events. | `list[BaseEvent]` |
| **LLM Provider** | Translates Events to Provider Specs. | OpenAI schema (e.g. injects base64 for images at send-time). |
| **SSE / REST** | Translates Events to Network Packets. | JSON representations of `BaseEvent`. |
| **Frontend** | Renders Events. | DOM mapped linearly to Event array. |

## 5. Persistence Compatibility Assessment

**Current Database Schema (`messages` table):**
```sql
id SERIAL PRIMARY KEY
session_id UUID
role VARCHAR
content TEXT
image_paths JSONB
tool_calls JSONB
tool_call_id VARCHAR
turn_id VARCHAR
```

**Assessment: Mostly Compatible, Needs Refinement (Phase 3).**
1. `image_paths` must be migrated to an `attachments` JSONB array to support file IDs and future types (audio/docs).
2. The current `messages` table conflates `AssistantEvent` (which uses `tool_calls`) and `ToolResultEvent` (which uses `tool_call_id` and raw JSON `content`). The canonical model maps perfectly to these roles, but we need to ensure the DB deserializer specifically constructs the correct Event subclass based on the `role` column.
3. UUIDs should be evaluated for `messages.id` rather than SERIAL to make client-side event tracking deterministic across transports.

## 6. Validation Strategy
We will validate this model by replacing the dictionaries returned by `app/db/queries.py:format_ai_history_rows` with these Pydantic models. If the providers can seamlessly accept the objects and generate completion payloads, the model holds. If the orchestrator loop can cleanly yield these objects to the SSE boundary, the boundary is proven.