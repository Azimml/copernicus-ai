from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any

import orjson

from app.core.config import ANALYTICS_DIR


EVENTS_PATH = ANALYTICS_DIR / "events.jsonl"
_lock = RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_chat_event(
    *,
    session_id: str | None,
    message: str,
    needs_human: bool = False,
    confidence: float | None = None,
    latency_ms: int | None = None,
    error: str | None = None,
    event_type: str = "chat",
    satisfaction: str | None = None,
) -> None:
    payload = {
        "ts": _now_iso(),
        "channel": "web",
        "language": "en",
        "session_id": session_id or "",
        "message": (message or "")[:400],
        "needs_human": bool(needs_human),
        "confidence": confidence,
        "latency_ms": latency_ms,
        "error": error or "",
        "event_type": (event_type or "chat")[:40],
        "satisfaction": (satisfaction or "")[:20],
    }
    line = orjson.dumps(payload).decode("utf-8")
    with _lock:
        ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
        with EVENTS_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def _iter_events(max_events: int = 20000) -> list[dict[str, Any]]:
    if not EVENTS_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    with _lock:
        lines = EVENTS_PATH.read_text(encoding="utf-8").splitlines()
    for ln in lines[-max_events:]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            row = orjson.loads(ln.encode("utf-8"))
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def build_summary(days: int = 0) -> dict[str, Any]:
    events = _iter_events()
    if not events:
        return {
            "window_days": days,
            "total_messages": 0,
            "unique_sessions": 0,
            "needs_human": 0,
            "error_count": 0,
            "avg_latency_ms": 0,
            "top_questions": [],
            "satisfaction_total": 0,
            "satisfaction_counts": {"yes": 0, "no": 0},
        }

    filtered: list[dict[str, Any]] = []
    if days and days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        for ev in events:
            ts = ev.get("ts")
            try:
                dt = datetime.fromisoformat(ts)
            except Exception:
                continue
            if dt >= cutoff:
                filtered.append(ev)
    else:
        filtered = events

    chat_events = [ev for ev in filtered if str(ev.get("event_type") or "chat") != "satisfaction"]
    satisfaction_events = [ev for ev in filtered if str(ev.get("event_type") or "") == "satisfaction"]

    session_ids = [ev.get("session_id", "") for ev in chat_events if ev.get("session_id")]
    unique_sessions = len(set(session_ids))
    top_questions = Counter((ev.get("message") or "").strip() for ev in chat_events if ev.get("message"))
    satisfaction_counts = Counter(
        ev.get("satisfaction")
        for ev in satisfaction_events
        if ev.get("satisfaction") in {"yes", "no"}
    )
    lats = [int(ev["latency_ms"]) for ev in chat_events if isinstance(ev.get("latency_ms"), int)]
    avg_latency = int(sum(lats) / len(lats)) if lats else 0
    needs_human_count = sum(1 for ev in chat_events if ev.get("needs_human"))
    error_count = sum(1 for ev in chat_events if ev.get("error"))

    return {
        "window_days": days,
        "total_messages": len(chat_events),
        "unique_sessions": unique_sessions,
        "needs_human": needs_human_count,
        "error_count": error_count,
        "avg_latency_ms": avg_latency,
        "top_questions": [{"question": q, "count": c} for q, c in top_questions.most_common(10)],
        "satisfaction_total": int(sum(satisfaction_counts.values())),
        "satisfaction_counts": {
            "yes": int(satisfaction_counts.get("yes", 0)),
            "no": int(satisfaction_counts.get("no", 0)),
        },
    }
