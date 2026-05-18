"""SQLite storage layer.

Replaces JSON file storage for everything that's written under concurrent
load (chat logs, handoffs, analytics events, operator outbox, session memory).

Why SQLite:
- Single file, no separate server process to run.
- WAL mode handles many concurrent readers + one writer at a time, which is
  exactly the chatbot's profile (lots of analytics-event appends, few admin
  writes).
- Survives `uvicorn --workers N` because all workers point at the same DB
  file. Session memory becomes worker-agnostic — a follow-up message from
  the same `session_id` finds its history regardless of which worker the
  previous turn hit.
- JSON files are still used for content that's edited by admins infrequently
  (FAQ, quick_actions, link_rules) — they're small, human-readable, and
  hot-reload friendly.

The DB lives at data/copernicus.db (override with COPERNICUS_DB_PATH env var).
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from app.core.config import DATA_DIR

DB_PATH = Path(os.environ.get("COPERNICUS_DB_PATH", DATA_DIR / "copernicus.db"))

_lock = threading.Lock()
_initialized = False

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS chat_logs (
    id          TEXT PRIMARY KEY,
    ts          TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    channel     TEXT NOT NULL DEFAULT 'web',
    role        TEXT NOT NULL,
    text        TEXT NOT NULL,
    meta_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_chat_logs_session ON chat_logs (session_id, ts);
CREATE INDEX IF NOT EXISTS idx_chat_logs_ts ON chat_logs (ts);

CREATE TABLE IF NOT EXISTS handoffs (
    id              TEXT PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'open',
    channel         TEXT NOT NULL DEFAULT 'web',
    session_id      TEXT NOT NULL DEFAULT '',
    language        TEXT NOT NULL DEFAULT 'en',
    user_message    TEXT NOT NULL DEFAULT '',
    bot_answer      TEXT NOT NULL DEFAULT '',
    confidence      REAL,
    reason          TEXT NOT NULL DEFAULT '',
    contact_json    TEXT NOT NULL DEFAULT '{}',
    ai_enabled      INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    resolved_at     TEXT NOT NULL DEFAULT '',
    resolution_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_handoffs_status ON handoffs (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_handoffs_session ON handoffs (session_id, status);

CREATE TABLE IF NOT EXISTS handoff_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    handoff_id      TEXT NOT NULL,
    role            TEXT NOT NULL,
    operator_name   TEXT NOT NULL DEFAULT '',
    text            TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (handoff_id) REFERENCES handoffs (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_handoff_messages ON handoff_messages (handoff_id, created_at);

CREATE TABLE IF NOT EXISTS analytics_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    channel         TEXT NOT NULL DEFAULT 'web',
    language        TEXT NOT NULL DEFAULT 'en',
    session_id      TEXT NOT NULL DEFAULT '',
    message         TEXT NOT NULL DEFAULT '',
    needs_human     INTEGER NOT NULL DEFAULT 0,
    confidence      REAL,
    latency_ms      INTEGER,
    error           TEXT NOT NULL DEFAULT '',
    event_type      TEXT NOT NULL DEFAULT 'chat',
    satisfaction    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_analytics_ts ON analytics_events (ts);
CREATE INDEX IF NOT EXISTS idx_analytics_type ON analytics_events (event_type, ts);

-- Short-term LLM memory, shared across workers.
CREATE TABLE IF NOT EXISTS session_memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_memory ON session_memory (session_id, id);

-- Background reindex job state — survives worker restarts.
CREATE TABLE IF NOT EXISTS reindex_jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    status      TEXT NOT NULL DEFAULT 'pending', -- pending | running | success | failed
    full_crawl  INTEGER NOT NULL DEFAULT 1,
    docs        INTEGER,
    chunks      INTEGER,
    error       TEXT NOT NULL DEFAULT '',
    started_at  TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_reindex_status ON reindex_jobs (status, started_at DESC);
"""


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def init() -> None:
    """Initialize the DB schema. Idempotent."""
    global _initialized
    with _lock:
        if _initialized:
            return
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH, timeout=10.0) as conn:
            _init_db(conn)
        _initialized = True


@contextmanager
def connect():
    """Open a short-lived DB connection. Auto-commits on success.

    SQLite handles concurrent readers + serialized writers natively under WAL
    mode, so we don't need a connection pool — opening a new connection per
    request is cheap (~50us) and avoids cross-thread fd sharing problems.
    """
    if not _initialized:
        init()
    conn = sqlite3.connect(DB_PATH, timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()
