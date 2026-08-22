from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api import static


@pytest.mark.asyncio
async def test_legacy_private_file_routes_are_disabled_by_default(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("YUZU_LEGACY_PRIVATE_FILES_ENABLED", raising=False)
    monkeypatch.setattr(static, "BASE_DIR", tmp_path)
    path = tmp_path / "static" / "uploads" / "legacy.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"legacy")

    with pytest.raises(HTTPException) as error:
        await static.serve_uploaded_image("legacy.png", "authenticated-user")

    assert error.value.status_code == 404
