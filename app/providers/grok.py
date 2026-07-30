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


class GrokProvider(AIProvider):
    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__("grok", config)
        self.base_url: str = "https://api.x.ai/v1/chat/completions"
        self.capabilities: ProviderCapabilities = ProviderCapabilities(
            supports_native_fc=True,
            supports_streaming_fc=True,
            supports_tool_call_parsing=True,
        )
        self.available_models: list[str] = []

    async def get_models(self) -> list[str]:
        return self.available_models

    def _prepare_payload(
        self, ctx: LLMContext, messages: list[dict[str, Any]], stream: bool, **kwargs
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        messages = self._normalize_messages(messages)
        temperature = kwargs.get("temperature")
        max_tokens = kwargs.get("max_tokens")
        top_p = kwargs.get("top_p")

        headers = {
            "Authorization": f"Bearer {self._require_api_key(ctx)}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": ctx.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
            "stream": stream,
        }

        tools = kwargs.get("tools")
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

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
            base = ctx.base_url or self.base_url
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
                content = result["choices"][0]["message"].get("content", "") or ""
                return content.strip()
            logger.warning("[Grok] %s: %s", response.status_code, response.text[:300])
            return None
        except MissingProviderKeyError:
            raise
        except Exception as e:
            logger.error("[Grok] send_message error: %s", e)
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
            base = ctx.base_url or self.base_url
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
                return result
            logger.warning(
                "[Grok] raw %s: %s", response.status_code, response.text[:300]
            )
            return None
        except MissingProviderKeyError:
            raise
        except Exception as e:
            logger.error("[Grok] send_message_raw error: %s", e)
            return None

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
                payload.pop("tool_choice", None)

            has_tools = bool(payload.get("tools"))
            base = ctx.base_url or self.base_url

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
                            "[Grok] stream %s: %s", response.status_code, body[:300]
                        )
                        yield f"\n[System] {self.name} API returned HTTP {response.status_code}. Please try again."
                        return

                    if has_tools:
                        tool_call_fragments: dict[int, dict[str, Any]] = {}
                        async for line in response.aiter_lines():
                            if not line or not line.startswith("data: "):
                                continue
                            if line == "data: [DONE]":
                                break
                            try:
                                data = json.loads(line[6:])
                                choices = data.get("choices", [])
                                if not choices:
                                    continue
                                delta = choices[0].get("delta", {})
                                if delta.get("content"):
                                    yield delta["content"]
                                for tc_delta in delta.get("tool_calls") or []:
                                    idx = tc_delta.get("index", 0)
                                    if idx not in tool_call_fragments:
                                        tool_call_fragments[idx] = {
                                            "id": "",
                                            "function": {"name": "", "arguments": ""},
                                        }
                                    frag = tool_call_fragments[idx]
                                    if tc_delta.get("id"):
                                        frag["id"] = tc_delta["id"]
                                    fn = tc_delta.get("function", {})
                                    if fn.get("name"):
                                        frag["function"]["name"] = fn["name"]
                                    if fn.get("arguments"):
                                        frag["function"]["arguments"] += fn["arguments"]
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
                    else:
                        async for line in response.aiter_lines():
                            if not line or not line.startswith("data: "):
                                continue
                            if line == "data: [DONE]":
                                break
                            try:
                                data = json.loads(line[6:])
                                choices = data.get("choices", [])
                                if choices:
                                    content = choices[0].get("delta", {}).get("content")
                                    if content:
                                        yield content
                            except (json.JSONDecodeError, KeyError):
                                continue

        except MissingProviderKeyError:
            raise

        except Exception as e:
            logger.error("[Grok] streaming error: %s", repr(e), exc_info=True)
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
