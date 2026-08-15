import pytest

from app.providers.openrouter import OpenRouterProvider


@pytest.mark.asyncio
async def test_connection_uses_discovery_when_catalog_is_empty():
    provider = OpenRouterProvider()

    async def discover(api_key=None):
        return ["model"]

    provider.fetch_live_models = discover

    assert await provider.test_connection()


@pytest.mark.asyncio
async def test_connection_without_discovery_uses_cached_models():
    provider = OpenRouterProvider()
    provider.available_models = ["model"]

    assert await provider.test_connection()


@pytest.mark.asyncio
async def test_openrouter_live_models_available():
    p = OpenRouterProvider()
    models = await p.fetch_live_models()
    assert isinstance(models, list)
    assert len(models) > 0
    assert all(isinstance(m, str) for m in models)


@pytest.mark.asyncio
async def test_discovery_contract_supports_cached_provider_without_live_fetcher():
    from app.providers.base import AIProvider, AIProviderManager

    class CachedProvider(AIProvider):
        async def get_models(self):
            return ["cached-model"]

    manager = AIProviderManager()
    manager.register_provider("cached", CachedProvider("cached"))

    models, infos = await manager.discover_provider_models("cached")

    assert models == ["cached-model"]
    assert infos[0]["id"] == "cached-model"
    assert infos[0]["source"] == "unknown"


@pytest.mark.asyncio
async def test_discovery_contract_normalizes_live_and_returns_model_infos():
    from app.providers.base import AIProviderManager

    class LiveProvider(OpenRouterProvider):
        async def fetch_live_models(self, api_key=None):
            self.set_model_metadata(
                [
                    {
                        "id": "vision-model",
                        "architecture": {"input_modalities": ["text", "image"]},
                    }
                ]
            )
            self.available_models = ["vision-model"]
            return self.available_models

    manager = AIProviderManager()
    manager.register_provider("live", LiveProvider())

    models, infos = await manager.discover_provider_models("live", api_key="key")

    assert models == ["vision-model"]
    assert infos[0]["capabilities"]["vision"] == "supported"
