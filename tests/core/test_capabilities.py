from app.core.capabilities import (
    EffectiveCapabilities,
    ModelCapabilities,
    ModelInfo,
    ReasoningCapability,
    RequestRequirements,
    normalize_model_metadata,
    omit_images,
    request_needs_vision,
    resolve_effective_capabilities,
)
from app.providers.base import AIProvider


def test_openrouter_metadata_normalizes_modalities_and_tools():
    info = normalize_model_metadata(
        "openrouter",
        {
            "id": "vision-model",
            "architecture": {"input_modalities": ["text", "image"]},
            "supported_parameters": ["tools", "tool_choice", "reasoning_effort"],
        },
    )

    assert info == ModelInfo(
        provider="openrouter",
        id="vision-model",
        capabilities=ModelCapabilities(
            vision="supported",
            function_call="supported",
            reasoning=ReasoningCapability("effort", ("low", "medium", "high")),
        ),
        source="declared",
    )


def test_missing_metadata_stays_unknown():
    info = normalize_model_metadata("custom", {"id": "model"})

    assert info is not None
    assert info.capabilities.vision == "unknown"
    assert info.capabilities.function_call == "unknown"
    assert info.capabilities.reasoning.mode == "unknown"


def test_model_fallback_does_not_inherit_provider_capabilities():
    provider = AIProvider("test")
    provider.capabilities.supports_vision = True
    provider.capabilities.supports_native_fc = True

    info = provider.get_model_info("unlisted-model")

    assert info.source == "unknown"
    assert info.capabilities.vision == "unknown"
    assert info.capabilities.function_call == "unknown"


def test_images_can_be_omitted_without_losing_text():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "describe this"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}},
            ],
        }
    ]

    assert request_needs_vision(messages)
    result = omit_images(messages)
    assert result[0]["content"] == [{"type": "text", "text": "describe this"}]


def test_effective_capabilities_separate_declared_from_request_requirements():
    declared = ModelCapabilities(vision="unsupported", function_call="supported")

    effective = resolve_effective_capabilities(
        declared,
        RequestRequirements(needs_vision=True, needs_function_call=True),
        provider_allows_tools=True,
    )

    assert effective == EffectiveCapabilities(
        vision="unsupported",
        function_call="supported",
        images_included=False,
        tools_included=True,
    )


def test_unknown_vision_fails_closed_but_tools_use_transport_floor():
    effective = resolve_effective_capabilities(
        ModelCapabilities(),
        RequestRequirements(needs_vision=True, needs_function_call=True),
        provider_allows_tools=True,
    )

    assert effective.vision == "unknown"
    assert effective.function_call == "unknown"
    assert effective.images_included is False
    assert effective.tools_included is True


def test_metadata_normalizes_structured_output_image_generation_and_limits():
    info = normalize_model_metadata(
        "provider",
        {
            "id": "multimodal",
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["text", "image"],
            },
            "supported_parameters": ["response_format"],
            "context_length": 128000,
            "max_output_tokens": 4096,
        },
    )

    assert info is not None
    assert info.capabilities.structured_output == "supported"
    assert info.capabilities.image_generation == "supported"
    assert info.limits.context_window == 128000
    assert info.limits.max_output_tokens == 4096
