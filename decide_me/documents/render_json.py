from __future__ import annotations

import json
from typing import Any


def render_json_document(model: dict[str, Any]) -> str:
    return json.dumps(model, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
