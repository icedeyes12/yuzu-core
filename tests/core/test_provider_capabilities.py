from app.core.capabilities import ModelCapabilities, ReasoningCapability
from app.providers.deepseek import DeepSeekProvider
from app.providers.openai import OpenAIProvider


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
    assert provider.supports_vision("o3-mini")
