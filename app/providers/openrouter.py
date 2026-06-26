from __future__ import annotations

import json
import logging
import httpx
import requests
from typing import AsyncGenerator
from app.providers.base import AIProvider
from app.tools import multimodal_tools

logger = logging.getLogger(__name__)


class OpenRouterProvider(AIProvider):
    def __init__(self, config: dict | None = None):
        super().__init__("openrouter", config)
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.available_models = [
            "deepseek/deepseek-chat-v3-0324:free",
            "deepseek/deepseek-v4-flash:free",
            "openai/gpt-4o",
            "openai/gpt-4o-mini",
            "anthropic/claude-sonnet-4",
            "google/gemini-2.5-flash",
            "qwen/qwen3-235b-a22b",
            "deepseek/deepseek-chat-v3.1:free",
            "deepseek/deepseek-r1:free",
            "google/gemini-flash-1.5-8b:free",
            "google/gemini-flash-1.5:free",
            "meituan/longcat-flash-chat:free",
            "openai/gpt-4o-mini:free",
            "openai/gpt-4o-mini-2024-07-18:free",
            "qwen/qwen3-235b-a22b:free",
            "qwen/qwen3-vl-235b-a22b-instruct:free",
            "tngtech/deepseek-r1-chimera:free",
            "tngtech/deepseek-r1t2-chimera:free",
            "z-ai/glm-4.5-air:free",
            "z-ai/glm-4.5-air-2507:free",
            "x-ai/grok-4.1-fast:free",
            "deepseek/deepseek-chat-v3-0324",
            "deepseek/deepseek-chat-v3.1",
            "deepseek/deepseek-v3.2",
            "deepseek/deepseek-v3.2-exp",
            "deepseek/deepseek-v3.2-speciale",
            "google/gemma-3-12b",
            "xiaomi/mimo-v2-flash",
            "minimax/minimax-m2",
            "moonshotai/kimi-k2.5",
            "moonshotai/kimi-k2-0905",
            "openai/gpt-oss-120b",
            "qwen/qwen3-235b-a22b-2507",
            "qwen/qwen3-coder",
            "qwen/qwen3.5-397b-a17b",
            "qwen/qwen3.5-plus-02-15",
            "tngtech/deepseek-r1t2-chimera",
            "z-ai/glm-4.6",
            "z-ai/glm-4.7",
            "openrouter/owl-alpha",
        ]

    def get_models(self) -> list[str]:
        return self.available_models

    def _prepare_payload(
        self, messages: list[dict], model: str, stream: bool, **kwargs
    ) -> tuple[dict, dict]:
        messages = self._normalize_messages(messages)

        if self.supports_vision(model) and messages:
            last_user_message = self._get_last_user_message(messages)
            if last_user_message and multimodal_tools.has_images(last_user_message):
                vision_messages = self.format_vision_message(last_user_message)
                messages = self._replace_last_user_message(
                    messages, last_user_message, vision_messages
                )

        temperature = kwargs.get("temperature", 0.73)
        max_tokens = kwargs.get("max_tokens")
        top_p = kwargs.get("top_p", 0.9)
        top_k = kwargs.get("top_k", 40)
        typical_p = kwargs.get("typical_p", 0.8)

        if model.endswith(":free"):
            max_tokens = min(max_tokens or 2048, 2048)
            temperature = min(temperature, 0.8)

        headers = {
            "Authorization": f"Bearer {self._require_api_key()}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/icedeyes12/yuzu-companion",
            "X-Title": "Yuzu-Companion",
        }

        payload = {
            "model": self.resolve_model(model),
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
            if not stream:  # Usually tool_choice is auto for non-streaming
                payload["tool_choice"] = "auto"

        return headers, payload

    def send_message(self, messages: list[dict], model: str, **kwargs) -> str | None:
        if model not in self.available_models:
            return None

        try:
            headers, payload = self._prepare_payload(messages, model, False, **kwargs)
            logger.debug(
                f"[OpenRouter] {model} | max_tokens={payload['max_tokens'] or 'unlimited'}"
            )

            response = requests.post(
                self.resolve_base_url(self.base_url),
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
        except Exception:
            return None

    def send_message_raw(
        self, messages: list[dict], model: str, **kwargs
    ) -> dict | None:
        if model not in self.available_models:
            return None

        try:
            headers, payload = self._prepare_payload(messages, model, False, **kwargs)
            response = requests.post(
                self.resolve_base_url(self.base_url),
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
        except Exception as e:
            logger.error(
                f"[OpenRouter] exception in send_message_raw: {type(e).__name__}: {e}"
            )
            return None

    async def send_message_streaming(
        self, messages: list[dict], model: str, **kwargs
    ) -> AsyncGenerator[str, None]:
        if model not in self.available_models:
            yield ""
            return

        try:
            headers, payload = self._prepare_payload(messages, model, True, **kwargs)
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    self.resolve_base_url(self.base_url),
                    headers=headers,
                    json=payload,
                    timeout=kwargs.get("timeout", 180),
                ) as response:
                    if response.status_code == 200:
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
                                        delta = json_data["choices"][0].get("delta", {})
                                        if "content" in delta and delta["content"]:
                                            yield delta["content"]
                                except (json.JSONDecodeError, KeyError):
                                    continue
                    else:
                        yield ""
        except Exception as e:
            logger.error("OpenRouter streaming error: %s", repr(e), exc_info=True)
            error_msg = str(e)
            if not error_msg:
                error_msg = repr(e)
            yield f"Error: {type(e).__name__} - {error_msg}"

    def parse_tool_calls(self, raw_response) -> list[dict]:
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
        except Exception:
            return []
