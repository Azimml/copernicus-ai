from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from app.core.config import RAW_DIR
from app.core.io import read_json, write_json


LINK_RULES_PATH = RAW_DIR / "link_rules.json"
_lock = RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(text: str) -> str:
    return "".join(ch for ch in (text or "").lower().replace("'", "").replace("’", "") if ch.isalnum())


def list_link_rules() -> list[dict]:
    with _lock:
        payload = read_json(LINK_RULES_PATH, default={"items": []})
    items = payload.get("items", [])
    if not isinstance(items, list):
        return []
    return list(reversed(items))


def upsert_link_rule(item: dict, rule_id: str | None = None) -> dict:
    now = _now_iso()
    payload_item = {
        "question_pattern": str(item.get("question_pattern") or "").strip()[:200],
        "mode": "disable" if str(item.get("mode") or "") == "disable" else "manual",
        "url": str(item.get("url") or "").strip()[:1000],
        "note": str(item.get("note") or "").strip()[:400],
        "enabled": bool(item.get("enabled", True)),
    }
    with _lock:
        payload = read_json(LINK_RULES_PATH, default={"items": []})
        items = payload.get("items", [])
        if rule_id:
            for idx, existing in enumerate(items):
                if existing.get("id") != rule_id:
                    continue
                updated = {
                    **existing,
                    **payload_item,
                    "id": rule_id,
                    "updated_at": now,
                }
                items[idx] = updated
                write_json(LINK_RULES_PATH, {"items": items})
                return updated

        created = {
            "id": rule_id or str(uuid4()),
            **payload_item,
            "created_at": now,
            "updated_at": now,
        }
        items.append(created)
        write_json(LINK_RULES_PATH, {"items": items})
        return created


def delete_link_rule(rule_id: str) -> bool:
    with _lock:
        payload = read_json(LINK_RULES_PATH, default={"items": []})
        items = payload.get("items", [])
        new_items = [it for it in items if it.get("id") != rule_id]
        if len(new_items) == len(items):
            return False
        write_json(LINK_RULES_PATH, {"items": new_items})
    return True


def find_matching_link_rule(question: str) -> dict | None:
    q_norm = _normalize(question)
    if not q_norm:
        return None
    with _lock:
        payload = read_json(LINK_RULES_PATH, default={"items": []})
    best: dict | None = None
    best_len = -1
    for item in payload.get("items", []):
        if not item.get("enabled", True):
            continue
        pattern = str(item.get("question_pattern") or "").strip()
        if not pattern:
            continue
        p_norm = _normalize(pattern)
        if not p_norm or p_norm not in q_norm:
            continue
        if len(p_norm) > best_len:
            best = item
            best_len = len(p_norm)
    return best
