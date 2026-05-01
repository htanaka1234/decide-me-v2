from __future__ import annotations

"""Snapshot normalization for Phase 10 helpers."""

import csv
import json
import re
from io import StringIO
from typing import Any

from decide_me.documents.merge import MARKER_END, MARKER_START_RE


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


def normalize_markdown_snapshot(value: str) -> str:
    text = _normalize_newlines(value)
    start_matches = list(MARKER_START_RE.finditer(text))
    end_matches = list(re.finditer(re.escape(MARKER_END), text))
    if not start_matches and not end_matches:
        return text.strip() + "\n"
    if len(start_matches) != 1:
        raise ValueError("markdown snapshot must contain exactly one decide-me generated start marker")
    if len(end_matches) != 1:
        raise ValueError("markdown snapshot must contain exactly one decide-me generated end marker")
    start_marker = start_matches[0]
    end_marker = end_matches[0]
    if end_marker.start() < start_marker.end():
        raise ValueError("markdown snapshot generated end marker appears before start marker")

    start = start_marker.end()
    if start < len(text) and text[start] == "\n":
        start += 1
    text = text[start:end_marker.start()]
    return text.strip() + "\n"


def normalize_csv_snapshot(value: str) -> str:
    text = _normalize_newlines(value)
    rows = list(csv.reader(StringIO(text)))
    if not rows:
        return ""
    header, data_rows = rows[0], rows[1:]
    handle = StringIO()
    writer = csv.writer(handle, lineterminator="\n")
    writer.writerow(header)
    for row in sorted(data_rows):
        writer.writerow(row)
    return handle.getvalue()


def normalize_snapshot_text(path: str, value: str) -> str:
    if path.endswith(".json"):
        return stable_json(json.loads(value))
    if path.endswith(".md"):
        return normalize_markdown_snapshot(value)
    if path.endswith(".csv"):
        return normalize_csv_snapshot(value)
    return _normalize_newlines(value)


def _normalize_newlines(value: str) -> str:
    return re.sub(r"\r\n?", "\n", value)
