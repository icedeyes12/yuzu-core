from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SupportState = Literal["supported", "unsupported", "unknown"]
ReasoningMode = Literal["unsupported", "toggle", "effort", "unknown"]


@dataclass(frozen=True)
class ReasoningCapability:
    """(｡•̀ᴗ-)✧"""

    mode: ReasoningMode = "unknown"
    levels: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "levels": list(self.levels)}


@dataclass(frozen=True)
class ModelCapabilities:
    """(｡•̀ᴗ-)✧"""

    text_input: SupportState = "supported"
    vision: SupportState = "unknown"
    function_call: SupportState = "unknown"
    reasoning: ReasoningCapability = field(default_factory=ReasoningCapability)
    image_generation: SupportState = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "text_input": self.text_input,
            "vision": self.vision,
            "function_call": self.function_call,
            "reasoning": self.reasoning.to_dict(),
            "image_generation": self.image_generation,
        }


@dataclass(frozen=True)
class ModelInfo:
    """(｡•̀ᴗ-)✧"""

    provider: str
    id: str
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    source: Literal["declared", "inferred", "unknown"] = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "id": self.id,
            "capabilities": self.capabilities.to_dict(),
            "source": self.source,
        }


def _state(value: Any) -> SupportState:
    if value is True:
        return "supported"
    if value is False:
        return "unsupported"
    return "unknown"


def normalize_model_metadata(
    provider: str,
    metadata: dict[str, Any],
    *,
    provider_tools: bool | None = None,
    provider_vision: bool | None = None,
) -> ModelInfo | None:
    """(｡•̀ᴗ-)✧"""
    model_id = metadata.get("id")
    if not isinstance(model_id, str) or not model_id:
        return None

    architecture = metadata.get("architecture")
    architecture = architecture if isinstance(architecture, dict) else {}
    input_modalities = architecture.get("input_modalities")
    supported_parameters = metadata.get("supported_parameters")
    if not isinstance(supported_parameters, list):
        supported_parameters = []

    vision: SupportState = "unknown"
    if isinstance(input_modalities, list):
        vision = "supported" if "image" in input_modalities else "unsupported"
    elif provider_vision is not None:
        vision = _state(provider_vision)

    function_call: SupportState = "unknown"
    if supported_parameters:
        function_call = (
            "supported"
            if any(p in supported_parameters for p in ("tools", "tool_choice"))
            else "unsupported"
        )
    elif provider_tools is not None:
        function_call = _state(provider_tools)

    reasoning = ReasoningCapability()
    if "reasoning_effort" in supported_parameters:
        reasoning = ReasoningCapability("effort", ("low", "medium", "high"))
    elif "reasoning" in supported_parameters:
        reasoning = ReasoningCapability("toggle")

    source = "declared" if architecture or supported_parameters else "inferred"
    return ModelInfo(
        provider=provider,
        id=model_id,
        capabilities=ModelCapabilities(
            vision=vision,
            function_call=function_call,
            reasoning=reasoning,
        ),
        source=source,
    )


def request_needs_vision(messages: list[dict[str, Any]]) -> bool:
    """(｡•̀ᴗ-)✧"""
    return any(
        isinstance(part, dict) and part.get("type") == "image_url"
        for message in messages
        if isinstance(message.get("content"), list)
        for part in message["content"]
    )


def omit_images(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """(｡•̀ᴗ-)✧"""
    result: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            result.append(message)
            continue
        parts = [part for part in content if part.get("type") != "image_url"]
        result.append(
            {
                **message,
                "content": parts or "[Image omitted: model cannot inspect images.]",
            }
        )
    return result
