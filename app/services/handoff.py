from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from app.core.config import RAW_DIR
from app.core.io import read_json, write_json
from app.services.chat_log import append_log
from app.services.operator_bridge import enqueue_operator_message


HANDOFFS_PATH = RAW_DIR / "handoffs.json"
_lock = RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_handoffs(status: str | None = None, limit: int = 100) -> list[dict]:
    payload = read_json(HANDOFFS_PATH, default={"items": []})
    items = payload.get("items", [])
    if status in {"open", "resolved"}:
        items = [x for x in items if x.get("status") == status]
    return list(reversed(items))[: max(1, min(limit, 500))]


def get_handoff(handoff_id: str) -> dict | None:
    payload = read_json(HANDOFFS_PATH, default={"items": []})
    for it in payload.get("items", []):
        if it.get("id") == handoff_id:
            return it
    return None


def get_open_handoff(session_id: str) -> dict | None:
    sid = (session_id or "").strip()
    if not sid:
        return None
    payload = read_json(HANDOFFS_PATH, default={"items": []})
    items = payload.get("items", [])
    for idx in range(len(items) - 1, -1, -1):
        item = items[idx]
        if item.get("status") != "open":
            continue
        if item.get("session_id") != sid:
            continue
        return item
    return None


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
    with _lock:
        payload = read_json(HANDOFFS_PATH, default={"items": []})
        items = payload.get("items", [])
        item = {
            "id": str(uuid4()),
            "status": "open",
            "channel": "web",
            "session_id": sid,
            "language": "en",
            "user_message": user_message[:2000],
            "bot_answer": bot_answer[:2000],
            "confidence": confidence,
            "reason": needs_human_reason[:300],
            "created_at": now,
            "updated_at": now,
            "resolved_at": "",
            "resolution_note": "",
            "ai_enabled": bool(ai_enabled),
            "contact": contact_payload,
            "messages": [
                {"role": "user", "text": user_message[:2000], "created_at": now},
                {"role": "assistant", "text": bot_answer[:2000], "created_at": now},
            ],
        }
        items.append(item)
        write_json(HANDOFFS_PATH, {"items": items})
    return item


def resolve_handoff(handoff_id: str, note: str = "") -> dict | None:
    with _lock:
        payload = read_json(HANDOFFS_PATH, default={"items": []})
        items = payload.get("items", [])
        for idx, it in enumerate(items):
            if it.get("id") != handoff_id:
                continue
            updated = {
                **it,
                "status": "resolved",
                "resolved_at": _now_iso(),
                "resolution_note": note[:500],
                "updated_at": _now_iso(),
            }
            items[idx] = updated
            write_json(HANDOFFS_PATH, {"items": items})
            return updated
    return None


def add_operator_reply(handoff_id: str, message: str, operator_name: str = "Operator") -> dict | None:
    text = (message or "").strip()
    if not text:
        return None
    with _lock:
        payload = read_json(HANDOFFS_PATH, default={"items": []})
        items = payload.get("items", [])
        for idx, it in enumerate(items):
            if it.get("id") != handoff_id:
                continue
            now = _now_iso()
            msgs = it.get("messages", [])
            msg = {
                "role": "operator",
                "operator_name": operator_name,
                "text": text[:4000],
                "created_at": now,
            }
            msgs.append(msg)
            updated = {
                **it,
                "messages": msgs[-160:],
                "updated_at": now,
                "ai_enabled": False,
            }
            items[idx] = updated
            write_json(HANDOFFS_PATH, {"items": items})

            session_id = updated.get("session_id", "")
            if session_id:
                enqueue_operator_message(session_id=session_id, message=text, operator_name=operator_name)
                append_log(session_id=session_id, role="operator", text=text)
            return updated
    return None


def set_handoff_ai_enabled(handoff_id: str, ai_enabled: bool) -> dict | None:
    with _lock:
        payload = read_json(HANDOFFS_PATH, default={"items": []})
        items = payload.get("items", [])
        for idx, it in enumerate(items):
            if it.get("id") != handoff_id:
                continue
            updated = {
                **it,
                "ai_enabled": bool(ai_enabled),
                "updated_at": _now_iso(),
            }
            items[idx] = updated
            write_json(HANDOFFS_PATH, {"items": items})
            return updated
    return None


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
    with _lock:
        payload = read_json(HANDOFFS_PATH, default={"items": []})
        items = payload.get("items", [])
        for idx in range(len(items) - 1, -1, -1):
            it = items[idx]
            if it.get("status") != "open" or it.get("session_id") != sid:
                continue
            now = _now_iso()
            msgs = it.get("messages", [])
            msgs.append({"role": "user", "text": body[:2000], "created_at": now})
            updated = {
                **it,
                "user_message": body[:2000],
                "updated_at": now,
                "messages": msgs[-160:],
            }
            items[idx] = updated
            write_json(HANDOFFS_PATH, {"items": items})
            return updated
    return None
