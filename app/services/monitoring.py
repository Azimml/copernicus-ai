"""Runtime monitoring.

Process start time is per-worker but the counters (chat requests, errors,
reindex runs) are queried from the database so the values match across
``uvicorn --workers N``.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from time import monotonic
from threading import RLock

from app.core.db import connect


class RuntimeMonitor:
    def __init__(self) -> None:
        self._lock = RLock()
        self._started_at = datetime.now(timezone.utc)
        self._started_monotonic = monotonic()

    # The legacy increment APIs are no-ops now — counts come from the DB so
    # they're accurate across workers and survive restarts. Kept for API
    # compatibility with the routes layer.
    def inc_chat(self) -> None: ...
    def inc_chat_error(self) -> None: ...
    def inc_chat_stream(self) -> None: ...
    def mark_reindex(self) -> None: ...

    def snapshot(self) -> dict:
        chat_requests = 0
        chat_errors = 0
        reindex_runs = 0
        last_reindex_at = ""
        try:
            with connect() as conn:
                r = conn.execute(
                    "SELECT COUNT(*) AS c FROM analytics_events WHERE event_type='chat'"
                ).fetchone()
                chat_requests = r["c"] if r else 0
                r = conn.execute(
                    "SELECT COUNT(*) AS c FROM analytics_events "
                    "WHERE event_type='chat' AND error <> ''"
                ).fetchone()
                chat_errors = r["c"] if r else 0
                r = conn.execute(
                    "SELECT COUNT(*) AS c FROM reindex_jobs WHERE status='success'"
                ).fetchone()
                reindex_runs = r["c"] if r else 0
                r = conn.execute(
                    "SELECT finished_at FROM reindex_jobs WHERE status='success' "
                    "ORDER BY finished_at DESC LIMIT 1"
                ).fetchone()
                last_reindex_at = (r["finished_at"] if r and r["finished_at"] else "")
        except Exception:
            pass

        return {
            "started_at": self._started_at.isoformat(),
            "uptime_sec": int(monotonic() - self._started_monotonic),
            "pid": os.getpid(),
            "chat_requests": chat_requests,
            "chat_errors": chat_errors,
            "reindex_runs": reindex_runs,
            "last_reindex_at": last_reindex_at,
        }


runtime_monitor = RuntimeMonitor()
