from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.core.db import connect


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def enqueue_operator_message(session_id: str, message: str, operator_name: str = "Operator") -> dict:
    if not session_id:
        return {}
    msg_id = str(uuid4())
    ts = _now_iso()
    text = (message or "")[:4000]
    with connect() as conn:
        conn.execute(
            "INSERT INTO operator_outbox (id, session_id, role, operator_name, text, created_at) "
            "VALUES (?, ?, 'operator', ?, ?, ?)",
            (msg_id, session_id, operator_name, text, ts),
        )
    return {
        "id": msg_id,
        "role": "operator",
        "operator_name": operator_name,
        "text": text,
        "created_at": ts,
    }


def list_operator_messages(session_id: str, after_id: str | None = None, limit: int = 100) -> list[dict]:
    if not session_id:
        return []
    cap = max(1, min(limit, 200))

    with connect() as conn:
        if after_id:
            row = conn.execute(
                "SELECT created_at FROM operator_outbox WHERE id = ? AND session_id = ?",
                (after_id, session_id),
            ).fetchone()
            if row:
                cursor_ts = row["created_at"]
                rows = conn.execute(
                    "SELECT id, role, operator_name, text, created_at FROM operator_outbox "
                    "WHERE session_id = ? AND created_at > ? "
                    "ORDER BY created_at ASC LIMIT ?",
                    (session_id, cursor_ts, cap),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, role, operator_name, text, created_at FROM operator_outbox "
                    "WHERE session_id = ? ORDER BY created_at ASC LIMIT ?",
                    (session_id, cap),
                ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, role, operator_name, text, created_at FROM operator_outbox "
                "WHERE session_id = ? ORDER BY created_at ASC LIMIT ?",
                (session_id, cap),
            ).fetchall()

    return [
        {
            "id": r["id"],
            "role": r["role"],
            "operator_name": r["operator_name"],
            "text": r["text"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
