from __future__ import annotations

from typing import Any

from app.core.capabilities import (
    ModelCapabilities,
    ModelInfo,
    ReasoningCapability,
    merge_model_info,
)
from app.core.llm_context import LLMContext
from app.providers.custom_openai import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    log_prefix: str = "DeepSeek"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__("deepseek", config)
        self.base_url: str = "https://api.deepseek.com/v1/chat/completions"

    def get_model_info(self, model: str) -> ModelInfo:
        info = super().get_model_info(model)
        if model == "deepseek-reasoner":
            inferred = ModelInfo(
                provider=self.name,
                id=model,
                capabilities=ModelCapabilities(
                    function_call="unsupported",
                    reasoning=ReasoningCapability("toggle"),
                ),
                source="inferred",
            )
            if info.source != "unknown":
                return merge_model_info(info, inferred)
            return inferred
        return info

    def _prepare_payload(
        self, ctx: LLMContext, messages: list[dict[str, Any]], stream: bool, **kwargs
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        headers, payload = super()._prepare_payload(ctx, messages, stream, **kwargs)
        tools = kwargs.get("tools")
        if (
            tools
            and self.get_model_info(ctx.model or "").capabilities.function_call
            == "unsupported"
        ):
            payload.pop("tools", None)
            payload.pop("tool_choice", None)
        return headers, payload
