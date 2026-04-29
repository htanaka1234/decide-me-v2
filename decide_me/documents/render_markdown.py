from __future__ import annotations

from typing import Any

from decide_me.exporters.render import render_markdown_list, render_markdown_text, render_table_cell


def render_markdown_document(model: dict[str, Any]) -> str:
    lines = [
        f"# {model['title']}",
        "",
        f"Generated at: {render_markdown_text(model.get('generated_at'))}",
        f"Project head: {render_markdown_text(model.get('project_head'))}",
        f"Document type: {model['document_type']}",
        "",
    ]
    if model.get("warnings"):
        lines.extend(["## Warnings", "", render_markdown_list(model["warnings"]), ""])
    for section in model.get("sections", []):
        lines.extend(_render_section(section))
    return "\n".join(lines).rstrip() + "\n"


def _render_section(section: dict[str, Any]) -> list[str]:
    lines = [f"## {section['title']}", ""]
    blocks = section.get("blocks", [])
    if not blocks:
        return [*lines, "none recorded", ""]
    for block in blocks:
        rendered = _render_block(block)
        if rendered:
            lines.append(rendered)
            lines.append("")
    return lines


def _render_block(block: dict[str, Any]) -> str:
    block_type = block["type"]
    if block_type == "text":
        return render_markdown_text(block.get("text"))
    if block_type == "list":
        return render_markdown_list(block.get("items", []))
    if block_type == "table":
        return _render_table(block.get("columns", []), block.get("rows", []))
    if block_type == "callout":
        severity = block.get("severity") or "note"
        text = render_markdown_text(block.get("text"))
        return f"> **{severity}:** {text}"
    if block_type == "object_refs":
        return render_markdown_list(block.get("object_ids", []))
    raise ValueError(f"unsupported document block type: {block_type}")


def _render_table(columns: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "none recorded"
    header = "| " + " | ".join(render_table_cell(column) for column in columns) + " |"
    separator = "| " + " | ".join("---" for _column in columns) + " |"
    rendered_rows = []
    for row in rows:
        padded = [*row, *([""] * max(0, len(columns) - len(row)))]
        rendered_rows.append("| " + " | ".join(render_table_cell(value) for value in padded[: len(columns)]) + " |")
    return "\n".join([header, separator, *rendered_rows])
