from __future__ import annotations

import os
import sys

sys.path.append("/home/workspace/yuzu-companion")


def test_build_messages_returns_list():
    """Smoke test — build_messages is async and needs a DB; just verify import."""
    from app.prompts import build_messages

    assert callable(build_messages)


def test_encode_image_safe_missing_file():
    """_encode_image_safe returns None for non-existent files."""
    from app.prompts import _encode_image_safe

    assert _encode_image_safe("/nonexistent/path.jpg") is None


def test_encode_image_safe_valid(tmp_path=None):
    """_encode_image_safe returns a valid image_url block for a real image."""
    from app.prompts import _encode_image_safe
    from PIL import Image
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        img = Image.new("RGB", (10, 10), color="blue")
        img.save(f, format="PNG")
        path = f.name

    try:
        result = _encode_image_safe(path)
        assert result is not None
        assert result["type"] == "image_url"
        assert "data:image/png;base64," in result["image_url"]["url"]
    finally:
        os.unlink(path)
