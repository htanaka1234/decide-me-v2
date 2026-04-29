from __future__ import annotations

import csv
from io import StringIO
from typing import Any

from decide_me.documents.model import CSV_DOCUMENT_TYPES


def render_csv_document(model: dict[str, Any]) -> str:
    document_type = model["document_type"]
    if document_type not in CSV_DOCUMENT_TYPES:
        supported = ", ".join(sorted(CSV_DOCUMENT_TYPES))
        raise ValueError(f"CSV export is supported only for: {supported}")
    table = _first_table(model)
    if table is None:
        return ""
    handle = StringIO()
    writer = csv.writer(handle, lineterminator="\n")
    writer.writerow(table.get("columns", []))
    for row in table.get("rows", []):
        writer.writerow(row)
    return handle.getvalue()


def _first_table(model: dict[str, Any]) -> dict[str, Any] | None:
    preferred_section = "risks" if model["document_type"] == "risk-register" else "comparison"
    for section in model.get("sections", []):
        if section.get("id") != preferred_section:
            continue
        for block in section.get("blocks", []):
            if block.get("type") == "table":
                return block
    for section in model.get("sections", []):
        for block in section.get("blocks", []):
            if block.get("type") == "table":
                return block
    return None
