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
    structured_output: SupportState = "unknown"
    reasoning: ReasoningCapability = field(default_factory=ReasoningCapability)
    image_generation: SupportState = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "text_input": self.text_input,
            "vision": self.vision,
            "function_call": self.function_call,
            "structured_output": self.structured_output,
            "reasoning": self.reasoning.to_dict(),
            "image_generation": self.image_generation,
        }


@dataclass(frozen=True)
class ModelLimits:
    """(｡•̀ᴗ-)✧"""

    context_window: int | None = None
    max_output_tokens: int | None = None

    def to_dict(self) -> dict[str, int | None]:
        return {
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
        }


@dataclass(frozen=True)
class RequestRequirements:
    """(｡•̀ᴗ-)✧"""

    needs_vision: bool = False
    needs_function_call: bool = False


@dataclass(frozen=True)
class EffectiveCapabilities:
    """(｡•̀ᴗ-)✧"""

    vision: SupportState
    function_call: SupportState
    images_included: bool
    tools_included: bool


@dataclass(frozen=True)
class ModelInfo:
    """(｡•̀ᴗ-)✧"""

    provider: str
    id: str
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    limits: ModelLimits = field(default_factory=ModelLimits)
    source: Literal["declared", "inferred", "unknown"] = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "id": self.id,
            "capabilities": self.capabilities.to_dict(),
            "limits": self.limits.to_dict(),
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

    output_modalities = metadata.get("output_modalities")
    if not isinstance(output_modalities, list):
        output_modalities = architecture.get("output_modalities")
    if not isinstance(output_modalities, list):
        output_modalities = []

    reasoning = ReasoningCapability()
    if "reasoning_effort" in supported_parameters:
        reasoning = ReasoningCapability("effort", ("low", "medium", "high"))
    elif "reasoning" in supported_parameters:
        reasoning = ReasoningCapability("toggle")

    structured_output: SupportState = "unknown"
    if (
        "response_format" in supported_parameters
        or "structured_outputs" in supported_parameters
    ):
        structured_output = "supported"

    context_window = metadata.get("context_length") or metadata.get("context_window")
    max_output_tokens = metadata.get("max_output") or metadata.get("max_output_tokens")
    limits = ModelLimits(
        context_window=context_window if isinstance(context_window, int) else None,
        max_output_tokens=max_output_tokens
        if isinstance(max_output_tokens, int)
        else None,
    )
    source = (
        "declared"
        if architecture or supported_parameters or limits != ModelLimits()
        else "unknown"
    )
    return ModelInfo(
        provider=provider,
        id=model_id,
        capabilities=ModelCapabilities(
            vision=vision,
            function_call=function_call,
            structured_output=structured_output,
            reasoning=reasoning,
            image_generation=(
                "supported" if "image" in output_modalities else "unknown"
            ),
        ),
        limits=limits,
        source=source,
    )


def resolve_effective_capabilities(
    declared: ModelCapabilities,
    requirements: RequestRequirements,
    *,
    provider_allows_tools: bool = False,
) -> EffectiveCapabilities:
    """(｡•̀ᴗ-)✧"""
    function_call = declared.function_call
    tools_included = function_call != "unsupported" and (
        function_call != "unknown" or provider_allows_tools
    )
    return EffectiveCapabilities(
        vision=declared.vision,
        function_call=function_call,
        images_included=not requirements.needs_vision or declared.vision == "supported",
        tools_included=not requirements.needs_function_call or tools_included,
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
