from __future__ import annotations

from fastapi import APIRouter

from app.api.endpoints import (
    auth,
    chat,
    memory,
    presets_endpoint,
    profile,
    sessions,
    stream,
)
from app.api.files import router as files_router
from app.api.static import router as static_router

router = APIRouter()

router.include_router(static_router)
router.include_router(files_router)
router.include_router(auth.router)
router.include_router(chat.router)
router.include_router(sessions.router)
router.include_router(profile.router)
router.include_router(memory.router)
router.include_router(stream.router)
router.include_router(presets_endpoint.router)
