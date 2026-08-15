from __future__ import annotations

from typing import Any

from app.providers.custom_openai import OpenAICompatibleProvider


class GrokProvider(OpenAICompatibleProvider):
    log_prefix: str = "Grok"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__("grok", config)
        self.base_url: str = "https://api.x.ai/v1/chat/completions"
