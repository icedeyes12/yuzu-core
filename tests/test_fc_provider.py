"""Regression tests for the Native Function Calling provider layer (FC2, FC9)."""

from __future__ import annotations

import pytest

from app.providers.base import AIProviderManager, ProviderCapabilities
from app.tools.schemas import StreamToolEvent


class TestProviderCapabilities:
    """ProviderCapabilities declares what each provider supports."""

    def test_defaults(self):
        caps = ProviderCapabilities()
        assert caps.supports_native_fc is False
        assert caps.supports_streaming_fc is False
        assert caps.supports_tool_call_parsing is False

    def test_openrouter_capabilities(self):
        from app.providers.openrouter import OpenRouterProvider

        provider = OpenRouterProvider()
        assert provider.capabilities.supports_native_fc is True
        assert provider.capabilities.supports_streaming_fc is True
        assert provider.capabilities.supports_tool_call_parsing is True

    def test_ollama_capabilities(self):
        from app.providers.ollama import OllamaProvider

        provider = OllamaProvider()
        assert provider.capabilities.supports_native_fc is False

    def test_to_dict(self):
        caps = ProviderCapabilities(
            supports_native_fc=True,
            supports_streaming_fc=True,
            supports_tool_call_parsing=True,
        )
        d = caps.to_dict()
        assert d == {
            "supports_native_fc": True,
            "supports_streaming_fc": True,
            "supports_tool_call_parsing": True,
        }


class TestAIProviderManagerCapabilities:
    """AIProviderManager routes based on provider capabilities."""

    async def _init_manager(self):
        """Ensure AIProviderManager is initialized with OpenRouter registered."""
        from app.providers import get_ai_manager
        from app.providers.openrouter import OpenRouterProvider

        manager = await get_ai_manager()
        await manager.initialize()
        if "openrouter" not in manager.providers:
            provider = OpenRouterProvider()
            provider.is_available = True
            manager.register_provider("openrouter", provider)
        return manager

    @pytest.mark.asyncio
    async def test_provider_supports_tools_openrouter(self):
        manager = await self._init_manager()
        assert manager.provider_supports_tools("openrouter") is True

    @pytest.mark.asyncio
    async def test_provider_supports_tools_ollama(self):
        manager = await self._init_manager()
        assert manager.provider_supports_tools("ollama") is False

    @pytest.mark.asyncio
    async def test_provider_supports_tools_unknown(self):
        manager = await self._init_manager()
        assert manager.provider_supports_tools("nonexistent") is False

    @pytest.mark.asyncio
    async def test_provider_supports_streaming_tools(self):
        manager = await self._init_manager()
        # OpenRouter now supports streaming FC (FC9)
        assert manager.provider_supports_streaming_tools("openrouter") is True
        # Ollama does not
        assert manager.provider_supports_streaming_tools("ollama") is False


class TestOpenRouterParseToolCalls:
    """OpenRouter parse_tool_calls() extracts canonical tool calls from raw response."""

    def test_parses_single_tool_call(self):
        from app.providers.openrouter import OpenRouterProvider

        provider = OpenRouterProvider()
        raw = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_abc123",
                                "function": {
                                    "name": "bash",
                                    "arguments": '{"cmd": "ls -la"}',
                                },
                            }
                        ],
                    },
                }
            ],
        }
        calls = provider.parse_tool_calls(raw)
        assert len(calls) == 1
        assert calls[0]["id"] == "call_abc123"
        assert calls[0]["name"] == "bash"
        assert calls[0]["arguments"] == {"cmd": "ls -la"}

    def test_parses_multiple_tool_calls(self):
        from app.providers.openrouter import OpenRouterProvider

        provider = OpenRouterProvider()
        raw = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "bash",
                                    "arguments": '{"cmd": "ls"}',
                                },
                            },
                            {
                                "id": "call_2",
                                "function": {
                                    "name": "python",
                                    "arguments": '{"script": "print(1)"}',
                                },
                            },
                        ],
                    },
                }
            ],
        }
        calls = provider.parse_tool_calls(raw)
        assert len(calls) == 2
        assert calls[0]["name"] == "bash"
        assert calls[1]["name"] == "python"

    def test_empty_tool_calls(self):
        from app.providers.openrouter import OpenRouterProvider

        provider = OpenRouterProvider()
        raw = {"choices": [{"message": {"content": "hello", "tool_calls": []}}]}
        calls = provider.parse_tool_calls(raw)
        assert calls == []

    def test_invalid_input_returns_empty(self):
        from app.providers.openrouter import OpenRouterProvider

        provider = OpenRouterProvider()
        assert provider.parse_tool_calls(None) == []
        assert provider.parse_tool_calls("not a dict") == []
        assert provider.parse_tool_calls({}) == []

    def test_malformed_arguments_handled(self):
        from app.providers.openrouter import OpenRouterProvider

        provider = OpenRouterProvider()
        raw = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "bash",
                                    "arguments": "not valid json",
                                },
                            }
                        ],
                    },
                }
            ],
        }
        # Should not crash — returns empty or handles gracefully
        calls = provider.parse_tool_calls(raw)
        # The function parses arguments with json.loads; invalid JSON raises and returns []
        assert isinstance(calls, list)


class TestOpenRouterPayloadPreparation:
    """OpenRouter _prepare_payload() includes tools when provided."""

    def _make_provider(self):
        from app.providers.openrouter import OpenRouterProvider

        provider = OpenRouterProvider()
        return provider

    def test_tools_attached_for_non_streaming(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test_key")
        provider = self._make_provider()
        messages = [{"role": "user", "content": "test"}]
        tools = [
            {
                "type": "function",
                "function": {"name": "bash", "description": "Run commands"},
            }
        ]
        headers, payload = provider._prepare_payload(
            messages, "openai/gpt-4o-mini", False, tools=tools
        )
        assert payload["tools"] == tools
        assert payload["tool_choice"] == "auto"

    def test_tools_attached_for_streaming(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test_key")
        provider = self._make_provider()
        messages = [{"role": "user", "content": "test"}]
        tools = [
            {
                "type": "function",
                "function": {"name": "bash", "description": "Run commands"},
            }
        ]
        headers, payload = provider._prepare_payload(
            messages, "openai/gpt-4o-mini", True, tools=tools
        )
        assert payload["tools"] == tools
        assert payload["tool_choice"] == "auto"

    def test_no_tools_when_not_provided(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test_key")
        provider = self._make_provider()
        messages = [{"role": "user", "content": "test"}]
        headers, payload = provider._prepare_payload(
            messages, "openai/gpt-4o-mini", False
        )
        assert "tools" not in payload


class TestStreamToolEventSSE:
    """StreamToolEvent serializes correctly for SSE transport."""

    def test_tool_call_event_shape(self):
        event = StreamToolEvent(
            type="tool_call",
            data={"id": "call_1", "name": "bash", "arguments": {"cmd": "ls"}},
        )
        sse = event.to_sse()
        assert sse["type"] == "tool_call"
        assert sse["data"]["name"] == "bash"

    def test_tool_result_event_shape(self):
        event = StreamToolEvent(
            type="tool_result", data={"call_id": "call_1", "name": "bash", "ok": True}
        )
        sse = event.to_sse()
        assert sse["type"] == "tool_result"
        assert sse["data"]["ok"] is True

    def test_token_event_shape(self):
        event = StreamToolEvent(type="token", data="hello")
        sse = event.to_sse()
        assert sse == {"type": "token", "content": "hello"}
