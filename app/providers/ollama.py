from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator

import httpx

from app.core.llm_context import LLMContext
from app.providers.base import AIProvider, ProviderCapabilities
from app.tools.schemas import StreamToolEvent

logger = logging.getLogger(__name__)


class OllamaProvider(AIProvider):
    def __init__(self, config: dict | None = None):
        super().__init__("ollama", config)
        self.base_url = self.config.get("base_url", "http://127.0.0.1:11434")
        self.capabilities = ProviderCapabilities(
            supports_native_fc=False,  # Ollama FC support is model-dependent, disabled by default
            supports_streaming_fc=False,
            supports_tool_call_parsing=False,
        )
        self.available_models: list[str] = []

    async def get_models(self) -> list[str]:
        return self.available_models

    async def send_message(
        self, ctx: LLMContext, messages: list[dict], source: str = "llm", **kwargs
    ) -> str | None:

        try:
            temperature = kwargs.get("temperature")
            top_p = kwargs.get("top_p")
            top_k = kwargs.get("top_k")
            typical_p = kwargs.get("typical_p")
            num_ctx = kwargs.get("num_ctx")

            payload = {
                "model": ctx.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": top_k,
                    "typical_p": typical_p,
                    "num_ctx": num_ctx,
                },
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{ctx.base_url or self.base_url}/api/chat",
                    json=payload,
                    timeout=kwargs.get("timeout", 180),
                )

            if response.status_code == 200:
                result = response.json()
                return result["message"]["content"].strip()
            else:
                return None

        except Exception:
            return None

    async def _send_message_streaming_impl(
        self, ctx: LLMContext, messages: list[dict], source: str = "llm", **kwargs
    ) -> AsyncGenerator[str | StreamToolEvent, None]:

        try:
            temperature = kwargs.get("temperature")
            top_p = kwargs.get("top_p")
            top_k = kwargs.get("top_k")
            typical_p = kwargs.get("typical_p")
            num_ctx = kwargs.get("num_ctx")

            payload = {
                "model": ctx.model,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": top_k,
                    "typical_p": typical_p,
                    "num_ctx": num_ctx,
                },
            }

            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    f"{ctx.base_url or self.base_url}/api/chat",
                    json=payload,
                    timeout=kwargs.get("timeout", 180),
                ) as response:
                    if response.status_code == 200:
                        async for line in response.aiter_lines():
                            if line:
                                try:
                                    json_data = json.loads(line)
                                    if (
                                        "message" in json_data
                                        and "content" in json_data["message"]
                                    ):
                                        yield json_data["message"]["content"]
                                except json.JSONDecodeError:
                                    continue
                    else:
                        await response.aread()
                        logger.warning(
                            "[%s] HTTP %d for model %s: %s",
                            self.name,
                            response.status_code,
                            ctx.model,
                            response.text[:200],
                        )
                        yield f"\n[System] API returned HTTP {response.status_code}. Please try again."

        except Exception as e:
            logger.error("Ollama streaming error: %s", repr(e), exc_info=True)
            error_msg = str(e)
            if not error_msg:
                error_msg = repr(e)
            yield f"Error: {type(e).__name__} - {error_msg}"
