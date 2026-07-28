from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.context import get_request_keyring


class CredentialProvider(ABC):
    @abstractmethod
    def for_request(self, provider: str) -> str | None:
        raise NotImplementedError

    def is_available(self, provider: str) -> bool:
        return bool(self.for_request(provider))


class EnvCredentialProvider(CredentialProvider):
    def for_request(self, provider: str) -> str | None:
        keyring = get_request_keyring(provider)
        return keyring.key if keyring else None
