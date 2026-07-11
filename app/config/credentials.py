from __future__ import annotations

from abc import ABC, abstractmethod


class CredentialProvider(ABC):
    @abstractmethod
    def for_request(self, provider: str) -> str | None:
        raise NotImplementedError

    def is_available(self, provider: str) -> bool:
        return bool(self.for_request(provider))


class EnvCredentialProvider(CredentialProvider):
    def for_request(self, provider: str) -> str | None:
        from app.core.context import resolve_api_key

        return resolve_api_key(provider)
