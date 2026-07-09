import pytest

from app.providers.base import AIProviderManager
from app.providers.openrouter import OpenRouterProvider
from app.providers.chutes import ChutesProvider


@pytest.mark.asyncio
async def test_openrouter_live_models_available():
    p = OpenRouterProvider()
    models = await p.fetch_live_models()
    assert isinstance(models, list)
    assert len(models) > 0
    assert all(isinstance(m, str) for m in models)
