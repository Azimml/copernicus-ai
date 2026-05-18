from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from app.core.db import connect


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
    log_id = str(uuid4())
    ts = _now_iso()
    text = (text or "")[:4000]

    safe_meta: dict[str, object] = {}
    if isinstance(meta, dict):
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
    meta_json = json.dumps(safe_meta) if safe_meta else None

    with connect() as conn:
        conn.execute(
            "INSERT INTO chat_logs (id, ts, session_id, channel, role, text, meta_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (log_id, ts, session_id, channel, role, text, meta_json),
        )

    entry = {
        "id": log_id,
        "ts": ts,
        "session_id": session_id,
        "channel": channel,
        "role": role,
        "text": text,
    }
    if safe_meta:
        entry["meta"] = safe_meta
    return entry


def list_sessions(limit: int = 200, channel: str | None = None, query: str | None = None) -> list[dict]:
    query_text = (query or "").strip().lower()
    cap = max(1, min(limit, 500))

    preview_skip_kinds = {
        "satisfaction_prompt",
        "satisfaction_response",
        "satisfaction_followup",
        "satisfaction_ack",
        "satisfaction_choice",
    }

    # Pull every row for known sessions. Cheaper than per-session subqueries
    # while we're at tens of thousands of rows.
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, ts, session_id, channel, role, text, meta_json FROM chat_logs ORDER BY ts ASC"
        ).fetchall()

    sessions: dict[str, dict] = {}
    for row in rows:
        sid = row["session_id"]
        if not sid:
            continue
        entry_channel = row["channel"] or "web"
        if channel in {"web"} and entry_channel != channel:
            continue

        try:
            meta = json.loads(row["meta_json"]) if row["meta_json"] else {}
        except Exception:
            meta = {}
        meta_kind = str(meta.get("kind") or "").strip() if isinstance(meta, dict) else ""

        preview = " ".join((row["text"] or "").split())[:220]

        summary = sessions.get(sid)
        if not summary:
            sessions[sid] = {
                "session_id": sid,
                "channel": entry_channel,
                "started_at": row["ts"] or "",
                "last_activity_at": row["ts"] or "",
                "message_count": 1,
                "last_role": row["role"] or "",
                "preview": "" if meta_kind in preview_skip_kinds else preview,
                "latest_satisfaction": None,
                "latest_satisfaction_at": None,
            }
            if meta_kind == "satisfaction_response" and meta.get("value") in {"yes", "no"}:
                sessions[sid]["latest_satisfaction"] = str(meta.get("value"))
                sessions[sid]["latest_satisfaction_at"] = row["ts"] or ""
            continue

        summary["message_count"] += 1
        summary["last_activity_at"] = row["ts"] or summary["last_activity_at"]
        summary["last_role"] = row["role"] or summary["last_role"]
        if meta_kind == "satisfaction_response" and meta.get("value") in {"yes", "no"}:
            summary["latest_satisfaction"] = str(meta.get("value"))
            summary["latest_satisfaction_at"] = row["ts"] or summary.get("latest_satisfaction_at")
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
    return items[:cap]


def get_session_log(session_id: str, limit: int = 200) -> list[dict]:
    if not session_id:
        return []
    cap = max(1, min(limit, 500))
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, ts, session_id, channel, role, text, meta_json FROM chat_logs "
            "WHERE session_id = ? ORDER BY ts ASC LIMIT ?",
            (session_id, cap),
        ).fetchall()
    out: list[dict] = []
    for row in rows:
        item = {
            "id": row["id"],
            "ts": row["ts"],
            "session_id": row["session_id"],
            "channel": row["channel"],
            "role": row["role"],
            "text": row["text"],
        }
        if row["meta_json"]:
            try:
                item["meta"] = json.loads(row["meta_json"])
            except Exception:
                pass
        out.append(item)
    return out
