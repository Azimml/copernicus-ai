from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from time import monotonic


class RuntimeMonitor:
    def __init__(self) -> None:
        self._lock = RLock()
        self._started_at = datetime.now(timezone.utc)
        self._started_monotonic = monotonic()
        self._chat_requests = 0
        self._chat_errors = 0
        self._chat_stream_requests = 0
        self._reindex_runs = 0
        self._last_reindex_at = ""

    def inc_chat(self) -> None:
        with self._lock:
            self._chat_requests += 1

    def inc_chat_error(self) -> None:
        with self._lock:
            self._chat_errors += 1

    def inc_chat_stream(self) -> None:
        with self._lock:
            self._chat_stream_requests += 1

    def mark_reindex(self) -> None:
        with self._lock:
            self._reindex_runs += 1
            self._last_reindex_at = datetime.now(timezone.utc).isoformat()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "started_at": self._started_at.isoformat(),
                "uptime_sec": int(monotonic() - self._started_monotonic),
                "chat_requests": self._chat_requests,
                "chat_stream_requests": self._chat_stream_requests,
                "chat_errors": self._chat_errors,
                "reindex_runs": self._reindex_runs,
                "last_reindex_at": self._last_reindex_at,
            }


runtime_monitor = RuntimeMonitor()
