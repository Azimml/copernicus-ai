"""One-shot migration: copy legacy JSON state into SQLite.

Idempotent — re-running won't duplicate rows. Safe to run on a fresh install
too (the legacy JSON files won't exist and it'll just exit).

Migrates:
- data/raw/chat_logs.json        -> chat_logs table
- data/raw/handoffs.json         -> handoffs + handoff_messages tables
- data/raw/operator_outbox.json  -> operator_outbox table
- data/analytics/events.jsonl    -> analytics_events table

The JSON files are left in place after migration; delete them manually
once you've verified the new SQLite data looks correct.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import DATA_DIR
from app.core.db import init as db_init, connect


def migrate_chat_logs() -> int:
    src = DATA_DIR / "raw" / "chat_logs.json"
    if not src.exists():
        return 0
    payload = json.loads(src.read_bytes())
    items = payload.get("items", []) if isinstance(payload, dict) else []
    n = 0
    with connect() as conn:
        for item in items:
            log_id = item.get("id")
            if not log_id:
                continue
            row = conn.execute("SELECT 1 FROM chat_logs WHERE id = ?", (log_id,)).fetchone()
            if row:
                continue
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else None
            conn.execute(
                "INSERT INTO chat_logs (id, ts, session_id, channel, role, text, meta_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    log_id,
                    item.get("ts", ""),
                    item.get("session_id", ""),
                    item.get("channel", "web"),
                    item.get("role", ""),
                    (item.get("text") or "")[:4000],
                    json.dumps(meta) if meta else None,
                ),
            )
            n += 1
    return n


def migrate_handoffs() -> int:
    src = DATA_DIR / "raw" / "handoffs.json"
    if not src.exists():
        return 0
    payload = json.loads(src.read_bytes())
    items = payload.get("items", []) if isinstance(payload, dict) else []
    n = 0
    with connect() as conn:
        for item in items:
            hid = item.get("id")
            if not hid:
                continue
            row = conn.execute("SELECT 1 FROM handoffs WHERE id = ?", (hid,)).fetchone()
            if row:
                continue
            contact = item.get("contact") if isinstance(item.get("contact"), dict) else {}
            conn.execute(
                "INSERT INTO handoffs (id, status, channel, session_id, language, user_message, "
                "bot_answer, confidence, reason, contact_json, ai_enabled, created_at, updated_at, "
                "resolved_at, resolution_note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    hid,
                    item.get("status", "open"),
                    item.get("channel", "web"),
                    item.get("session_id", ""),
                    item.get("language", "en"),
                    item.get("user_message", "")[:2000],
                    item.get("bot_answer", "")[:2000],
                    item.get("confidence"),
                    item.get("reason", "")[:300],
                    json.dumps(contact),
                    1 if item.get("ai_enabled", True) else 0,
                    item.get("created_at", ""),
                    item.get("updated_at", ""),
                    item.get("resolved_at", ""),
                    item.get("resolution_note", ""),
                ),
            )
            for msg in item.get("messages") or []:
                conn.execute(
                    "INSERT INTO handoff_messages (handoff_id, role, operator_name, text, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        hid,
                        msg.get("role", "user"),
                        msg.get("operator_name", ""),
                        (msg.get("text") or "")[:4000],
                        msg.get("created_at", ""),
                    ),
                )
            n += 1
    return n


def migrate_operator_outbox() -> int:
    src = DATA_DIR / "raw" / "operator_outbox.json"
    if not src.exists():
        return 0
    payload = json.loads(src.read_bytes())
    items_map = payload.get("items", {}) if isinstance(payload, dict) else {}
    n = 0
    with connect() as conn:
        for session_id, queue in items_map.items():
            if not isinstance(queue, list):
                continue
            for msg in queue:
                msg_id = msg.get("id")
                if not msg_id:
                    continue
                row = conn.execute("SELECT 1 FROM operator_outbox WHERE id = ?", (msg_id,)).fetchone()
                if row:
                    continue
                conn.execute(
                    "INSERT INTO operator_outbox (id, session_id, role, operator_name, text, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        msg_id,
                        session_id,
                        msg.get("role", "operator"),
                        msg.get("operator_name", "Operator"),
                        (msg.get("text") or "")[:4000],
                        msg.get("created_at", ""),
                    ),
                )
                n += 1
    return n


def migrate_analytics() -> int:
    src = DATA_DIR / "analytics" / "events.jsonl"
    if not src.exists():
        return 0
    # No native id in the JSONL — we use (ts, session_id, message, event_type)
    # as a dedup signature so re-running the migration doesn't duplicate.
    n = 0
    with connect() as conn:
        for line in src.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if not isinstance(ev, dict):
                continue
            existing = conn.execute(
                "SELECT 1 FROM analytics_events WHERE ts=? AND session_id=? AND message=? AND event_type=?",
                (
                    ev.get("ts", ""),
                    ev.get("session_id", ""),
                    (ev.get("message") or "")[:400],
                    (ev.get("event_type") or "chat")[:40],
                ),
            ).fetchone()
            if existing:
                continue
            conn.execute(
                "INSERT INTO analytics_events (ts, channel, language, session_id, message, "
                "needs_human, confidence, latency_ms, error, event_type, satisfaction) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ev.get("ts", ""),
                    ev.get("channel", "web"),
                    ev.get("language", "en"),
                    ev.get("session_id", ""),
                    (ev.get("message") or "")[:400],
                    1 if ev.get("needs_human") else 0,
                    ev.get("confidence"),
                    ev.get("latency_ms"),
                    (ev.get("error") or "")[:500],
                    (ev.get("event_type") or "chat")[:40],
                    (ev.get("satisfaction") or "")[:20],
                ),
            )
            n += 1
    return n


def main() -> None:
    db_init()
    a = migrate_chat_logs()
    b = migrate_handoffs()
    c = migrate_operator_outbox()
    d = migrate_analytics()
    print(f"Migrated: {a} chat_logs, {b} handoffs, {c} operator_outbox, {d} analytics_events.")
    print("Source JSON files left in place — delete after verifying the SQLite data.")


if __name__ == "__main__":
    main()
