from __future__ import annotations

from threading import RLock

from app.core.config import RAW_DIR
from app.core.io import read_json, write_json


QUICK_ACTIONS_PATH = RAW_DIR / "quick_actions.json"
_lock = RLock()

_DEFAULT_ITEMS = [
    {
        "id": "quick_1",
        "question": "What does Copernicus Berlin do?",
        "answer": "",
        "enabled": True,
        "sort_order": 1,
    },
    {
        "id": "quick_2",
        "question": "How can I apply for a scholarship?",
        "answer": "",
        "enabled": True,
        "sort_order": 2,
    },
    {
        "id": "quick_3",
        "question": "What Erasmus+ projects are available?",
        "answer": "",
        "enabled": True,
        "sort_order": 3,
    },
    {
        "id": "quick_4",
        "question": "How can I volunteer?",
        "answer": "",
        "enabled": True,
        "sort_order": 4,
    },
]


def _sanitize_item(item: dict, fallback: dict) -> dict:
    return {
        "id": str(item.get("id") or fallback["id"]).strip()[:40] or fallback["id"],
        "question": str(item.get("question") or fallback.get("question") or "").strip()[:200],
        "answer": str(item.get("answer") or "").strip()[:4000],
        "enabled": bool(item.get("enabled", True)),
        "sort_order": int(item.get("sort_order") or fallback.get("sort_order") or 0),
    }


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").strip().casefold().split())


def list_quick_actions() -> list[dict]:
    with _lock:
        payload = read_json(QUICK_ACTIONS_PATH, default={"items": []})
    saved_items = payload.get("items", [])
    saved_by_id = {
        str(item.get("id") or "").strip(): item
        for item in saved_items
        if isinstance(item, dict)
    }

    default_ids = {d["id"] for d in _DEFAULT_ITEMS}
    items = []
    for default_item in _DEFAULT_ITEMS:
        merged = {**default_item, **(saved_by_id.get(default_item["id"]) or {})}
        items.append(_sanitize_item(merged, default_item))

    for saved_item in saved_items:
        if not isinstance(saved_item, dict):
            continue
        item_id = str(saved_item.get("id") or "").strip()
        if item_id and item_id not in default_ids:
            items.append(_sanitize_item(saved_item, saved_item))

    items.sort(key=lambda item: (int(item.get("sort_order") or 0), item.get("id") or ""))
    return items


def save_quick_actions(items: list[dict]) -> list[dict]:
    incoming = {
        str(item.get("id") or "").strip(): item
        for item in items
        if isinstance(item, dict)
    }
    default_ids = {d["id"] for d in _DEFAULT_ITEMS}
    sanitized = []

    for default_item in _DEFAULT_ITEMS:
        merged = {**default_item, **(incoming.get(default_item["id"]) or {})}
        sanitized.append(_sanitize_item(merged, default_item))

    for item_id, item in incoming.items():
        if item_id not in default_ids:
            sanitized.append(_sanitize_item(item, item))

    sanitized.sort(key=lambda x: (int(x.get("sort_order") or 0), x.get("id") or ""))
    with _lock:
        write_json(QUICK_ACTIONS_PATH, {"items": sanitized})
    return sanitized


def list_public_quick_actions() -> list[dict]:
    items: list[dict] = []
    for item in list_quick_actions():
        if not item.get("enabled", True):
            continue
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        items.append(
            {
                "id": item["id"],
                "question": question,
                "action": "message",
            }
        )
    return items


def find_manual_quick_action(message: str) -> dict | None:
    norm_message = _normalize_text(message)
    if not norm_message:
        return None

    for item in list_quick_actions():
        if not item.get("enabled", True):
            continue

        question = str(item.get("question") or "").strip()
        if not question:
            continue
        if _normalize_text(question) != norm_message:
            continue

        answer = str(item.get("answer") or "").strip()
        if not answer:
            return None

        return {
            "id": item["id"],
            "question": question,
            "answer": answer,
        }

    return None
