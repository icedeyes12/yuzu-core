from __future__ import annotations

import json
import logging
import httpx
from typing import AsyncGenerator

from app.providers.base import AIProvider, ProviderCapabilities
from app.core.llm_context import LLMContext
from app.tools.schemas import StreamToolEvent

logger = logging.getLogger(__name__)

_DEFAULT_MODELS = [
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.0-pro-exp-02-05",
    "gemini-2.0-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
]


class GoogleProvider(AIProvider):
    def __init__(self, config: dict | None = None):
        super().__init__("google", config)
        self.base_url = (
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        )
        self.capabilities = ProviderCapabilities(
            supports_native_fc=True,
            supports_streaming_fc=True,
            supports_tool_call_parsing=True,
        )
        self.available_models = list(_DEFAULT_MODELS)

    async def get_models(self) -> list[str]:
        return self.available_models

    def _prepare_payload(
        self, ctx: LLMContext, messages: list[dict], stream: bool, **kwargs
    ) -> tuple[dict, dict]:
        messages = self._normalize_messages(messages)
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens", 4096)
        top_p = kwargs.get("top_p", 1.0)

        headers = {
            "Authorization": f"Bearer {self._require_api_key(ctx)}",
            "Content-Type": "application/json",
        }

        payload: dict = {
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
        self, ctx: LLMContext, messages: list[dict], **kwargs
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
            logger.warning("[Google] %s: %s", response.status_code, response.text[:300])
            return None
        except Exception as e:
            logger.error("[Google] send_message error: %s", e)
            return None

    async def send_message_raw(
        self, ctx: LLMContext, messages: list[dict], **kwargs
    ) -> dict | None:
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
                "[Google] raw %s: %s", response.status_code, response.text[:300]
            )
            return None
        except Exception as e:
            logger.error("[Google] send_message_raw error: %s", e)
            return None

    async def _send_message_streaming_impl(
        self,
        ctx: LLMContext,
        messages: list[dict],
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
                            "[Google] stream %s: %s", response.status_code, body[:300]
                        )
                        yield f"\n[System] {self.name} API returned HTTP {response.status_code}. Please try again."
                        return

                    if has_tools:
                        tool_call_fragments: dict[int, dict] = {}
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

        except Exception as e:
            logger.error("[Google] streaming error: %s", repr(e), exc_info=True)
            yield f"Error: {type(e).__name__} - {e}"

    def parse_tool_calls(self, raw_response) -> list[dict]:
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
        except Exception:
            return []
