from __future__ import annotations

from typing import Any


def render_impact_report(
    template: str,
    impact: dict[str, Any],
    invalidation_candidates: dict[str, Any],
    *,
    max_depth: int | None = None,
    include_low_severity: bool = False,
    include_invalidated: bool = False,
) -> str:
    summary = impact["summary"]
    replacements = {
        "{{ root_object_id }}": impact["root_object_id"],
        "{{ change_kind }}": impact["change_kind"],
        "{{ generated_at }}": impact["generated_at"],
        "{{ max_depth }}": str(max_depth) if max_depth is not None else "unbounded",
        "{{ include_low_severity }}": _render_bool(include_low_severity),
        "{{ include_invalidated }}": _render_bool(include_invalidated),
        "{{ affected_count }}": str(summary["affected_count"]),
        "{{ highest_severity }}": summary["highest_severity"],
        "{{ affected_layers }}": _render_inline_list(summary["affected_layers"]),
        "{{ affected_objects }}": _render_affected_objects(impact["affected_objects"]),
        "{{ invalidation_candidates }}": _render_invalidation_candidates(
            invalidation_candidates["candidates"]
        ),
        "{{ paths }}": _render_paths(impact["paths"]),
    }
    body = template
    for token, value in replacements.items():
        body = body.replace(token, value)
    return body.rstrip()


def _render_affected_objects(affected_objects: list[dict[str, Any]]) -> str:
    if not affected_objects:
        return "| _none_ |  |  |  |  |  |  |"
    rows = []
    for affected in affected_objects:
        rows.append(
            _render_row(
                [
                    _object_label(affected["object_id"], affected.get("title")),
                    affected["object_type"],
                    affected["layer"],
                    affected["status"],
                    affected["severity"],
                    affected["impact_kind"],
                    affected["recommended_action"],
                ]
            )
        )
    return "\n".join(rows)


def _render_invalidation_candidates(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "| _none_ |  |  |  |  |  |"
    rows = []
    for candidate in candidates:
        rows.append(
            _render_row(
                [
                    candidate["candidate_id"],
                    candidate["target_object_id"],
                    candidate["candidate_kind"],
                    candidate["severity"],
                    "required" if candidate["requires_human_approval"] else "not required",
                    candidate["reason"],
                ]
            )
        )
    return "\n".join(rows)


def _render_paths(paths: list[dict[str, Any]]) -> str:
    if not paths:
        return "| _none_ |  |"
    rows = []
    for path in paths:
        rendered_path = " -> ".join(path["node_ids"])
        if path["link_ids"]:
            rendered_path = f"{rendered_path} [links: {' -> '.join(path['link_ids'])}]"
        rows.append(_render_row([path["target_object_id"], rendered_path]))
    return "\n".join(rows)


def _render_inline_list(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def _render_bool(value: bool) -> str:
    return "true" if value else "false"


def _object_label(object_id: str, title: str | None) -> str:
    if not title or title == object_id:
        return object_id
    return f"{object_id}: {title}"


def _render_row(cells: list[str]) -> str:
    return "| " + " | ".join(_escape_cell(str(cell)) for cell in cells) + " |"


def _escape_cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")
