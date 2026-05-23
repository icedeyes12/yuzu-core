# FILE: app/api/main.py
# DESCRIPTION: Central router registry for the FastAPI backend.

from __future__ import annotations

from fastapi import APIRouter
from app.api.routes import api_router as legacy_router

# The main router that will hold all sub-routers
router = APIRouter()

# Register sub-routers
from app.api.static import router as static_router
router.include_router(static_router)

# For now, include the legacy router to maintain functionality
router.include_router(legacy_router)
