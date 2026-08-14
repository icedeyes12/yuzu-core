from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from app.core.context import MissingProviderKeyError
from app.core.llm_context import LLMContext
from app.providers.base import AIProvider, ProviderCapabilities
from app.tools.schemas import StreamToolEvent

logger = logging.getLogger(__name__)


class CustomAnthropicProvider(AIProvider):
    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__("custom_anthropic", config)
        self.base_url: str = "https://api.anthropic.com/v1/messages"
        self.capabilities: ProviderCapabilities = ProviderCapabilities(
            supports_native_fc=True,
            supports_streaming_fc=True,
            supports_tool_call_parsing=True,
            supports_structured_system_content=False,
        )

    def _resolve_url(self, ctx: LLMContext) -> str:
        """Ensure the URL ends with /messages."""
        url = (ctx.base_url or self.base_url).rstrip("/")
        if not url.endswith("/messages"):
            url += "/messages"
        return url

    async def fetch_live_models(
        self, api_key: str | None = None, base_url: str | None = None
    ) -> list[str]:
        if not base_url:
            return []
        return await self._fetch_models(base_url, api_key)

    async def _fetch_models(self, base_url: str, api_key: str | None) -> list[str]:
        url = base_url.rstrip("/")
        if url.endswith("/messages"):
            url = url[: -len("/messages")]
        url = f"{url}/models"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=10.0)
            if response.status_code != 200:
                return []
            metadata = [
                item
                for item in response.json().get("data", [])
                if isinstance(item, dict)
            ]
            self.set_model_metadata(metadata)
            return sorted(
                {
                    model_id
                    for item in metadata
                    if isinstance(model_id := item.get("id"), str) and model_id
                }
            )
        except (MissingProviderKeyError, httpx.HTTPError, ValueError):
            return []

    async def get_models(self) -> list[str]:
        return await self.fetch_live_models()

    def _convert_tools_to_anthropic(
        self, openai_tools: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        anthropic_tools = []
        for t in openai_tools:
            if t.get("type") == "function":
                fn = t.get("function", {})
                anthropic_tools.append(
                    {
                        "name": fn.get("name", ""),
                        "description": fn.get("description", ""),
                        "input_schema": fn.get(
                            "parameters", {"type": "object", "properties": {}}
                        ),
                    }
                )
        return anthropic_tools

    def _prepare_payload(
        self, ctx: LLMContext, messages: list[dict[str, Any]], stream: bool, **kwargs
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        system_text = ""
        anthropic_messages = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                system_text += content + "\n"
            elif role == "user" or role == "assistant":
                anthropic_messages.append({"role": role, "content": content})
            elif role == "tool":
                anthropic_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.get("tool_call_id", ""),
                                "content": content,
                            }
                        ],
                    }
                )

        headers = {
            "x-api-key": self._require_api_key(ctx),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": ctx.model,
            "messages": anthropic_messages,
            "max_tokens": kwargs.get("max_tokens"),
            "stream": stream,
        }
        if system_text:
            payload["system"] = system_text.strip()

        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]

        tools = kwargs.get("tools")
        if tools:
            payload["tools"] = self._convert_tools_to_anthropic(tools)

        return headers, payload

    async def send_message(
        self,
        ctx: LLMContext,
        messages: list[dict[str, Any]],
        source: str = "llm",
        **kwargs,
    ) -> str | None:
        try:
            headers, payload = self._prepare_payload(ctx, messages, False, **kwargs)
            base = self._resolve_url(ctx)
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    base,
                    headers=headers,
                    json=payload,
                    timeout=kwargs.get("timeout", 180),
                )
            if response.status_code == 200:
                result = response.json()
                self._last_raw_response = result
                content_blocks = result.get("content", [])
                text = ""
                for block in content_blocks:
                    if block.get("type") == "text":
                        text += block.get("text", "")
                return text.strip()
            logger.warning(
                "[CustomAnthropic] %s: %s", response.status_code, response.text[:300]
            )
            return None
        except MissingProviderKeyError:
            raise
        except Exception as e:
            logger.error("[CustomAnthropic] send_message error: %s", e)
            return None

    async def send_message_raw(
        self,
        ctx: LLMContext,
        messages: list[dict[str, Any]],
        source: str = "llm",
        **kwargs,
    ) -> dict[str, Any] | None:
        try:
            headers, payload = self._prepare_payload(ctx, messages, False, **kwargs)
            base = self._resolve_url(ctx)
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    base,
                    headers=headers,
                    json=payload,
                    timeout=kwargs.get("timeout", 180),
                )
            if response.status_code == 200:
                result = response.json()
                self._last_raw_response = result
                return self._convert_response_to_openai(result)
            logger.warning(
                "[CustomAnthropic] raw %s: %s",
                response.status_code,
                response.text[:300],
            )
            return None
        except MissingProviderKeyError:
            raise
        except Exception as e:
            logger.error("[CustomAnthropic] send_message_raw error: %s", e)
            return None

    def _convert_response_to_openai(self, anth_res: dict[str, Any]) -> dict[str, Any]:
        text = ""
        tool_calls = []
        for block in anth_res.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    {
                        "id": block.get("id"),
                        "type": "function",
                        "function": {
                            "name": block.get("name"),
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    }
                )

        return {
            "choices": [
                {"message": {"content": text.strip(), "tool_calls": tool_calls}}
            ]
        }

    async def _send_message_streaming_impl(
        self,
        ctx: LLMContext,
        messages: list[dict[str, Any]],
        source: str = "llm",
        **kwargs,
    ) -> AsyncGenerator[str | StreamToolEvent, None]:
        suppress_tools = kwargs.pop("suppress_tools", False)
        try:
            headers, payload = self._prepare_payload(ctx, messages, True, **kwargs)
            if suppress_tools:
                payload.pop("tools", None)

            base = self._resolve_url(ctx)

            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    base,
                    headers=headers,
                    json=payload,
                    timeout=kwargs.get("timeout", 180),
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        logger.warning(
                            "[CustomAnthropic] stream %s: %s",
                            response.status_code,
                            body[:300],
                        )
                        yield f"\n[System] {self.name} API returned HTTP {response.status_code}. Please try again."
                        return
                    tool_call_fragments: dict[int, dict[str, Any]] = {}

                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        try:
                            data = json.loads(line[6:])
                            event_type = data.get("type")

                            if event_type == "content_block_delta":
                                delta = data.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    yield delta.get("text", "")
                                elif delta.get("type") == "input_json_delta":
                                    idx = data.get("index", 0)
                                    if idx in tool_call_fragments:
                                        tool_call_fragments[idx]["function"][
                                            "arguments"
                                        ] += delta.get("partial_json", "")

                            elif event_type == "content_block_start":
                                block = data.get("content_block", {})
                                if block.get("type") == "tool_use":
                                    idx = data.get("index", 0)
                                    tool_call_fragments[idx] = {
                                        "id": block.get("id", ""),
                                        "function": {
                                            "name": block.get("name", ""),
                                            "arguments": "",
                                        },
                                    }

                            elif event_type == "message_stop":
                                break

                        except (json.JSONDecodeError, KeyError):
                            continue

                    for idx in sorted(tool_call_fragments):
                        frag = tool_call_fragments[idx]
                        try:
                            args = (
                                json.loads(frag["function"]["arguments"])
                                if frag["function"]["arguments"]
                                else {}
                            )
                        except json.JSONDecodeError:
                            args = {}
                        yield StreamToolEvent(
                            type="tool_call",
                            data={
                                "id": frag["id"],
                                "name": frag["function"]["name"],
                                "arguments": args,
                            },
                        )

        except MissingProviderKeyError:
            raise

        except Exception as e:
            logger.error(
                "[CustomAnthropic] streaming error: %s", repr(e), exc_info=True
            )
            yield f"Error: {type(e).__name__} - {e}"

    def parse_tool_calls(self, raw_response) -> list[dict[str, Any]]:
        if not isinstance(raw_response, dict):
            return []
        try:
            message = raw_response.get("choices", [{}])[0].get("message", {})
            results = []
            for tc in message.get("tool_calls", []):
                fn = tc.get("function", {})
                results.append(
                    {
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "arguments": json.loads(fn.get("arguments", "{}")),
                    }
                )
            return results
        except MissingProviderKeyError:
            raise
        except Exception:
            return []
