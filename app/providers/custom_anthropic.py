from __future__ import annotations

from typing import Any

from app.providers.anthropic import AnthropicProvider


class CustomAnthropicProvider(AnthropicProvider):
    log_prefix: str = "CustomAnthropic"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.name = "custom_anthropic"

    async def get_models(self) -> list[str]:
        return await self.fetch_live_models()


__all__ = ["CustomAnthropicProvider"]
