# FILE: app/api/main.py
# DESCRIPTION: Central router registry for the FastAPI backend.

from __future__ import annotations

from fastapi import APIRouter

from app.api.endpoints import chat, memory, profile, sessions, stream
from app.api.static import router as static_router

router = APIRouter()

router.include_router(static_router)
router.include_router(chat.router)
router.include_router(sessions.router)
router.include_router(profile.router)
router.include_router(memory.router)
router.include_router(stream.router)
