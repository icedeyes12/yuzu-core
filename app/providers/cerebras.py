from __future__ import annotations

from typing import Any

from app.core.llm_context import LLMContext
from app.providers.base import ProviderCapabilities
from app.providers.custom_openai import OpenAICompatibleProvider


class CerebrasProvider(OpenAICompatibleProvider):
    log_prefix: str = "Cerebras"
    default_timeout: float = 120.0

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__("cerebras", config)
        self.base_url: str = "https://api.cerebras.ai/v1/chat/completions"
        # Cerebras API doesn't expose function calling yet
        self.capabilities = ProviderCapabilities(
            supports_native_fc=False,
            supports_streaming_fc=False,
            supports_tool_call_parsing=False,
        )

    def _prepare_payload(
        self, ctx: LLMContext, messages: list[dict[str, Any]], stream: bool, **kwargs
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        headers, payload = super()._prepare_payload(ctx, messages, stream, **kwargs)
        payload["top_k"] = kwargs.get("top_k")
        payload["typical_p"] = kwargs.get("typical_p")
        return headers, payload
