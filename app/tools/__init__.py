from __future__ import annotations

# tools package
from app.tools.registry import execute_tool as execute_tool
from app.tools.registry import execute_tool_event as execute_tool_event
from app.tools.registry import get_tool_definitions as get_tool_definitions
from app.tools.registry import get_tool_definition as get_tool_definition
from app.tools.registry import get_tool_role as get_tool_role
from app.tools.registry import get_tool_schemas as get_tool_schemas
from app.tools.registry import get_tool_capabilities as get_tool_capabilities
from app.tools.registry import get_all_capabilities as get_all_capabilities
from app.tools.schemas import ToolDefinition, ToolParam
from app.tools.schemas import ToolCallEvent, ToolResultEvent, StreamToolEvent
from app.tools.schemas import make_tool_call_event, make_tool_result_event, new_turn_id
from app.tools.multimodal import multimodal_tools as multimodal_tools
from app.tools.multimodal import MultimodalTools as MultimodalTools


__all__ = [
    # Dispatch
    "execute_tool",
    "execute_tool_event",
    # Schema access
    "get_tool_definitions",
    "get_tool_definition",
    "get_tool_role",
    "get_tool_schemas",
    "get_tool_capabilities",
    "get_all_capabilities",
    # Core types
    "ToolDefinition",
    "ToolParam",
    # Event envelope
    "ToolCallEvent",
    "ToolResultEvent",
    "StreamToolEvent",
    "make_tool_call_event",
    "make_tool_result_event",
    "new_turn_id",
    # Multimodal
    "multimodal_tools",
    "MultimodalTools",
]
