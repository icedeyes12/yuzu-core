from __future__ import annotations

import os
from pathlib import Path

from app.core.ids import EntityType, PublicId
from app.db.file_repository import PgFileRepository
from app.services.file_service import FileNotFound, FileService


def get_file_service() -> FileService:
    """ฅ^•ﻌ•^ฅ"""
    root = Path(
        os.environ.get(
            "YUZU_STORAGE_ROOT",
            Path(__file__).resolve().parent.parent.parent / "data",
        )
    )
    return FileService(root, PgFileRepository())


async def resolve_private_file(reference: str, owner_id: str) -> Path | None:
    """ฅ^•ﻌ•^ฅ"""
    marker = "/files/"
    if marker not in reference:
        return None
    try:
        file_id = PublicId.decode(
            EntityType.FILE, reference.rsplit(marker, 1)[1], allow_raw_uuid=False
        )
        _row, path = await get_file_service().open_for_owner(file_id, owner_id)
        return path
    except (ValueError, FileNotFound):
        return None
