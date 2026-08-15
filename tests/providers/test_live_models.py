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
