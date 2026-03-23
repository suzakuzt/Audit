from __future__ import annotations

import json
import re
from typing import Any


def load_json_text(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(str(exc)) from exc


def dump_json_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def normalize_text(value: Any) -> str:
    if value is None:
        return ''
    text = str(value).strip()
    return re.sub(r'\s+', ' ', text).lower()
