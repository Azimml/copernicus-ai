"""Background reindex jobs.

The reindex (Playwright crawl + OpenAI embedding) takes 3-5 minutes. Running
it inline blocks the HTTP worker for the duration. Instead we kick off a
daemon thread, record state in a DB row, and the admin UI polls
``/admin/reindex-status`` for progress.

Only one reindex runs at a time — the table is small so a single-row "is
anything running?" query is cheap.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Callable

from app.core.db import connect

logger = logging.getLogger(__name__)

_thread_lock = threading.Lock()
_active_thread: threading.Thread | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_active_job() -> dict | None:
    """Return the most recent pending/running job, or None."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM reindex_jobs WHERE status IN ('pending', 'running') "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def get_latest_job() -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM reindex_jobs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def _create_job(full_crawl: bool) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO reindex_jobs (status, full_crawl, started_at) "
            "VALUES ('pending', ?, ?)",
            (1 if full_crawl else 0, _now_iso()),
        )
        return cur.lastrowid


def _set_status(job_id: int, status: str, **fields) -> None:
    sets = ["status = ?"]
    params: list = [status]
    for k, v in fields.items():
        sets.append(f"{k} = ?")
        params.append(v)
    params.append(job_id)
    with connect() as conn:
        conn.execute(
            f"UPDATE reindex_jobs SET {', '.join(sets)} WHERE id = ?",
            params,
        )


def start_job(full_crawl: bool, on_done: Callable[[int, int], None] | None = None) -> dict:
    """Kick off a reindex in a background thread. Returns the job row.

    Raises RuntimeError if another reindex is already running.
    """
    global _active_thread

    with _thread_lock:
        active = get_active_job()
        if active or (_active_thread and _active_thread.is_alive()):
            raise RuntimeError("Another reindex is already running")

        job_id = _create_job(full_crawl)

        def _run():
            from app.services.indexer import build_index
            _set_status(job_id, "running")
            logger.info("Reindex job %d started (full=%s)", job_id, full_crawl)
            try:
                docs, chunks = build_index(full_crawl=full_crawl)
                _set_status(
                    job_id,
                    "success",
                    docs=docs,
                    chunks=chunks,
                    finished_at=_now_iso(),
                )
                logger.info("Reindex job %d finished: %d docs / %d chunks", job_id, docs, chunks)
                if on_done:
                    try:
                        on_done(docs, chunks)
                    except Exception:
                        logger.exception("reindex on_done callback failed")
            except Exception as exc:
                logger.exception("Reindex job %d failed", job_id)
                _set_status(
                    job_id,
                    "failed",
                    error=str(exc)[:500],
                    finished_at=_now_iso(),
                )

        t = threading.Thread(target=_run, name=f"reindex-{job_id}", daemon=True)
        _active_thread = t
        t.start()

    return get_latest_job()
