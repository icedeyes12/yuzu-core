"""Process-local registry for active owned PTY sessions. ฅ^•ﻌ•^ฅ"""

from __future__ import annotations

from typing import Protocol


class ClosableSession(Protocol):
    generation: int

    def close(self) -> None: ...


_sessions: dict[str, set[ClosableSession]] = {}


def register(owner_id: str, session: ClosableSession) -> None:
    _sessions.setdefault(owner_id, set()).add(session)


def unregister(owner_id: str, session: ClosableSession) -> None:
    sessions = _sessions.get(owner_id)
    if not sessions:
        return
    sessions.discard(session)
    if not sessions:
        _sessions.pop(owner_id, None)


def close_owner(owner_id: str) -> None:
    for session in tuple(_sessions.pop(owner_id, ())):
        session.close()
