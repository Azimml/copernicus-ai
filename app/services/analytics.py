from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.db import connect


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
    ts = _now_iso()
    with connect() as conn:
        conn.execute(
            "INSERT INTO analytics_events (ts, channel, language, session_id, message, "
            "needs_human, confidence, latency_ms, error, event_type, satisfaction) "
            "VALUES (?, 'web', 'en', ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ts,
                session_id or "",
                (message or "")[:400],
                1 if needs_human else 0,
                confidence,
                latency_ms,
                (error or "")[:500],
                (event_type or "chat")[:40],
                (satisfaction or "")[:20],
            ),
        )


def build_summary(days: int = 0) -> dict[str, Any]:
    with connect() as conn:
        if days and days > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
            chat_rows = conn.execute(
                "SELECT * FROM analytics_events WHERE ts >= ? AND event_type != 'satisfaction'",
                (cutoff,),
            ).fetchall()
            sat_rows = conn.execute(
                "SELECT * FROM analytics_events WHERE ts >= ? AND event_type = 'satisfaction'",
                (cutoff,),
            ).fetchall()
        else:
            chat_rows = conn.execute(
                "SELECT * FROM analytics_events WHERE event_type != 'satisfaction'"
            ).fetchall()
            sat_rows = conn.execute(
                "SELECT * FROM analytics_events WHERE event_type = 'satisfaction'"
            ).fetchall()

    if not chat_rows and not sat_rows:
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

    session_ids = [r["session_id"] for r in chat_rows if r["session_id"]]
    unique_sessions = len(set(session_ids))
    top_questions = Counter((r["message"] or "").strip() for r in chat_rows if r["message"])
    satisfaction_counts = Counter(
        r["satisfaction"] for r in sat_rows if r["satisfaction"] in {"yes", "no"}
    )
    lats = [int(r["latency_ms"]) for r in chat_rows if r["latency_ms"] is not None]
    avg_latency = int(sum(lats) / len(lats)) if lats else 0
    needs_human_count = sum(1 for r in chat_rows if r["needs_human"])
    error_count = sum(1 for r in chat_rows if r["error"])

    return {
        "window_days": days,
        "total_messages": len(chat_rows),
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
