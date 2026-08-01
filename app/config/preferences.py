from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class UserPreferences:
    assistant_name: str = ""
    user_name: str = ""
    persona: str = ""
    theme: str = "default"
    affection: int = 50
    preferred_provider: str = ""
    preferred_model: str = ""
    display_name: str = ""
    partner_name: str = ""
    image_model: str = ""
    model_parameters: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_profile_row(cls, row: dict[str, Any] | None) -> UserPreferences:
        if not row:
            return cls()

        providers_config = row.get("providers_config") or {}
        return cls(
            assistant_name="",
            user_name="",
            persona="",
            theme=row.get("theme") or "default",
            affection=int(row.get("affection") or 50),
            preferred_provider=providers_config.get("preferred_provider") or "",
            preferred_model=providers_config.get("preferred_model") or "",
            display_name=row.get("display_name") or "",
            partner_name=row.get("partner_name") or "",
            image_model=row.get("image_model") or "",
            model_parameters=row.get("model_parameters") or {},
        )

    def to_profile_updates(self) -> dict[str, Any]:
        providers_config: dict[str, Any] = {}
        if self.preferred_provider or self.preferred_model:
            providers_config["preferred_provider"] = self.preferred_provider
            providers_config["preferred_model"] = self.preferred_model

        updates: dict[str, Any] = {
            "theme": self.theme,
            "affection": self.affection,
            "display_name": self.display_name,
            "partner_name": self.partner_name,
            "image_model": self.image_model,
            "model_parameters": self.model_parameters,
        }
        if providers_config:
            updates["providers_config"] = providers_config
        return updates
