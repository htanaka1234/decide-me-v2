from __future__ import annotations

import json
from typing import Any


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    pieces = ["".join(ch for ch in token if ch.isalnum()) for token in lowered.split()]
    return "-".join(piece for piece in pieces if piece) or "decision"


def render_yaml(value: dict[str, Any]) -> str:
    return "\n".join(_render_mapping(value, 0))


def render_markdown_list(values: list[Any]) -> str:
    if not values:
        return "- none recorded"
    return "\n".join(f"- {_markdown_item(value)}" for value in values)


def render_markdown_text(value: Any) -> str:
    if value is None:
        return "none recorded"
    if isinstance(value, str):
        return value.strip() or "none recorded"
    return _markdown_item(value)


def render_table_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, list):
        text = ", ".join(str(item) for item in value)
    elif isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    else:
        text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _render_mapping(value: dict[str, Any], indent: int) -> list[str]:
    lines: list[str] = []
    prefix = " " * indent
    for key, item in value.items():
        if isinstance(item, dict):
            if item:
                lines.append(f"{prefix}{key}:")
                lines.extend(_render_mapping(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {{}}")
        elif isinstance(item, list):
            if item:
                lines.append(f"{prefix}{key}:")
                lines.extend(_render_sequence(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: []")
        else:
            lines.append(f"{prefix}{key}: {_render_scalar(item)}")
    return lines


def _render_sequence(value: list[Any], indent: int) -> list[str]:
    lines: list[str] = []
    prefix = " " * indent
    for item in value:
        if isinstance(item, dict):
            if not item:
                lines.append(f"{prefix}- {{}}")
                continue
            pairs = list(item.items())
            first_key, first_value = pairs[0]
            if isinstance(first_value, dict):
                if first_value:
                    lines.append(f"{prefix}- {first_key}:")
                    lines.extend(_render_mapping(first_value, indent + 4))
                else:
                    lines.append(f"{prefix}- {first_key}: {{}}")
            elif isinstance(first_value, list):
                if first_value:
                    lines.append(f"{prefix}- {first_key}:")
                    lines.extend(_render_sequence(first_value, indent + 4))
                else:
                    lines.append(f"{prefix}- {first_key}: []")
            else:
                lines.append(f"{prefix}- {first_key}: {_render_scalar(first_value)}")
            for key, nested in pairs[1:]:
                lines.extend(_render_mapping({key: nested}, indent + 2))
        elif isinstance(item, list):
            lines.append(f"{prefix}-")
            lines.extend(_render_sequence(item, indent + 2))
        else:
            lines.append(f"{prefix}- {_render_scalar(item)}")
    return lines


def _render_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _markdown_item(value: Any) -> str:
    if isinstance(value, str):
        return value.replace("\n", " ").strip() or "none recorded"
    if value is None:
        return "null"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
