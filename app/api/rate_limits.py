from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import HTTPException, Request


class RateLimiter:
    """Small single-process sliding-window and active-work limiter."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._windows: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._active: dict[tuple[str, str], int] = defaultdict(int)

    def allow(
        self, key: str, limit: int, window_seconds: float, policy: str = "default"
    ) -> bool:
        now = self._clock()
        with self._lock:
            window = self._windows[(policy, key)]
            cutoff = now - window_seconds
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= limit:
                return False
            window.append(now)
            return True

    def retry_after(
        self, key: str, window_seconds: float, policy: str = "default"
    ) -> int:
        with self._lock:
            window = self._windows.get((policy, key))
            if not window:
                return 1
            return max(1, int(window[0] + window_seconds - self._clock() + 0.999))

    def acquire_active(self, key: str, limit: int, policy: str = "default") -> bool:
        with self._lock:
            active_key = (policy, key)
            if self._active[active_key] >= limit:
                return False
            self._active[active_key] += 1
            return True

    def release_active(self, key: str, policy: str = "default") -> None:
        with self._lock:
            active_key = (policy, key)
            if self._active[active_key] <= 1:
                self._active.pop(active_key, None)
            else:
                self._active[active_key] -= 1


limiter = RateLimiter()


def get_client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(
    rate_limiter: RateLimiter,
    key: str,
    limit: int,
    window_seconds: float,
    *,
    policy: str = "default",
) -> None:
    if rate_limiter.allow(key, limit, window_seconds, policy):
        return
    retry_after = rate_limiter.retry_after(key, window_seconds, policy)
    raise HTTPException(
        status_code=429,
        detail="Rate limit exceeded",
        headers={"Retry-After": str(retry_after)},
    )


def enforce_active_limit(
    rate_limiter: RateLimiter, key: str, limit: int, *, policy: str
) -> None:
    if rate_limiter.acquire_active(key, limit, policy):
        return
    raise HTTPException(
        status_code=429,
        detail="Too many active requests",
        headers={"Retry-After": "1"},
    )


def user_key(user_id: str) -> str:
    return str(user_id)


def ip_key(request: Request) -> str:
    return get_client_ip(request)


RATE_LIMITER = limiter


def rate_limit_ip(request: Request, limit: int, policy: str) -> None:
    enforce_rate_limit(limiter, ip_key(request), limit, 60, policy=policy)


def rate_limit_user(user_id: str, limit: int, policy: str) -> None:
    enforce_rate_limit(limiter, user_key(user_id), limit, 60, policy=policy)


def acquire_active_user(user_id: str, limit: int, policy: str) -> None:
    enforce_active_limit(limiter, user_key(user_id), limit, policy=policy)


def release_active(user_id: str, policy: str) -> None:
    limiter.release_active(user_key(user_id), policy)
