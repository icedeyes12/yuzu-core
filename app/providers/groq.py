from __future__ import annotations

from typing import Any

from app.providers.custom_openai import OpenAICompatibleProvider


class GroqProvider(OpenAICompatibleProvider):
    log_prefix: str = "Groq"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__("groq", config)
        self.base_url: str = "https://api.groq.com/openai/v1/chat/completions"
