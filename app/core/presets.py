"""Preset storage helpers — sub-document array inside profile.model_parameters JSONB.

Round-trip contract for Phase 2:
- Storage: ``model_parameters.presets`` is the source of truth.
- Schema: ``[{name, payload, is_active}, ...]`` with at most one ``is_active=True``.
- Active resolution: the most recently set ``is_active`` entry wins (deterministic).
- Sync: ``sync_top_level_with_active()`` mirrors the active preset's payload into
  the legacy top-level model_parameters keys so callers that read raw ``model_parameters["temperature"]``
  still see the active values during the transition window.
- Runtime: ``LLMContext.from_profile`` calls ``resolve_active_preset_payload()`` and
  uses that as the *only* source for runtime parameters, never mixing loose model_parameters
  overrides with preset values.
"""

from __future__ import annotations

from typing import Any

# Fields the user can persist inside a preset payload. All values round-trip through
# JSONB and are coerced in resolve_active_preset_payload().
PRESET_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {
        "temperature",
        "top_p",
        "max_tokens",
        "top_k",
        "additional_instructions",
        "personality_preset",
        "personality_custom",
        "character_profile",
    }
)


def normalize_presets(raw: Any) -> list[dict[str, Any]]:
    """Coerce a stored ``model_parameters.presets`` value to a clean list of dicts.

    Drops entries that are not dicts or that lack a ``name`` / ``payload`` shape.
    Preserves the stored ``is_active`` flag when present.
    The function is idempotent: feeding the result back yields the same value.
    """
    if not raw:
        return []
    if isinstance(raw, str):
        import json

        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        payload = entry.get("payload")
        if not isinstance(name, str) or not name:
            continue
        if not isinstance(payload, dict):
            payload = {}
        cleaned: dict[str, Any] = {
            "name": name,
            "payload": {k: v for k, v in payload.items() if k in PRESET_PAYLOAD_KEYS},
            "is_active": bool(entry.get("is_active", False)),
        }
        out.append(cleaned)
    return out


def list_presets(model_parameters: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return the user's preset list from model parameters."""
    if not model_parameters:
        return []
    return normalize_presets(model_parameters.get("presets"))


def find_active_preset(
    model_parameters: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Find the currently active preset."""
    presets = list_presets(model_parameters)
    if not presets:
        return None
    named = (model_parameters or {}).get("active_preset")
    if isinstance(named, str) and named:
        for entry in presets:
            if entry.get("name") == named:
                return entry
    for entry in reversed(presets):
        if entry.get("is_active"):
            return entry
    return None


def active_preset(model_parameters: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the active preset, or None."""
    return find_active_preset(model_parameters)


def resolve_active_preset_payload(
    model_parameters: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return the active preset payload, or None."""
    entry = find_active_preset(model_parameters)
    if not entry:
        return None
    return dict(entry.get("payload") or {})


def upsert_preset(
    model_parameters: dict[str, Any],
    name: str,
    payload: dict[str, Any],
    *,
    make_active: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Insert or update a preset by name. Returns the new preset list + the target entry."""
    presets = list_presets(model_parameters)
    payload_clean = {
        k: v for k, v in (payload or {}).items() if k in PRESET_PAYLOAD_KEYS
    }
    target: dict[str, Any] | None = None
    for entry in presets:
        if entry.get("name") == name:
            entry["payload"] = payload_clean
            target = entry
            break
    if target is None:
        target = {"name": name, "payload": payload_clean, "is_active": False}
        presets.append(target)
    if make_active:
        for entry in presets:
            entry["is_active"] = entry is target
    return presets, target


def set_active_preset(
    model_parameters: dict[str, Any], name: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Mark the preset with the given name as active. Returns the new list + target entry."""
    presets = list_presets(model_parameters)
    target: dict[str, Any] | None = None
    for entry in presets:
        if entry.get("name") == name:
            target = entry
        entry["is_active"] = False
    if target is not None:
        target["is_active"] = True
    return presets, target


def delete_preset(
    model_parameters: dict[str, Any], name: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Remove the preset with the given name. Returns the new list + removed entry (or None)."""
    presets = list_presets(model_parameters)
    kept: list[dict[str, Any]] = []
    removed: dict[str, Any] | None = None
    for entry in presets:
        if entry.get("name") == name and removed is None:
            removed = entry
            continue
        kept.append(entry)
    return kept, removed


def sync_top_level_with_active(model_parameters: dict[str, Any]) -> dict[str, Any]:
    """Mirror the active preset's payload into top-level model-parameter keys.

    This preserves the active preset values for readers of the model_parameters
    object. Returns the possibly modified model_parameters mapping.
    """
    active = find_active_preset(model_parameters)
    if not active:
        return model_parameters
    payload = active.get("payload") or {}
    for key, value in payload.items():
        model_parameters[key] = value
    model_parameters["active_preset"] = active.get("name")
    return model_parameters


__all__ = [
    "PRESET_PAYLOAD_KEYS",
    "normalize_presets",
    "list_presets",
    "find_active_preset",
    "active_preset",
    "resolve_active_preset_payload",
    "upsert_preset",
    "set_active_preset",
    "delete_preset",
    "sync_top_level_with_active",
]
