from __future__ import annotations
# FILE: app/api/__init__.py
# DESCRIPTION: API routing package for yuzu-companion web interface

from app.api.main import router as api_router

__all__ = ["api_router"]
