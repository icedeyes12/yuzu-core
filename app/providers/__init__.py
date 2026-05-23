from __future__ import annotations

from app.providers.base import AIProviderManager, get_ai_manager, reload_ai_manager
from app.providers.ollama import OllamaProvider
from app.providers.cerebras import CerebrasProvider
from app.providers.openrouter import OpenRouterProvider
from app.providers.chutes import ChutesProvider

# Override load_providers to register actual provider implementations
def load_all_providers(manager: AIProviderManager):
    ollama = OllamaProvider()
    if ollama.test_connection():
        manager.register_provider("ollama", ollama)

    cerebras = CerebrasProvider()
    if cerebras.is_available:
        manager.register_provider("cerebras", cerebras)

    openrouter = OpenRouterProvider()
    if openrouter.is_available:
        manager.register_provider("openrouter", openrouter)

    chutes = ChutesProvider()
    if chutes.is_available:
        manager.register_provider("chutes", chutes)

# Patch the AIProviderManager to use our load function
AIProviderManager.load_providers = load_all_providers

__all__ = ["get_ai_manager", "reload_ai_manager", "AIProviderManager"]
