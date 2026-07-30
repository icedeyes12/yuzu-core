from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from app.core.context import MissingProviderKeyError
from app.core.llm_context import LLMContext
from app.providers.base import AIProvider, ProviderCapabilities
from app.tools.multimodal import multimodal_tools
from app.tools.schemas import StreamToolEvent

logger = logging.getLogger(__name__)


class OpenRouterProvider(AIProvider):
    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__("openrouter", config)
        self.base_url: str = "https://openrouter.ai/api/v1/chat/completions"
        self.capabilities: ProviderCapabilities = ProviderCapabilities(
            supports_native_fc=True,
            supports_streaming_fc=True,  # FC9: streaming tool-call parsing implemented
            supports_tool_call_parsing=True,
            supports_structured_system_content=True,
            supports_vision=True,
        )
        self.available_models: list[str] = []

    async def get_models(self) -> list[str]:
        return self.available_models

    async def fetch_live_models(self) -> list[str]:
        """Fetch the canonical model list from OpenRouter's /models endpoint.

        Fetch models only when the caller provides a request-scoped key.
        """
        try:
            import httpx

            url = "https://openrouter.ai/api/v1/models"
            key = None
            try:
                from app.core.context import get_request_keyring

                keyring = get_request_keyring("openrouter")
                if keyring and keyring.key:
                    key = keyring.key
            except MissingProviderKeyError:
                raise
            except Exception:  # noqa: BLE001
                pass
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers, timeout=8.0)
                if resp.status_code != 200:
                    return []
                data = resp.json()
            return [
                model_id
                for m in (data.get("data") or [])
                if isinstance(m, dict) and isinstance(model_id := m.get("id"), str)
            ]
        except MissingProviderKeyError:
            raise
        except Exception:
            return []

    def _prepare_payload(
        self, ctx: LLMContext, messages: list[dict[str, Any]], stream: bool, **kwargs
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        messages = self._normalize_messages(messages)
        model = ctx.model
        assert model is not None

        if self.supports_vision(model) and messages:
            last_user_message = self._get_last_user_message(messages)
            if last_user_message and multimodal_tools.has_images(last_user_message):
                vision_messages = self.format_vision_message(last_user_message)
                messages = self._replace_last_user_message(
                    messages, last_user_message, vision_messages
                )

        temperature = kwargs.get("temperature")
        max_tokens = kwargs.get("max_tokens")
        top_p = kwargs.get("top_p")
        top_k = kwargs.get("top_k")
        typical_p = kwargs.get("typical_p")

        headers = {
            "Authorization": f"Bearer {self._require_api_key(ctx)}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/icedeyes12/yuzu-companion",
            "X-Title": "Yuzu-Companion",
        }

        payload = {
            "model": ctx.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
            "top_k": top_k,
            "typical_p": typical_p,
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
            logger.debug(
                f"[OpenRouter] {ctx.model} | max_tokens={payload['max_tokens'] or 'unlimited'}"
            )

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    ctx.base_url or self.base_url,
                    headers=headers,
                    json=payload,
                    timeout=kwargs.get("timeout", 180),
                )

            if response.status_code == 200:
                result = response.json()
                self._last_raw_response = result
                message = result["choices"][0]["message"]
                content = message.get("content", "")
                return content.strip() if content else ""

            if response.status_code == 402:
                return "OpenRouter free tier limit reached. Please try a different model or add credits."
            if response.status_code == 429:
                return "Rate limit exceeded. Please wait a moment and try again."
            return None
        except MissingProviderKeyError:
            raise
        except Exception:
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
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    ctx.base_url or self.base_url,
                    headers=headers,
                    json=payload,
                    timeout=kwargs.get("timeout", 180),
                )

            if response.status_code == 200:
                result = response.json()
                self._last_raw_response = result
                return result
            logger.warning(
                f"[OpenRouter] raw error {response.status_code}: {response.text[:500]}"
            )
            return None
        except MissingProviderKeyError:
            raise
        except Exception as e:
            logger.error(
                f"[OpenRouter] exception in send_message_raw: {type(e).__name__}: {e}"
            )
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

            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    ctx.base_url or self.base_url,
                    headers=headers,
                    json=payload,
                    timeout=kwargs.get("timeout", 180),
                ) as response:
                    if response.status_code == 200:
                        if has_tools:
                            # FC9: Accumulate tool call fragments from delta chunks
                            tool_call_fragments: dict[int, dict[str, Any]] = {}
                            async for line in response.aiter_lines():
                                if not line or not line.startswith("data: "):
                                    continue
                                if line == "data: [DONE]":
                                    break
                                try:
                                    json_data = json.loads(line[6:])
                                    if (
                                        "choices" in json_data
                                        and len(json_data["choices"]) > 0
                                    ):
                                        delta = json_data["choices"][0].get("delta", {})
                                        # Yield text content
                                        if delta.get("content"):
                                            yield delta["content"]
                                        # Accumulate tool call fragments
                                        if delta.get("tool_calls"):
                                            for tc_delta in delta["tool_calls"]:
                                                idx = tc_delta.get("index", 0)
                                                if idx not in tool_call_fragments:
                                                    tool_call_fragments[idx] = {
                                                        "id": "",
                                                        "function": {
                                                            "name": "",
                                                            "arguments": "",
                                                        },
                                                    }
                                                frag = tool_call_fragments[idx]
                                                if tc_delta.get("id"):
                                                    frag["id"] = tc_delta["id"]
                                                fn = tc_delta.get("function", {})
                                                if fn.get("name"):
                                                    frag["function"]["name"] = fn[
                                                        "name"
                                                    ]
                                                if fn.get("arguments"):
                                                    frag["function"]["arguments"] += fn[
                                                        "arguments"
                                                    ]
                                except (json.JSONDecodeError, KeyError):
                                    continue

                            # Emit each accumulated tool call as individual StreamToolEvent
                            for idx in sorted(tool_call_fragments.keys()):
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
                            # No tools — plain text streaming
                            async for line in response.aiter_lines():
                                if line and line.startswith("data: "):
                                    if line == "data: [DONE]":
                                        break
                                    try:
                                        json_data = json.loads(line[6:])
                                        if (
                                            "choices" in json_data
                                            and len(json_data["choices"]) > 0
                                        ):
                                            delta = json_data["choices"][0].get(
                                                "delta", {}
                                            )
                                            if delta.get("content"):
                                                yield delta["content"]
                                    except (json.JSONDecodeError, KeyError):
                                        continue
                    else:
                        _ = await response.aread()
                        logger.warning(
                            "[%s] HTTP %d for model %s: %s",
                            self.name,
                            response.status_code,
                            ctx.model,
                            response.text[:200],
                        )
                        yield f"\n[System] API returned HTTP {response.status_code}. Please try again."
        except MissingProviderKeyError:
            raise
        except Exception as e:
            logger.error("OpenRouter streaming error: %s", repr(e), exc_info=True)
            error_msg = str(e)
            if not error_msg:
                error_msg = repr(e)
            yield f"Error: {type(e).__name__} - {error_msg}"

    def parse_tool_calls(self, raw_response) -> list[dict[str, Any]]:
        if not isinstance(raw_response, dict):
            return []
        try:
            message = raw_response.get("choices", [{}])[0].get("message", {})
            tool_calls = message.get("tool_calls", [])
            results = []
            for tc in tool_calls:
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
