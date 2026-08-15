from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SupportState = Literal["supported", "unsupported", "unknown"]
ReasoningMode = Literal[
    "unsupported",
    "toggle",
    "effort",
    "budget",
    "provider-specific",
    "unknown",
]


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
    input_modalities: tuple[str, ...] = ()
    output_modalities: tuple[str, ...] = ()
    vision: SupportState = "unknown"
    function_call: SupportState = "unknown"
    structured_output: SupportState = "unknown"
    reasoning: ReasoningCapability = field(default_factory=ReasoningCapability)
    image_generation: SupportState = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "text_input": self.text_input,
            "input_modalities": list(self.input_modalities),
            "output_modalities": list(self.output_modalities),
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

    declared_capabilities = metadata.get("capabilities")
    declared_capabilities = (
        declared_capabilities if isinstance(declared_capabilities, dict) else {}
    )
    architecture = metadata.get("architecture")
    architecture = architecture if isinstance(architecture, dict) else {}
    input_modalities = metadata.get("input_modalities")
    if not isinstance(input_modalities, list):
        input_modalities = architecture.get("input_modalities")
    if not isinstance(input_modalities, list):
        if declared_capabilities.get("vision") is True:
            input_modalities = ["text", "image"]
        elif declared_capabilities.get("vision") is False:
            input_modalities = ["text"]
    if not isinstance(input_modalities, list):
        input_modalities = []
    input_modalities = tuple(
        modality for modality in input_modalities if isinstance(modality, str)
    )
    supported_parameters = metadata.get("supported_parameters")
    if not isinstance(supported_parameters, list):
        supported_parameters = []

    vision: SupportState = "unknown"
    if input_modalities:
        vision = "supported" if "image" in input_modalities else "unsupported"
    elif provider_vision is not None:
        vision = _state(provider_vision)

    function_call: SupportState = "unknown"
    declared_function_call = metadata.get("function_calling")
    if declared_function_call is None:
        declared_function_call = declared_capabilities.get("function_calling")
    if declared_function_call is None:
        declared_function_call = declared_capabilities.get("tools")
    if declared_function_call is False:
        function_call = "unsupported"
    elif declared_function_call is True:
        function_call = "supported"
    elif supported_parameters:
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
    if (
        not isinstance(output_modalities, list)
        and declared_capabilities.get("imageOutput") is True
    ):
        output_modalities = ["text", "image"]
    if not isinstance(output_modalities, list):
        output_modalities = []
    output_modalities = tuple(
        modality for modality in output_modalities if isinstance(modality, str)
    )

    reasoning = ReasoningCapability()
    declared_reasoning_mode = metadata.get("reasoning_mode")
    if (
        declared_reasoning_mode is None
        and declared_capabilities.get("reasoning") is False
    ):
        declared_reasoning_mode = "unsupported"
    elif (
        declared_reasoning_mode is None
        and declared_capabilities.get("reasoning") is True
    ):
        declared_reasoning_mode = "toggle"
    if declared_reasoning_mode == "provider-specific":
        reasoning = ReasoningCapability("provider-specific")
    elif declared_reasoning_mode == "unsupported":
        reasoning = ReasoningCapability("unsupported")
    elif declared_reasoning_mode == "toggle":
        reasoning = ReasoningCapability("toggle")
    elif "reasoning_effort" in supported_parameters:
        reasoning = ReasoningCapability("effort", ("low", "medium", "high"))
    elif "reasoning" in supported_parameters:
        reasoning = ReasoningCapability("toggle")

    structured_output: SupportState = "unknown"
    if (
        "response_format" in supported_parameters
        or "structured_outputs" in supported_parameters
    ):
        structured_output = "supported"

    limits_metadata = metadata.get("limits")
    limits_metadata = limits_metadata if isinstance(limits_metadata, dict) else {}
    context_window = (
        metadata.get("context_length")
        or metadata.get("context_window")
        or metadata.get("max_context_length")
        or limits_metadata.get("max_context_length")
        or declared_capabilities.get("contextWindow")
    )
    max_output_tokens = (
        metadata.get("max_output")
        or metadata.get("max_output_tokens")
        or metadata.get("max_completion_tokens")
        or limits_metadata.get("max_completion_tokens")
        or declared_capabilities.get("maxOutput")
    )
    limits = ModelLimits(
        context_window=context_window if isinstance(context_window, int) else None,
        max_output_tokens=max_output_tokens
        if isinstance(max_output_tokens, int)
        else None,
    )
    source = (
        "declared"
        if (
            architecture
            or input_modalities
            or output_modalities
            or supported_parameters
            or limits != ModelLimits()
            or declared_capabilities
        )
        else "unknown"
    )
    return ModelInfo(
        provider=provider,
        id=model_id,
        capabilities=ModelCapabilities(
            input_modalities=input_modalities,
            output_modalities=output_modalities,
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


def merge_model_info(declared: ModelInfo, inferred: ModelInfo) -> ModelInfo:
    """(｡•̀ᴗ-)✧"""
    declared_caps = declared.capabilities
    inferred_caps = inferred.capabilities
    capabilities = ModelCapabilities(
        text_input=(
            declared_caps.text_input
            if declared_caps.text_input != "unknown"
            else inferred_caps.text_input
        ),
        input_modalities=declared_caps.input_modalities
        or inferred_caps.input_modalities,
        output_modalities=declared_caps.output_modalities
        or inferred_caps.output_modalities,
        vision=(
            declared_caps.vision
            if declared_caps.vision != "unknown"
            else inferred_caps.vision
        ),
        function_call=(
            declared_caps.function_call
            if declared_caps.function_call != "unknown"
            else inferred_caps.function_call
        ),
        structured_output=(
            declared_caps.structured_output
            if declared_caps.structured_output != "unknown"
            else inferred_caps.structured_output
        ),
        reasoning=(
            declared_caps.reasoning
            if declared_caps.reasoning.mode != "unknown"
            else inferred_caps.reasoning
        ),
        image_generation=(
            declared_caps.image_generation
            if declared_caps.image_generation != "unknown"
            else inferred_caps.image_generation
        ),
    )
    limits = ModelLimits(
        context_window=declared.limits.context_window or inferred.limits.context_window,
        max_output_tokens=declared.limits.max_output_tokens
        or inferred.limits.max_output_tokens,
    )
    return ModelInfo(
        provider=declared.provider,
        id=declared.id,
        capabilities=capabilities,
        limits=limits,
        source="declared",
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
