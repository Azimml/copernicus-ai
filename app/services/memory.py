"""Short-term conversation memory.

Backed by SQLite so it's shared across uvicorn workers. Each session keeps
the last ``max_turns * 2`` messages (user + assistant pairs). Older rows are
pruned on every write to keep the table small.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.db import connect


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionMemory:
    def __init__(self, max_turns: int = 8) -> None:
        self._max_turns = max_turns

    @property
    def _cap(self) -> int:
        return self._max_turns * 2

    def get_history(self, session_id: str) -> list[dict[str, str]]:
        if not session_id:
            return []
        with connect() as conn:
            rows = conn.execute(
                "SELECT role, content FROM session_memory WHERE session_id = ? "
                "ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def add_turn(self, session_id: str, role: str, content: str) -> None:
        if not session_id:
            return
        ts = _now_iso()
        with connect() as conn:
            conn.execute(
                "INSERT INTO session_memory (session_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?)",
                (session_id, role, content, ts),
            )
            # Prune older rows so we keep at most ``_cap`` per session.
            conn.execute(
                "DELETE FROM session_memory WHERE session_id = ? AND id NOT IN ("
                "    SELECT id FROM session_memory WHERE session_id = ? "
                "    ORDER BY id DESC LIMIT ?"
                ")",
                (session_id, session_id, self._cap),
            )

    def replace_last_assistant_turn(self, session_id: str, content: str) -> None:
        if not session_id:
            return
        with connect() as conn:
            row = conn.execute(
                "SELECT id FROM session_memory WHERE session_id = ? AND role = 'assistant' "
                "ORDER BY id DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if not row:
                return
            conn.execute(
                "UPDATE session_memory SET content = ? WHERE id = ?",
                (content, row["id"]),
            )

    def clear(self, session_id: str) -> None:
        if not session_id:
            return
        with connect() as conn:
            conn.execute("DELETE FROM session_memory WHERE session_id = ?", (session_id,))
