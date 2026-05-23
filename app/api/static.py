# FILE: app/api/static.py
# DESCRIPTION: Static file serving endpoints for uploaded and generated images.

from __future__ import annotations

import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/static", tags=["static"])

# Resolve base directory relative to this file
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

@router.get("/uploads/{filename}")
async def serve_uploaded_image(filename: str):
    try:
        uploads_dir = os.path.abspath(os.path.join(BASE_DIR, "static", "uploads"))
        file_path = os.path.abspath(
            os.path.normpath(os.path.join(uploads_dir, filename))
        )
        if not file_path.startswith(uploads_dir + os.sep):
            raise HTTPException(status_code=404, detail="Image not found")
        if os.path.exists(file_path):
            return FileResponse(file_path)
        raise HTTPException(status_code=404, detail="Image not found")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")

@router.get("/generated_images/{filename}")
async def serve_generated_image(filename: str):
    try:
        generated_dir = os.path.abspath(
            os.path.join(BASE_DIR, "static", "generated_images")
        )
        file_path = os.path.abspath(
            os.path.normpath(os.path.join(generated_dir, filename))
        )
        if not file_path.startswith(generated_dir + os.sep):
            raise HTTPException(status_code=404, detail="Image not found")
        if os.path.exists(file_path):
            return FileResponse(file_path)
        raise HTTPException(status_code=404, detail="Image not found")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")
