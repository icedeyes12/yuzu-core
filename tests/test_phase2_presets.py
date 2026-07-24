"""Phase 2 round-trip + payload-assertion tests for presets and parameters."""

from __future__ import annotations

from app.core import presets as presets_mod


def test_normalize_presets_idempotent():
    """normalize_presets should return the same list when input is already valid."""
    raw = [
        {"name": "default", "payload": {"temperature": 0.7}, "is_active": True},
        {"name": "creative", "payload": {"temperature": 1.2}, "is_active": False},
    ]
    out = presets_mod.normalize_presets(raw)
    assert len(out) == 2
    assert out[0]["name"] == "default"
    assert out[0]["is_active"] is True


def test_normalize_presets_drops_garbage():
    """Garbage items are silently dropped, no exception escapes."""
    bad = [None, "x", {}, {"name": 42}, {"name": "ok", "payload": "not-a-dict"}]
    out = presets_mod.normalize_presets(bad)
    # Only the well-formed entry survives.
    assert out == [{"name": "ok", "payload": {}, "is_active": False}]


def test_round_trip_preserves_all_fields():
    """Active preset payload must survive normalize -> active -> resolve."""
    ctx = {
        "temperature": 0.5,
        "top_p": 0.9,
        "max_tokens": 2048,
        "top_k": 40,
        "additional_instructions": "be terse",
        "presets": [
            {
                "name": "sharp",
                "payload": {
                    "temperature": 0.3,
                    "top_p": 0.8,
                    "top_k": 20,
                    "max_tokens": 1024,
                    "additional_instructions": "code-only",
                },
                "is_active": True,
            }
        ],
    }
    normalized = presets_mod.normalize_presets(ctx["presets"])
    ctx["presets"] = normalized
    payload = presets_mod.resolve_active_preset_payload(ctx)
    assert payload == normalized[0]["payload"]
    assert payload["additional_instructions"] == "code-only"
    assert payload["top_k"] == 20


def test_no_active_preset_returns_none():
    """If no preset is active, no payload override is applied."""
    ctx = {
        "temperature": 0.7,
        "presets": [{"name": "x", "payload": {}, "is_active": False}],
    }
    assert presets_mod.resolve_active_preset_payload(ctx) is None


def test_multiple_active_keeps_last():
    """If multiple presets are marked active, the last one wins."""
    ctx = {
        "presets": [
            {"name": "a", "payload": {"temperature": 0.1}, "is_active": True},
            {"name": "b", "payload": {"temperature": 0.9}, "is_active": True},
        ]
    }
    payload = presets_mod.resolve_active_preset_payload(ctx)
    assert payload["temperature"] == 0.9


def test_payload_to_parameters_overrides_context():
    """Active preset payload must win over loose context fields at runtime."""
    from app.core.llm_context import LLMContext

    profile = {
        "providers_config": {
            "preferred_provider": "ollama",
            "preferred_model": "glm-4.6:cloud",
        },
        "context": {
            "temperature": 1.5,  # loose
            "top_k": 99,  # loose
            "presets": [
                {
                    "name": "strict",
                    "payload": {"temperature": 0.2, "top_k": 5, "top_p": 0.5},
                    "is_active": True,
                }
            ],
        },
    }
    ctx = LLMContext.from_profile(profile)
    assert ctx.parameters["temperature"] == 0.2
    assert ctx.parameters["top_k"] == 5
    assert ctx.parameters["top_p"] == 0.5
    assert ctx.parameters["_payload_source"] == "preset"
