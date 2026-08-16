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


class OpenAIProvider(OpenAICompatibleProvider):
    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__("openai", config)
        self.base_url: str = "https://api.openai.com/v1/chat/completions"
        self.models_url: str = "https://api.openai.com/v1/models"

    def get_model_info(self, model: str) -> ModelInfo:
        info = super().get_model_info(model)
        if model.startswith(("o1", "o3", "o4")):
            inferred = ModelInfo(
                provider=self.name,
                id=model,
                capabilities=ModelCapabilities(
                    function_call="unsupported",
                    reasoning=ReasoningCapability("effort", ("low", "medium", "high")),
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
        messages = self._normalize_messages(messages)
        temperature = kwargs.get("temperature")
        max_tokens = kwargs.get("max_tokens")
        top_p = kwargs.get("top_p")

        headers = {
            "Authorization": f"Bearer {self._require_api_key(ctx)}",
            "Content-Type": "application/json",
        }

        # o1/o3/o4 reasoning models don't support system prompt or temperature
        model = ctx.model
        assert model is not None
        is_reasoning = (
            self.get_model_info(model).capabilities.reasoning.mode != "unknown"
        )
        if is_reasoning:
            messages = [m for m in messages if m.get("role") != "system"]
            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": stream,
            }
        else:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": top_p,
                "stream": stream,
            }

        effort = kwargs.get("reasoning_effort")
        reasoning = self.get_model_info(model).capabilities.reasoning
        if reasoning.mode == "effort" and effort in reasoning.levels:
            payload["reasoning_effort"] = effort

        tools = kwargs.get("tools")
        if tools and not is_reasoning:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        return headers, payload
