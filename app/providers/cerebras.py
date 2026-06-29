from __future__ import annotations

import logging
import httpx
from typing import AsyncGenerator
from app.providers.base import AIProvider

logger = logging.getLogger(__name__)


class CerebrasProvider(AIProvider):
    def __init__(self, config: dict | None = None):
        super().__init__("cerebras", config)
        self.base_url = "https://api.cerebras.ai/v1/chat/completions"
        self.available_models = [
            "qwen-3-235b-a22b-instruct-2507",
            "qwen-3-235b-a22b-thinking-2507",
            "qwen-3-coder-480b",
            "qwen-3-32b",
            "gpt-oss-120b",
            "llama-3.3-70b",
            "llama-4-scout-17b-16e-instruct",
            "llama3.1-8b",
        ]

    def get_models(self) -> list[str]:
        return self.available_models

    async def send_message(
        self, messages: list[dict], model: str, **kwargs
    ) -> str | None:
        if model not in self.available_models:
            return None

        try:
            messages = self._normalize_messages(messages)
            temperature = kwargs.get("temperature", 0.69)
            max_tokens = kwargs.get("max_tokens")
            top_p = kwargs.get("top_p", 0.7)
            top_k = kwargs.get("top_k", 40)
            typical_p = kwargs.get("typical_p", 0.8)

            headers = {
                "Authorization": f"Bearer {self._require_api_key()}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": self.resolve_model(model),
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": top_p,
                "top_k": top_k,
                "typical_p": typical_p,
                "stream": False,
            }

            logger.debug(
                f"[Cerebras] {model} | new_msg=1 | max_tokens={max_tokens or 'unlimited'}"
            )

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.resolve_base_url(self.base_url),
                    headers=headers,
                    json=payload,
                    timeout=kwargs.get("timeout", 120),
                )

            if response.status_code == 200:
                result = response.json()
                return result["choices"][0]["message"]["content"].strip()
            return None
        except Exception:
            return None

    async def send_message_streaming(
        self, messages: list[dict], model: str, **kwargs
    ) -> AsyncGenerator[str, None]:
        if model not in self.available_models:
            yield ""
            return

        try:
            messages = self._normalize_messages(messages)
            temperature = kwargs.get("temperature", 0.69)
            max_tokens = kwargs.get("max_tokens")
            top_p = kwargs.get("top_p", 0.7)
            top_k = kwargs.get("top_k", 40)
            typical_p = kwargs.get("typical_p", 0.8)

            headers = {
                "Authorization": f"Bearer {self._require_api_key()}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": self.resolve_model(model),
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": top_p,
                "top_k": top_k,
                "typical_p": typical_p,
                "stream": True,
            }

            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    self.resolve_base_url(self.base_url),
                    headers=headers,
                    json=payload,
                    timeout=kwargs.get("timeout", 120),
                ) as response:
                    if response.status_code == 200:
                        import json

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
            logger.error("Cerebras streaming error: %s", repr(e), exc_info=True)
            error_msg = str(e)
            if not error_msg:
                error_msg = repr(e)
            yield f"Error: {type(e).__name__} - {error_msg}"
