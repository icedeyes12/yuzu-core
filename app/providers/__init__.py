from __future__ import annotations

from app.providers.base import (
    AIProviderManager,
    get_ai_manager,
    reload_ai_manager,
    ProviderCapabilities,
)
from app.providers.ollama import OllamaProvider
from app.providers.cerebras import CerebrasProvider
from app.providers.openrouter import OpenRouterProvider
from app.providers.chutes import ChutesProvider


# Override load_providers to register actual provider implementations
async def load_all_providers(manager: AIProviderManager):
    ollama = OllamaProvider()
    # Initialize each provider so it can load its API key
    await ollama.initialize()
    if await ollama.test_connection():
        manager.register_provider("ollama", ollama)

    cerebras = CerebrasProvider()
    await cerebras.initialize()
    if cerebras.is_available:
        manager.register_provider("cerebras", cerebras)

    openrouter = OpenRouterProvider()
    await openrouter.initialize()
    if openrouter.is_available:
        manager.register_provider("openrouter", openrouter)

    chutes = ChutesProvider()
    await chutes.initialize()
    if chutes.is_available:
        manager.register_provider("chutes", chutes)


# Patch the AIProviderManager to use our load function
# Note: AIProviderManager.initialize calls load_providers()
AIProviderManager.load_providers = load_all_providers

__all__ = [
    "get_ai_manager",
    "reload_ai_manager",
    "AIProviderManager",
    "ProviderCapabilities",
]
