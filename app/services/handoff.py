from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from app.core.db import connect
from app.services.chat_log import append_log
from app.services import email as email_service


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_handoff(conn, row) -> dict:
    if row is None:
        return None
    try:
        contact = json.loads(row["contact_json"]) if row["contact_json"] else {}
    except Exception:
        contact = {}
    msgs = conn.execute(
        "SELECT role, operator_name, text, created_at FROM handoff_messages "
        "WHERE handoff_id = ? ORDER BY id ASC",
        (row["id"],),
    ).fetchall()
    return {
        "id": row["id"],
        "status": row["status"],
        "channel": row["channel"],
        "session_id": row["session_id"],
        "language": row["language"],
        "user_message": row["user_message"],
        "bot_answer": row["bot_answer"],
        "confidence": row["confidence"],
        "reason": row["reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "resolved_at": row["resolved_at"],
        "resolution_note": row["resolution_note"],
        "ai_enabled": bool(row["ai_enabled"]),
        "contact": contact,
        "messages": [
            {
                "role": m["role"],
                "operator_name": m["operator_name"],
                "text": m["text"],
                "created_at": m["created_at"],
            }
            for m in msgs
        ],
    }


def list_handoffs(status: str | None = None, limit: int = 100) -> list[dict]:
    cap = max(1, min(limit, 500))
    with connect() as conn:
        if status in {"open", "resolved"}:
            rows = conn.execute(
                "SELECT * FROM handoffs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, cap),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM handoffs ORDER BY created_at DESC LIMIT ?", (cap,)
            ).fetchall()
        return [_row_to_handoff(conn, r) for r in rows]


def get_handoff(handoff_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM handoffs WHERE id = ?", (handoff_id,)
        ).fetchone()
        return _row_to_handoff(conn, row) if row else None


def get_open_handoff(session_id: str) -> dict | None:
    sid = (session_id or "").strip()
    if not sid:
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM handoffs WHERE status = 'open' AND session_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (sid,),
        ).fetchone()
        return _row_to_handoff(conn, row) if row else None


def create_handoff(
    *,
    session_id: str | None,
    user_message: str,
    bot_answer: str,
    confidence: float | None = None,
    needs_human_reason: str = "",
    contact: dict | None = None,
    ai_enabled: bool = True,
) -> dict:
    sid = session_id or ""
    now = _now_iso()
    contact_payload = {
        k: str(v).strip()[:300]
        for k, v in (contact or {}).items()
        if str(v or "").strip()
    }
    hid = str(uuid4())
    user_message = (user_message or "")[:2000]
    bot_answer = (bot_answer or "")[:2000]
    needs_human_reason = (needs_human_reason or "")[:300]

    with connect() as conn:
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO handoffs (id, status, channel, session_id, language, user_message, "
            "bot_answer, confidence, reason, contact_json, ai_enabled, created_at, updated_at) "
            "VALUES (?, 'open', 'web', ?, 'en', ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                hid, sid, user_message, bot_answer, confidence,
                needs_human_reason, json.dumps(contact_payload),
                1 if ai_enabled else 0, now, now,
            ),
        )
        conn.execute(
            "INSERT INTO handoff_messages (handoff_id, role, operator_name, text, created_at) "
            "VALUES (?, 'user', '', ?, ?)",
            (hid, user_message, now),
        )
        conn.execute(
            "INSERT INTO handoff_messages (handoff_id, role, operator_name, text, created_at) "
            "VALUES (?, 'assistant', '', ?, ?)",
            (hid, bot_answer, now),
        )
        conn.execute("COMMIT")

    return get_handoff(hid)


def resolve_handoff(handoff_id: str, note: str = "") -> dict | None:
    now = _now_iso()
    with connect() as conn:
        cur = conn.execute(
            "UPDATE handoffs SET status='resolved', resolved_at=?, resolution_note=?, updated_at=? "
            "WHERE id = ?",
            (now, (note or "")[:500], now, handoff_id),
        )
        if cur.rowcount == 0:
            return None
    return get_handoff(handoff_id)


def add_operator_reply(handoff_id: str, message: str, operator_name: str = "Operator") -> dict | None:
    """Send the operator's reply via email to the address on the support form.

    The reply is stored in the handoff message log either way (so the admin
    has a record). If SMTP isn't configured the call still succeeds — the
    reply is logged with a clear "email skipped" marker so admin can see
    that no message left the server.
    """
    text = (message or "").strip()
    if not text:
        return None
    now = _now_iso()

    handoff = get_handoff(handoff_id)
    if not handoff:
        return None

    contact = handoff.get("contact") or {}
    to_email = (contact.get("email") or "").strip()
    to_name = (contact.get("name") or "").strip()
    original_question = handoff.get("user_message") or ""

    # Try to send email first so we can record the outcome alongside the
    # message row. The reply is still saved even if delivery fails.
    if to_email:
        result = email_service.send_operator_reply(
            to_email=to_email,
            to_name=to_name,
            operator_name=operator_name,
            original_question=original_question,
            reply_body=text,
        )
    else:
        result = email_service.EmailResult(ok=False, error="No email address on file for this request")

    if result.ok:
        email_status = "sent"
        email_error = ""
    elif result.skipped:
        email_status = "skipped"
        email_error = result.error
    else:
        email_status = "failed"
        email_error = result.error

    annotated_text = text[:4000]

    with connect() as conn:
        conn.execute(
            "INSERT INTO handoff_messages (handoff_id, role, operator_name, text, created_at) "
            "VALUES (?, 'operator', ?, ?, ?)",
            (handoff_id, operator_name, annotated_text, now),
        )
        conn.execute(
            "UPDATE handoffs SET updated_at=?, ai_enabled=0 WHERE id=?",
            (now, handoff_id),
        )

    session_id = handoff.get("session_id") or ""
    if session_id:
        append_log(
            session_id=session_id,
            role="operator",
            text=text,
            meta={
                "kind": "operator_email_reply",
                "email_status": email_status,
                "email_to": to_email,
                "email_error": email_error,
            },
        )

    # Return the latest handoff plus a small ``last_email`` block so the
    # admin UI can show "✓ Email sent" / "✗ Email failed: …".
    out = get_handoff(handoff_id)
    if out is not None:
        out["last_email"] = {
            "to": to_email,
            "status": email_status,
            "error": email_error,
        }
    return out


def set_handoff_ai_enabled(handoff_id: str, ai_enabled: bool) -> dict | None:
    now = _now_iso()
    with connect() as conn:
        cur = conn.execute(
            "UPDATE handoffs SET ai_enabled=?, updated_at=? WHERE id=?",
            (1 if ai_enabled else 0, now, handoff_id),
        )
        if cur.rowcount == 0:
            return None
    return get_handoff(handoff_id)


def is_ai_enabled_for_session(session_id: str | None) -> bool:
    item = get_open_handoff(session_id or "")
    if not item:
        return True
    return bool(item.get("ai_enabled", True))


def append_user_message_to_open_handoff(
    *,
    session_id: str | None,
    text: str,
) -> dict | None:
    sid = (session_id or "").strip()
    body = (text or "").strip()
    if not sid or not body:
        return None
    body = body[:2000]
    now = _now_iso()
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM handoffs WHERE status='open' AND session_id=? "
            "ORDER BY created_at DESC LIMIT 1",
            (sid,),
        ).fetchone()
        if not row:
            return None
        hid = row["id"]
        conn.execute(
            "INSERT INTO handoff_messages (handoff_id, role, operator_name, text, created_at) "
            "VALUES (?, 'user', '', ?, ?)",
            (hid, body, now),
        )
        conn.execute(
            "UPDATE handoffs SET user_message=?, updated_at=? WHERE id=?",
            (body, now, hid),
        )
    return get_handoff(hid)
