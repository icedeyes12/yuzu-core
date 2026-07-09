"""Preset storage helpers — sub-document array inside profile.context JSONB.

Round-trip contract for Phase 2:
- Storage: ``context.presets`` is the source of truth.
- Schema: ``[{name, payload, is_active}, ...]`` with at most one ``is_active=True``.
- Active resolution: the most recently set ``is_active`` entry wins (deterministic).
- Sync: ``sync_top_level_with_active()`` mirrors the active preset's payload into
  the legacy top-level context keys so callers that read raw ``context["temperature"]``
  still see the active values during the transition window.
- Runtime: ``LLMContext.from_profile`` calls ``resolve_active_preset_payload()`` and
  uses that as the *only* source for runtime parameters, never mixing loose context
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
        "persona_preset",
        "persona_prompt",
    }
)

_DEFAULT_PRESET: dict[str, Any] = {
    "name": "default",
    "payload": {
        "temperature": 1.0,
        "top_p": 1.0,
        "max_tokens": 4096,
        "top_k": 40,
    },
    "is_active": True,
}


def make_default_preset() -> dict[str, Any]:
    """Return a fresh, mutable copy of the default preset."""
    import copy

    return copy.deepcopy(_DEFAULT_PRESET)


def normalize_presets(raw: Any) -> list[dict[str, Any]]:
    """Coerce a stored ``context.presets`` value to a clean list of dicts.

    Drops entries that are not dicts or that lack a ``name`` / ``payload`` shape.
    Preserves ``is_active`` flag, defaulting to False if missing.
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


def list_presets(ctx: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return the user's preset list from a profile context dict."""
    if not ctx:
        return []
    return normalize_presets(ctx.get("presets"))


def find_active_preset(ctx: dict[str, Any] | None) -> dict[str, Any] | None:
    """Find the preset that is currently active.

    Resolution order:
    1. ctx['active_preset'] name match (authoritative).
    2. Last entry with is_active=True (legacy / upsert path).
    3. None if nothing qualifies.
    """
    presets = list_presets(ctx)
    if not presets:
        return None
    named = (ctx or {}).get("active_preset")
    if isinstance(named, str) and named:
        for entry in presets:
            if entry.get("name") == named:
                return entry
    for entry in reversed(presets):
        if entry.get("is_active"):
            return entry
    return None


def active_preset(ctx: dict[str, Any] | None) -> dict[str, Any] | None:
    """Public alias for find_active_preset — returns the active preset dict, or None."""
    return find_active_preset(ctx)


def resolve_active_preset_payload(ctx: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the active preset's payload, or None if no preset is active.

    Used by LLMContext.from_profile as the *only* source of runtime parameters
    when a preset is active. Loose top-level context values are ignored in that
    case to keep the runtime payload reproducible.
    """
    entry = find_active_preset(ctx)
    if not entry:
        return None
    return dict(entry.get("payload") or {})


def upsert_preset(
    ctx: dict[str, Any],
    name: str,
    payload: dict[str, Any],
    *,
    make_active: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Insert or update a preset by name. Returns the new preset list + the target entry."""
    presets = list_presets(ctx)
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
    ctx: dict[str, Any], name: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Mark the preset with the given name as active. Returns the new list + target entry."""
    presets = list_presets(ctx)
    target: dict[str, Any] | None = None
    for entry in presets:
        if entry.get("name") == name:
            target = entry
        entry["is_active"] = False
    if target is not None:
        target["is_active"] = True
    return presets, target


def delete_preset(
    ctx: dict[str, Any], name: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Remove the preset with the given name. Returns the new list + removed entry (or None)."""
    presets = list_presets(ctx)
    kept: list[dict[str, Any]] = []
    removed: dict[str, Any] | None = None
    for entry in presets:
        if entry.get("name") == name and removed is None:
            removed = entry
            continue
        kept.append(entry)
    return kept, removed


def sync_top_level_with_active(ctx: dict[str, Any]) -> dict[str, Any]:
    """Mirror the active preset's payload into the top-level context keys.

    This keeps older readers (that look at ``context["temperature"]`` directly)
    seeing the active preset's values. Returns the (possibly modified) ctx.
    Idempotent: calling twice yields the same dict.
    """
    active = find_active_preset(ctx)
    if not active:
        return ctx
    payload = active.get("payload") or {}
    for key, value in payload.items():
        ctx[key] = value
    ctx["active_preset"] = active.get("name")
    return ctx


__all__ = [
    "PRESET_PAYLOAD_KEYS",
    "make_default_preset",
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
