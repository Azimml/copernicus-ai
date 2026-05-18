from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from app.core.config import RAW_DIR
from app.core.io import read_json, write_json


LOG_PATH = RAW_DIR / "chat_logs.json"
_lock = RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_log(
    *,
    session_id: str,
    channel: str = "web",
    role: str,
    text: str,
    meta: dict | None = None,
) -> dict:
    if not session_id:
        return {}
    entry = {
        "id": str(uuid4()),
        "ts": _now_iso(),
        "session_id": session_id,
        "channel": channel,
        "role": role,
        "text": (text or "")[:4000],
    }
    if isinstance(meta, dict):
        safe_meta: dict[str, object] = {}
        for key, value in meta.items():
            if value is None:
                continue
            safe_key = str(key).strip()[:60]
            if not safe_key:
                continue
            if isinstance(value, bool):
                safe_meta[safe_key] = value
            elif isinstance(value, (int, float)):
                safe_meta[safe_key] = value
            else:
                safe_meta[safe_key] = str(value).strip()[:240]
        if safe_meta:
            entry["meta"] = safe_meta
    with _lock:
        payload = read_json(LOG_PATH, default={"items": []})
        items = payload.get("items", [])
        items.append(entry)
        write_json(LOG_PATH, {"items": items[-5000:]})
    return entry


def list_sessions(limit: int = 200, channel: str | None = None, query: str | None = None) -> list[dict]:
    query_text = (query or "").strip().lower()
    with _lock:
        payload = read_json(LOG_PATH, default={"items": []})
        raw_items = payload.get("items", [])

    sessions: dict[str, dict] = {}
    preview_skip_kinds = {
        "satisfaction_prompt",
        "satisfaction_response",
        "satisfaction_followup",
        "satisfaction_ack",
        "satisfaction_choice",
    }
    for item in raw_items:
        session_id = str(item.get("session_id") or "").strip()
        if not session_id:
            continue
        entry_channel = str(item.get("channel") or "web").strip() or "web"

        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        meta_kind = str(meta.get("kind") or "").strip()
        preview = " ".join(str(item.get("text") or "").split())[:220]
        summary = sessions.get(session_id)
        if not summary:
            sessions[session_id] = {
                "session_id": session_id,
                "channel": entry_channel,
                "started_at": item.get("ts") or "",
                "last_activity_at": item.get("ts") or "",
                "message_count": 1,
                "last_role": str(item.get("role") or ""),
                "preview": "" if meta_kind in preview_skip_kinds else preview,
                "latest_satisfaction": None,
                "latest_satisfaction_at": None,
            }
            if meta_kind == "satisfaction_response" and meta.get("value") in {"yes", "no"}:
                sessions[session_id]["latest_satisfaction"] = str(meta.get("value"))
                sessions[session_id]["latest_satisfaction_at"] = item.get("ts") or ""
            continue

        summary["message_count"] += 1
        summary["last_activity_at"] = item.get("ts") or summary["last_activity_at"]
        summary["last_role"] = str(item.get("role") or summary["last_role"])
        if meta_kind == "satisfaction_response" and meta.get("value") in {"yes", "no"}:
            summary["latest_satisfaction"] = str(meta.get("value"))
            summary["latest_satisfaction_at"] = item.get("ts") or summary.get("latest_satisfaction_at")
        if meta_kind not in preview_skip_kinds:
            summary["preview"] = preview or summary["preview"]

    items = list(sessions.values())
    if query_text:
        items = [
            item
            for item in items
            if query_text in item.get("session_id", "").lower()
            or query_text in item.get("preview", "").lower()
        ]

    items.sort(key=lambda item: item.get("last_activity_at", ""), reverse=True)
    return items[: max(1, min(limit, 500))]


def get_session_log(session_id: str, limit: int = 200) -> list[dict]:
    if not session_id:
        return []
    cap = max(1, min(limit, 500))
    with _lock:
        payload = read_json(LOG_PATH, default={"items": []})
    all_items = payload.get("items", [])
    items = [x for x in all_items if x.get("session_id") == session_id]
    items.sort(key=lambda x: x.get("ts", ""))
    return items[-cap:]
