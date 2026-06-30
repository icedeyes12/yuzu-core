"""Regression tests for the Native Function Calling orchestration layer (FC3, FC9)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.tools.schemas import (
    StreamToolEvent,
    make_tool_call_event,
    new_turn_id,
)
from app.orchestrator import (
    _parse_raw_tool_calls_async,
    _execute_tool_calls_async,
)


class TestParseRawToolCallsAsync:
    """_parse_raw_tool_calls_async() uses provider capability-aware parsing."""

    async def _ensure_manager(self):
        from app.providers import get_ai_manager
        from app.providers.openrouter import OpenRouterProvider

        manager = await get_ai_manager()
        await manager.initialize()
        # Ensure openrouter is registered for testing (may not be available without API key)
        if "openrouter" not in manager.providers:
            provider = OpenRouterProvider()
            provider.is_available = True
            manager.register_provider("openrouter", provider)

    @pytest.mark.asyncio
    async def test_openrouter_parses_tool_calls(self):
        await self._ensure_manager()
        raw = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_abc",
                                "function": {
                                    "name": "bash",
                                    "arguments": '{"cmd": "ls"}',
                                },
                            }
                        ],
                    },
                }
            ],
        }
        calls = await _parse_raw_tool_calls_async("openrouter", raw, turn_id="turn_1")
        assert len(calls) == 1
        assert calls[0]["name"] == "bash"
        assert calls[0]["arguments"] == {"cmd": "ls"}

    @pytest.mark.asyncio
    async def test_ollama_returns_empty(self):
        raw = {"choices": [{"message": {"content": "hello", "tool_calls": []}}]}
        calls = await _parse_raw_tool_calls_async("ollama", raw)
        assert calls == []

    @pytest.mark.asyncio
    async def test_none_response_returns_empty(self):
        await self._ensure_manager()
        calls = await _parse_raw_tool_calls_async("openrouter", None)
        assert calls == []

    @pytest.mark.asyncio
    async def test_turn_id_in_log(self):
        """Verify turn_id parameter is accepted (correlates logs)."""
        await self._ensure_manager()
        raw = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "bash",
                                    "arguments": '{"cmd": "echo test"}',
                                },
                            }
                        ],
                    },
                }
            ],
        }
        calls = await _parse_raw_tool_calls_async("openrouter", raw, turn_id="turn_xyz")
        assert len(calls) == 1


class TestExecuteToolCallsAsync:
    """_execute_tool_calls_async() uses canonical execute_tool_event() path.

    These tests mock execute_tool_event to avoid requiring a live database.
    """

    @pytest.mark.asyncio
    async def test_executes_single_tool(self):
        mock_result = AsyncMock()
        mock_result.ok = True
        mock_result.markdown = "ok"
        mock_result.error = ""
        with patch(
            "app.orchestrator.execute_tool_event",
            new=AsyncMock(return_value=mock_result),
        ):
            tool_calls = [
                {"id": "call_1", "name": "bash", "arguments": {"cmd": "echo hello"}}
            ]
            results = await _execute_tool_calls_async(
                tool_calls, session_id="test_session"
            )
        assert len(results) == 1
        tool_name, result = results[0]
        assert tool_name == "bash"
        assert result["ok"] is True
        assert "markdown" in result

    @pytest.mark.asyncio
    async def test_executes_multiple_tools(self):
        mock_result = AsyncMock()
        mock_result.ok = True
        mock_result.markdown = "ok"
        mock_result.error = ""
        with patch(
            "app.orchestrator.execute_tool_event",
            new=AsyncMock(return_value=mock_result),
        ):
            tool_calls = [
                {"id": "call_1", "name": "bash", "arguments": {"cmd": "echo first"}},
                {"id": "call_2", "name": "bash", "arguments": {"cmd": "echo second"}},
            ]
            results = await _execute_tool_calls_async(
                tool_calls, session_id="test_session"
            )
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_empty_list(self):
        results = await _execute_tool_calls_async([], session_id="test_session")
        assert results == []


class TestStreamToolEventHandling:
    """Orchestrator streaming path handles StreamToolEvent (FC9)."""

    def test_isinstance_check_works(self):
        """Verify isinstance check distinguishes StreamToolEvent from str."""
        event = StreamToolEvent(
            type="tool_call", data={"id": "call_1", "name": "bash", "arguments": {}}
        )
        assert isinstance(event, StreamToolEvent)
        assert not isinstance("plain string", StreamToolEvent)

    def test_tool_call_data_shape(self):
        """Verify tool_call event data has expected shape for orchestrator."""
        event = StreamToolEvent(
            type="tool_call",
            data={"id": "call_1", "name": "bash", "arguments": {"cmd": "ls"}},
        )
        assert event.type == "tool_call"
        assert isinstance(event.data, dict)
        assert event.data["name"] == "bash"
        assert "arguments" in event.data


class TestTurnIdCorrelation:
    """turn_id flows through the orchestration pipeline."""

    def test_new_turn_id_unique(self):
        id1 = new_turn_id()
        id2 = new_turn_id()
        assert id1 != id2
        assert id1.startswith("turn_")
        assert id2.startswith("turn_")

    def test_tool_call_event_carries_turn_id(self):
        event = make_tool_call_event(name="bash", arguments={}, turn_id="turn_abc")
        assert event.turn_id == "turn_abc"
