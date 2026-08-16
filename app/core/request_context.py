from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class ClientContext:
    """Resolved client metadata passed to prompt assembly."""

    timezone: str | None = None
    local_time: str | None = None

    def prompt_lines(self) -> list[str]:
        lines: list[str] = []
        if self.timezone:
            lines.append(f"- Client timezone: {self.timezone}")
        if self.local_time:
            lines.append(f"- Client local time: {self.local_time}")
        return lines


_client_context: ContextVar[ClientContext] = ContextVar(
    "client_context", default=ClientContext()
)


def set_client_context(context: ClientContext) -> None:
    _client_context.set(context)


def get_client_context() -> ClientContext:
    return _client_context.get()


def clear_client_context() -> None:
    _client_context.set(ClientContext())
