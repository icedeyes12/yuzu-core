from __future__ import annotations

import json
import requests
from typing import Generator
from app.providers.base import AIProvider

class OllamaProvider(AIProvider):
    def __init__(self, config: dict | None = None):
        super().__init__("ollama", config)
        self.base_url = self.config.get("base_url", "http://127.0.0.1:11434")
        self.available_models = [
            "smollm:360m",
            "smollm2:360m",
            "glm-4.6:cloud",
            "qwen3-vl:235b-cloud",
            "qwen3-coder:480b-cloud",
            "kimi-k2:1t-cloud",
            "kimi-k2.5:cloud",
            "gpt-oss:120b-cloud",
            "gpt-oss:20b-cloud",
            "deepseek-v3.1:671b-cloud",
        ]

    def get_models(self) -> list[str]:
        return self.available_models

    def send_message(self, messages: list[dict], model: str, **kwargs) -> str | None:
        if model not in self.available_models:
            return None

        try:
            temperature = kwargs.get("temperature", 0.69)
            top_p = kwargs.get("top_p", 0.7)
            top_k = kwargs.get("top_k", 40)
            typical_p = kwargs.get("typical_p", 0.8)
            num_ctx = kwargs.get("num_ctx", 8192)

            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": top_k,
                    "typical_p": typical_p,
                    "num_ctx": num_ctx,
                },
            }

            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=kwargs.get("timeout", 180),
            )

            if response.status_code == 200:
                result = response.json()
                return result["message"]["content"].strip()
            else:
                return None

        except Exception:
            return None

    def send_message_streaming(
        self, messages: list[dict], model: str, **kwargs
    ) -> Generator[str, None, None]:
        if model not in self.available_models:
            yield ""
            return

        try:
            temperature = kwargs.get("temperature", 0.69)
            top_p = kwargs.get("top_p", 0.7)
            top_k = kwargs.get("top_k", 40)
            typical_p = kwargs.get("typical_p", 0.8)
            num_ctx = kwargs.get("num_ctx", 8192)

            payload = {
                "model": model,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": top_k,
                    "typical_p": typical_p,
                    "num_ctx": num_ctx,
                },
            }

            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=kwargs.get("timeout", 180),
                stream=True,
            )

            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        try:
                            json_data = json.loads(line.decode("utf-8"))
                            if (
                                "message" in json_data
                                and "content" in json_data["message"]
                            ):
                                yield json_data["message"]["content"]
                        except json.JSONDecodeError:
                            continue
            else:
                yield ""

        except Exception as e:
            yield f"Error: {str(e)}"
