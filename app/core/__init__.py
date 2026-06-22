# FILE: app/core/__init__.py
# DESCRIPTION: Neutral core layer for cross-cutting primitives that must NOT
#              trigger router/orchestrator initialization on import.
#              Keep this package import-light — no eager endpoint loading.

from __future__ import annotations

__all__: list[str] = []
