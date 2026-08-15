from app.core.capabilities import (
    ModelCapabilities,
    ReasoningCapability,
    normalize_model_metadata,
)
from app.providers.deepseek import DeepSeekProvider
from app.providers.google import _normalize_google_model
from app.providers.mistral import _normalize_mistral_model
from app.providers.openai import OpenAIProvider


def test_google_native_metadata_maps_real_record_shape():
    record = {
        "name": "models/gemini-2.5-flash",
        "version": "2.5",
        "displayName": "Gemini 2.5 Flash",
        "description": "A real native Gemini model record.",
        "inputTokenLimit": 1048576,
        "outputTokenLimit": 65536,
        "supportedGenerationMethods": ["generateContent", "countTokens"],
    }

    assert _normalize_google_model(record) == {
        "id": "gemini-2.5-flash",
        "context_length": 1048576,
        "max_output_tokens": 65536,
    }


def test_google_native_model_id_is_unchanged_when_already_unprefixed():
    normalized = _normalize_google_model({"name": "gemini-2.5-flash"})
    assert normalized is not None
    assert normalized["id"] == "gemini-2.5-flash"


def test_mistral_native_metadata_maps_declared_capabilities():
    metadata = _normalize_mistral_model(
        {
            "id": "mistral-medium-2505",
            "max_context_length": 131072,
            "capabilities": {
                "vision": True,
                "function_calling": True,
                "reasoning": False,
            },
        }
    )

    assert metadata == {
        "id": "mistral-medium-2505",
        "context_length": 131072,
        "input_modalities": ["text", "image"],
        "supported_parameters": ["tools", "tool_choice"],
        "reasoning_mode": "unsupported",
    }
    info = normalize_model_metadata("mistral", metadata)
    assert info is not None
    assert info.capabilities.vision == "supported"
    assert info.capabilities.function_call == "supported"
    assert info.capabilities.reasoning.mode == "unsupported"
    assert info.limits.context_window == 131072


def test_openai_reasoning_model_uses_provider_boundary_inference():
    provider = OpenAIProvider()

    info = provider.get_model_info("o3-mini")

    assert info.source == "inferred"
    assert info.capabilities.function_call == "unsupported"
    assert info.capabilities.reasoning == ReasoningCapability(
        "effort", ("low", "medium", "high")
    )


def test_deepseek_reasoner_uses_provider_boundary_inference():
    provider = DeepSeekProvider()

    info = provider.get_model_info("deepseek-reasoner")

    assert info.source == "inferred"
    assert info.capabilities == ModelCapabilities(
        function_call="unsupported",
        reasoning=ReasoningCapability("toggle"),
    )


def test_declared_model_metadata_overrides_provider_inference():
    provider = OpenAIProvider()
    provider.set_model_metadata(
        [
            {
                "id": "o3-mini",
                "architecture": {"input_modalities": ["text", "image"]},
                "supported_parameters": ["tools", "reasoning_effort"],
            }
        ]
    )

    info = provider.get_model_info("o3-mini")

    assert info.source == "declared"
    assert info.capabilities.function_call == "supported"
    assert info.capabilities.vision == "supported"
    assert info.capabilities.reasoning == ReasoningCapability(
        "effort", ("low", "medium", "high")
    )
    assert provider.supports_vision("o3-mini")


def test_partial_declared_metadata_keeps_provider_inference():
    provider = OpenAIProvider()
    provider.set_model_metadata([{"id": "o3-mini", "context_length": 200000}])

    info = provider.get_model_info("o3-mini")

    assert info.source == "declared"
    assert info.limits.context_window == 200000
    assert info.capabilities.reasoning == ReasoningCapability(
        "effort", ("low", "medium", "high")
    )
    assert info.capabilities.function_call == "unsupported"


def test_declared_limits_reach_model_info_after_registration():
    provider = OpenAIProvider()
    provider.set_model_metadata(
        [
            {
                "id": "gpt-4o",
                "context_length": 128000,
                "max_output_tokens": 16384,
            }
        ]
    )

    info = provider.get_model_info("gpt-4o")

    assert info.limits.context_window == 128000
    assert info.limits.max_output_tokens == 16384
    assert info.source == "declared"
