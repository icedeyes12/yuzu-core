import pytest

from app.providers.image_provider import _chutes_payload


def test_qwen_image_generation_payload_has_no_edit_only_image_field():
    payload = _chutes_payload("qwen-image", "a cat", None)

    assert payload == {
        "prompt": "a cat",
        "seed": 42,
        "width": 1024,
        "height": 1024,
        "true_cfg_scale": 4,
        "negative_prompt": "",
        "num_inference_steps": 30,
    }


def test_qwen_image_edit_payload_requires_image_bytes():
    with pytest.raises(ValueError, match="image_bytes"):
        _chutes_payload("qwen-image-edit", "a cat", None)


def test_qwen_image_edit_payload_contains_image_bytes():
    payload = _chutes_payload("qwen-image-edit", "a cat", b"image")

    assert payload["image_b64s"]
    assert payload["prompt"] == "a cat"
    assert "input_args" not in payload


def test_z_image_generation_payload_is_flat():
    payload = _chutes_payload("z-image-turbo", "a cat", None)

    assert "input_args" not in payload
    assert payload["prompt"] == "a cat"
    assert payload["width"] == 1024
    assert payload["height"] == 1024


def test_legacy_qwen_model_name_has_a_single_canonical_mapping():
    from app.providers.image_provider import IMAGE_MODEL_ALIASES, _provider_for_model

    assert _provider_for_model("qwen-image") == "chutes"
    assert _provider_for_model("qwen_image") is None
    assert IMAGE_MODEL_ALIASES["qwen_image"] == "qwen-image"


if __name__ == "__main__":
    test_qwen_image_generation_payload_has_no_edit_only_image_field()
    test_qwen_image_edit_payload_contains_image_bytes()
    test_z_image_generation_payload_is_flat()
    print("ok")
