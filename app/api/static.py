from __future__ import annotations

import os
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/static", tags=["static"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent


@router.get("/uploads/{filename}")
async def serve_uploaded_image(filename: str):
    try:
        uploads_dir = (BASE_DIR / "static" / "uploads").resolve()
        file_path = (uploads_dir / filename).resolve()

        if not str(file_path).startswith(str(uploads_dir) + os.sep):
            raise HTTPException(status_code=404, detail="Image not found")
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        raise HTTPException(status_code=404, detail="Image not found")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")


@router.get("/generated_images/{filename}")
async def serve_generated_image(filename: str):
    try:
        generated_dir = (BASE_DIR / "static" / "generated_images").resolve()
        file_path = (generated_dir / filename).resolve()

        if not str(file_path).startswith(str(generated_dir) + os.sep):
            raise HTTPException(status_code=404, detail="Image not found")
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        raise HTTPException(status_code=404, detail="Image not found")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")
