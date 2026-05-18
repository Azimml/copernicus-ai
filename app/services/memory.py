from __future__ import annotations

from collections import defaultdict
from threading import RLock


class SessionMemory:
    def __init__(self, max_turns: int = 8) -> None:
        self._max_turns = max_turns
        self._lock = RLock()
        self._store: dict[str, list[dict[str, str]]] = defaultdict(list)

    def get_history(self, session_id: str) -> list[dict[str, str]]:
        if not session_id:
            return []
        with self._lock:
            return list(self._store.get(session_id, []))

    def add_turn(self, session_id: str, role: str, content: str) -> None:
        if not session_id:
            return
        with self._lock:
            history = self._store.setdefault(session_id, [])
            history.append({"role": role, "content": content})
            if len(history) > self._max_turns * 2:
                self._store[session_id] = history[-self._max_turns * 2 :]

    def replace_last_assistant_turn(self, session_id: str, content: str) -> None:
        if not session_id:
            return
        with self._lock:
            history = self._store.get(session_id)
            if not history:
                return
            for idx in range(len(history) - 1, -1, -1):
                if history[idx].get("role") == "assistant":
                    history[idx] = {"role": "assistant", "content": content}
                    return

    def clear(self, session_id: str) -> None:
        if not session_id:
            return
        with self._lock:
            self._store.pop(session_id, None)
