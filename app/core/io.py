from __future__ import annotations

from pathlib import Path
from typing import Any

import orjson


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return orjson.loads(path.read_bytes())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2))
