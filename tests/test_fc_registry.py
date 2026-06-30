"""Regression tests for the Native Function Calling tool registry and event schema (FC1)."""

from __future__ import annotations

import pytest

from app.tools.schemas import (
    StreamToolEvent,
    ToolCallEvent,
    ToolDefinition,
    ToolParam,
    ToolResultEvent,
    make_tool_call_event,
    make_tool_result_event,
    new_turn_id,
)
from app.tools.registry import (
    execute_tool_event,
    get_tool_capabilities,
    get_tool_schemas,
)


class TestToolDefinitionSchema:
    """ToolDefinition.to_llm_schema() produces valid OpenAI function-calling format."""

    def test_basic_schema_shape(self):
        tool = ToolDefinition(
            name="bash",
            description="Run shell commands",
            role="shell_tools",
            parameters=[
                ToolParam(name="cmd", description="Command to run", required=True),
            ],
        )
        schema = tool.to_llm_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "bash"
        assert schema["function"]["description"] == "Run shell commands"
        assert "cmd" in schema["function"]["parameters"]["properties"]
        assert "cmd" in schema["function"]["parameters"]["required"]

    def test_optional_parameter_not_in_required(self):
        tool = ToolDefinition(
            name="test_tool",
            description="A test tool",
            role="test_tools",
            parameters=[
                ToolParam(name="required_param", description="Required", required=True),
                ToolParam(
                    name="optional_param",
                    description="Optional",
                    required=False,
                    default="default_val",
                ),
            ],
        )
        schema = tool.to_llm_schema()
        assert "required_param" in schema["function"]["parameters"]["required"]
        assert "optional_param" not in schema["function"]["parameters"]["required"]

    def test_capability_flags_default_true(self):
        tool = ToolDefinition(name="test", description="Test", role="test_tools")
        assert tool.supports_native_fc is True
        assert tool.supports_streaming_fc is True


class TestGetToolSchemas:
    """get_tool_schemas() is the single source of truth for LLM tool arrays."""

    def test_returns_list_of_dicts(self):
        schemas = get_tool_schemas()
        assert isinstance(schemas, list)
        assert len(schemas) > 0
        for s in schemas:
            assert s["type"] == "function"
            assert "function" in s
            assert "name" in s["function"]

    def test_no_duplicates(self):
        schemas = get_tool_schemas()
        names = [s["function"]["name"] for s in schemas]
        assert len(names) == len(set(names))

    def test_only_native_fc_filter(self):
        all_schemas = get_tool_schemas()
        native_schemas = get_tool_schemas(only_native_fc=True)
        # Should return subset or equal
        assert len(native_schemas) <= len(all_schemas)
        for s in native_schemas:
            assert s["type"] == "function"


class TestGetToolCapabilities:
    """get_tool_capabilities() returns correct flags for each tool."""

    def test_known_tool_has_capabilities(self):
        caps = get_tool_capabilities("bash")
        assert isinstance(caps, dict)
        assert "supports_native_fc" in caps
        assert "supports_streaming_fc" in caps

    def test_unknown_tool_returns_false(self):
        caps = get_tool_capabilities("nonexistent_tool")
        assert caps["supports_native_fc"] is False
        assert caps["supports_streaming_fc"] is False


class TestToolCallEvent:
    """ToolCallEvent is the canonical invocation envelope."""

    def test_creation_with_turn_id(self):
        event = ToolCallEvent(
            id="call_123", name="bash", arguments={"cmd": "ls"}, turn_id="turn_abc"
        )
        assert event.id == "call_123"
        assert event.name == "bash"
        assert event.arguments == {"cmd": "ls"}
        assert event.turn_id == "turn_abc"

    def test_to_dict_serialization(self):
        event = ToolCallEvent(id="call_1", name="test", arguments={}, turn_id="turn_1")
        d = event.to_dict()
        assert d["event"] == "tool_call"
        assert d["id"] == "call_1"
        assert d["turn_id"] == "turn_1"


class TestToolResultEvent:
    """ToolResultEvent is the canonical result envelope."""

    def test_success_result(self):
        event = ToolResultEvent(
            call_id="call_1",
            name="bash",
            ok=True,
            data={"output": "file.txt"},
            markdown="<details>result</details>",
            turn_id="turn_1",
            tool_ms=42,
        )
        d = event.to_dict()
        assert d["event"] == "tool_result"
        assert d["ok"] is True
        assert d["tool_ms"] == 42
        assert "error" not in d

    def test_error_result_includes_error_field(self):
        event = ToolResultEvent(
            call_id="call_1",
            name="bash",
            ok=False,
            error="Something went wrong",
            turn_id="turn_1",
        )
        d = event.to_dict()
        assert d["ok"] is False
        assert d["error"] == "Something went wrong"


class TestStreamToolEvent:
    """StreamToolEvent is the SSE transport envelope."""

    def test_token_event_sse(self):
        event = StreamToolEvent(type="token", data="hello world")
        sse = event.to_sse()
        assert sse == {"type": "token", "content": "hello world"}

    def test_tool_call_event_sse(self):
        event = StreamToolEvent(
            type="tool_call", data={"id": "call_1", "name": "bash", "arguments": {}}
        )
        sse = event.to_sse()
        assert sse == {
            "type": "tool_call",
            "data": {"id": "call_1", "name": "bash", "arguments": {}},
        }

    def test_done_event_sse(self):
        event = StreamToolEvent(type="done")
        sse = event.to_sse()
        assert sse == {"type": "done"}


class TestFactoryHelpers:
    """Factory functions create canonical events."""

    def test_make_tool_call_event_generates_id(self):
        event = make_tool_call_event(name="bash", arguments={"cmd": "ls"})
        assert event.id.startswith("call_")
        assert event.name == "bash"

    def test_make_tool_call_event_with_explicit_id(self):
        event = make_tool_call_event(id="custom_id", name="bash", arguments={})
        assert event.id == "custom_id"

    def test_make_tool_result_event(self):
        event = make_tool_result_event(call_id="call_1", name="bash", ok=True)
        assert event.call_id == "call_1"
        assert event.ok is True

    def test_new_turn_id_format(self):
        turn_id = new_turn_id()
        assert turn_id.startswith("turn_")
        assert len(turn_id) > 20  # timestamp + random hex


class TestExecuteToolEvent:
    """execute_tool_event() is the canonical execution entry point (FC1).

    These tests mock execute_tool to avoid requiring a live database.
    """

    @pytest.mark.asyncio
    async def test_executes_known_tool(self):
        from unittest.mock import patch

        async def _mock_execute(tool_name, arguments, session_id=None, user_id=None):
            return {
                "ok": True,
                "data": {"output": "hello"},
                "markdown": "<details>ok</details>",
            }

        with patch("app.tools.registry.execute_tool", side_effect=_mock_execute):
            event = make_tool_call_event(name="bash", arguments={"cmd": "echo hello"})
            result = await execute_tool_event(event)
        assert isinstance(result, ToolResultEvent)
        assert result.call_id == event.id
        assert result.name == "bash"
        assert result.ok is True
        assert result.tool_ms >= 0  # mocked execution may be instant

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        event = make_tool_call_event(name="nonexistent_tool_xyz", arguments={})
        result = await execute_tool_event(event)
        assert result.ok is False
        assert "Unknown tool" in result.error

    @pytest.mark.asyncio
    async def test_turn_id_propagated(self):
        from unittest.mock import patch

        async def _mock_execute(tool_name, arguments, session_id=None, user_id=None):
            return {"ok": True, "data": {}, "markdown": "<details>ok</details>"}

        with patch("app.tools.registry.execute_tool", side_effect=_mock_execute):
            event = make_tool_call_event(
                name="bash", arguments={"cmd": "echo test"}, turn_id="turn_xyz"
            )
            result = await execute_tool_event(event)
        assert result.turn_id == "turn_xyz"
