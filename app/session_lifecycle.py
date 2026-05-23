# FILE: app/session_lifecycle.py
# DESCRIPTION: Backward-compatible shim for SessionService.
#              Logic migrated to app/services/session_service.py in Phase 3.

from __future__ import annotations
from typing import Any
from app.services.session_service import SessionService

class _NoopContext:
    def __enter__(self) -> "_NoopContext":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

# Public alias retained for any third-party caller that imported UserContext.
UserContext = _NoopContext

def auto_name_session_if_needed(session_id: int, active_session: dict[str, Any]) -> None:
    return SessionService.auto_name_session_if_needed(session_id, active_session)

def start_session(interface: str = "terminal") -> dict[str, Any]:
    return SessionService.start_session(interface)

def end_session_cleanup(
    profile: dict[str, Any],
    interface: str = "terminal",
    unexpected_exit: bool = False,
) -> str:
    return SessionService.end_session_cleanup(profile, interface, unexpected_exit)
