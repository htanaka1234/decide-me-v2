from __future__ import annotations

import json
from typing import Any


VOLATILE_KEYS = {
    "generated_at",
    "project_head",
    "last_event_id",
    "tx_id",
}


def normalize_json_snapshot(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: normalize_json_snapshot(item)
            for key, item in sorted(value.items())
            if key not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [normalize_json_snapshot(item) for item in value]
    return value


def stable_json(value: Any) -> str:
    return json.dumps(
        normalize_json_snapshot(value),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
