from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.config.preferences import UserPreferences

from app.config.application import ApplicationConfig
from app.config.credentials import CredentialProvider, EnvCredentialProvider
from app.config.preferences import UserPreferences
from app.config.runtime import RuntimeContext


def application_config_from_env() -> ApplicationConfig:
    return ApplicationConfig.from_env()


def user_preferences_from_profile(profile: dict | None) -> UserPreferences:
    return UserPreferences.from_profile_row(profile)


def runtime_context_from_request(
    provider: str,
    model: str,
    request: Any,
    preferences: "UserPreferences | None" = None,
) -> RuntimeContext:
    return RuntimeContext.from_request(provider, model, request, preferences)


def credential_provider() -> CredentialProvider:
    return EnvCredentialProvider()
