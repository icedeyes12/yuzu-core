from __future__ import annotations

import threading
import os
from collections import defaultdict


class Metrics:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._lock = threading.Lock()
        self._requests = 0
        self._active = 0
        self._durations: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._statuses: dict[tuple[str, str, int], int] = defaultdict(int)

    def request_started(self) -> None:
        with self._lock:
            self._requests += 1
            self._active += 1

    def request_finished(
        self, method: str, path: str, status: int, duration: float
    ) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)
            key = (method, path)
            self._durations[key].append(duration)
            self._durations[key] = self._durations[key][-1000:]
            self._statuses[(method, path, status)] += 1

    def render(self) -> tuple[str, str]:
        if not self.enabled:
            return "", "text/plain; version=0.0.4; charset=utf-8"
        lines = [
            "# HELP yuzu_http_requests_total Total HTTP requests.",
            "# TYPE yuzu_http_requests_total counter",
            f"yuzu_http_requests_total {self._requests}",
            "# HELP yuzu_http_active_requests Active HTTP requests.",
            "# TYPE yuzu_http_active_requests gauge",
            f"yuzu_http_active_requests {self._active}",
        ]
        with self._lock:
            for (method, path, status), count in sorted(self._statuses.items()):
                lines.append(
                    f'yuzu_http_responses_total{{method="{method}",path="{path}",status="{status}"}} {count}'
                )
            for (method, path), durations in sorted(self._durations.items()):
                if durations:
                    lines.append(
                        f'yuzu_http_request_duration_seconds_sum{{method="{method}",path="{path}"}} {sum(durations):.6f}'
                    )
                    lines.append(
                        f'yuzu_http_request_duration_seconds_count{{method="{method}",path="{path}"}} {len(durations)}'
                    )
        return "\n".join(lines) + "\n", "text/plain; version=0.0.4; charset=utf-8"


metrics = Metrics(enabled=os.environ.get("YUZU_METRICS_ENABLED", "false").lower() == "true")
