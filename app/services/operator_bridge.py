from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from app.core.config import RAW_DIR
from app.core.io import read_json, write_json


OUTBOX_PATH = RAW_DIR / "operator_outbox.json"
_lock = RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def enqueue_operator_message(session_id: str, message: str, operator_name: str = "Operator") -> dict:
    if not session_id:
        return {}
    with _lock:
        payload = read_json(OUTBOX_PATH, default={"items": {}})
        items = payload.get("items", {})
        queue = items.get(session_id, [])
        msg = {
            "id": str(uuid4()),
            "role": "operator",
            "operator_name": operator_name,
            "text": message[:4000],
            "created_at": _now_iso(),
        }
        queue.append(msg)
        items[session_id] = queue
        write_json(OUTBOX_PATH, {"items": items})
    return msg


def list_operator_messages(session_id: str, after_id: str | None = None, limit: int = 100) -> list[dict]:
    if not session_id:
        return []
    with _lock:
        payload = read_json(OUTBOX_PATH, default={"items": {}})
        items = payload.get("items", {})
        queue = items.get(session_id, [])
    if not isinstance(queue, list):
        return []
    if after_id:
        idx = -1
        for i, m in enumerate(queue):
            if m.get("id") == after_id:
                idx = i
                break
        if idx >= 0:
            queue = queue[idx + 1 :]
    return queue[: max(1, min(limit, 200))]
