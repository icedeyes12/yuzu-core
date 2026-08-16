from __future__ import annotations

from app.providers.anthropic import AnthropicProvider
from app.providers.base import (
    AIProviderManager,
    ProviderCapabilities,
    get_ai_manager,
    reload_ai_manager,
)
from app.providers.cerebras import CerebrasProvider
from app.providers.chutes import ChutesProvider
from app.providers.custom_anthropic import CustomAnthropicProvider
from app.providers.custom_openai import CustomOpenAIProvider
from app.providers.deepseek import DeepSeekProvider
from app.providers.google import GoogleProvider
from app.providers.grok import GrokProvider
from app.providers.groq import GroqProvider
from app.providers.mistral import MistralProvider
from app.providers.nvidia_nim import NvidiaNimProvider
from app.providers.openai import OpenAIProvider
from app.providers.openrouter import OpenRouterProvider
from app.providers.yuzu_portal import YuzuPortalProvider


# Override load_providers to register actual provider implementations
async def load_all_providers(manager: AIProviderManager):
    cerebras = CerebrasProvider()
    await cerebras.initialize()
    manager.register_provider("cerebras", cerebras)

    openrouter = OpenRouterProvider()
    await openrouter.initialize()
    manager.register_provider("openrouter", openrouter)

    chutes = ChutesProvider()
    await chutes.initialize()
    manager.register_provider("chutes", chutes)

    openai = OpenAIProvider()
    await openai.initialize()
    manager.register_provider("openai", openai)

    groq = GroqProvider()
    await groq.initialize()
    manager.register_provider("groq", groq)

    deepseek = DeepSeekProvider()
    await deepseek.initialize()
    manager.register_provider("deepseek", deepseek)

    grok = GrokProvider()
    await grok.initialize()
    manager.register_provider("grok", grok)

    anthropic = AnthropicProvider()
    await anthropic.initialize()
    manager.register_provider("anthropic", anthropic)

    custom_openai = CustomOpenAIProvider()
    await custom_openai.initialize()
    manager.register_provider("custom_openai", custom_openai)

    custom_anthropic = CustomAnthropicProvider()
    await custom_anthropic.initialize()
    manager.register_provider("custom_anthropic", custom_anthropic)

    google = GoogleProvider()
    await google.initialize()
    manager.register_provider("google", google)

    mistral = MistralProvider()
    await mistral.initialize()
    manager.register_provider("mistral", mistral)

    nvidia_nim = NvidiaNimProvider()
    await nvidia_nim.initialize()
    manager.register_provider("nvidia_nim", nvidia_nim)

    yuzu_portal = YuzuPortalProvider()
    await yuzu_portal.initialize()
    manager.register_provider("yuzu_portal", yuzu_portal)


# Patch the AIProviderManager to use our load function
# Note: AIProviderManager.initialize calls load_providers()
setattr(AIProviderManager, "load_providers", load_all_providers)

__all__ = [
    "get_ai_manager",
    "reload_ai_manager",
    "AIProviderManager",
    "ProviderCapabilities",
]
