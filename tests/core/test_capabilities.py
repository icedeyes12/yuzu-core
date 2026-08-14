from app.core.capabilities import (
    ModelCapabilities,
    ModelInfo,
    ReasoningCapability,
    normalize_model_metadata,
    omit_images,
    request_needs_vision,
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
