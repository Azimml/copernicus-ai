from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.core.io import read_json, write_json
from app.services.indexer import FAQ_PATH


def list_faq() -> list[dict]:
    payload = read_json(FAQ_PATH, default={"items": []})
    return payload.get("items", [])


def upsert_faq(item: dict, faq_id: str | None = None) -> dict:
    payload = read_json(FAQ_PATH, default={"items": []})
    items = payload.get("items", [])

    now = datetime.now(timezone.utc).isoformat()
    if faq_id:
        for idx, existing in enumerate(items):
            if existing.get("id") == faq_id:
                updated = {**existing, **item, "id": faq_id, "updated_at": now}
                items[idx] = updated
                write_json(FAQ_PATH, {"items": items})
                return updated

    created = {"id": faq_id or str(uuid4()), **item, "created_at": now, "updated_at": now}
    items.append(created)
    write_json(FAQ_PATH, {"items": items})
    return created


def delete_faq(faq_id: str) -> bool:
    payload = read_json(FAQ_PATH, default={"items": []})
    items = payload.get("items", [])
    new_items = [x for x in items if x.get("id") != faq_id]
    if len(new_items) == len(items):
        return False
    write_json(FAQ_PATH, {"items": new_items})
    return True
