from __future__ import annotations

import re
from pathlib import Path


MARKER_END = "<!-- decide-me:generated:end -->"
MARKER_START_RE = re.compile(r"<!-- decide-me:generated:start(?P<attrs>[^>]*) -->")


def managed_document_body(
    generated_content: str,
    *,
    document_type: str,
    project_head: str | None,
    include_human_notes: bool = True,
) -> str:
    region = managed_region(generated_content, document_type=document_type, project_head=project_head)
    if include_human_notes:
        return f"{region}\n## Human Notes\n\n"
    return region


def managed_region(
    generated_content: str,
    *,
    document_type: str,
    project_head: str | None,
) -> str:
    start = (
        "<!-- decide-me:generated:start "
        f"document_type={document_type} project_head={_attr_value(project_head)} -->"
    )
    return f"{start}\n{generated_content.rstrip()}\n{MARKER_END}\n"


def merge_managed_content(
    existing: str | None,
    generated_content: str,
    *,
    document_type: str,
    project_head: str | None,
    force: bool = False,
) -> tuple[str, list[str]]:
    new_body = managed_document_body(
        generated_content,
        document_type=document_type,
        project_head=project_head,
    )
    if existing is None:
        return new_body, []

    matches = list(MARKER_START_RE.finditer(existing))
    end_count = existing.count(MARKER_END)
    if not matches and end_count == 0:
        if not force:
            raise ValueError("document output already exists without decide-me markers; pass --force to overwrite it")
        return new_body, []
    if len(matches) != 1 or end_count != 1:
        raise ValueError("document output must contain exactly one decide-me generated marker block")

    start_match = matches[0]
    end_index = existing.index(MARKER_END)
    if end_index < start_match.start():
        raise ValueError("document output decide-me end marker appears before start marker")

    attrs = parse_marker_attrs(start_match.group("attrs"))
    existing_type = attrs.get("document_type")
    if existing_type and existing_type != document_type:
        raise ValueError(f"document marker type mismatch: expected {document_type}, found {existing_type}")

    warnings = []
    existing_head = attrs.get("project_head")
    current_head = _attr_value(project_head)
    if existing_head and existing_head != "null" and existing_head != current_head:
        warnings.append(
            f"Existing generated region project_head {existing_head} differs from current project_head {current_head}."
        )

    replacement = managed_region(
        generated_content,
        document_type=document_type,
        project_head=project_head,
    )
    suffix_start = end_index + len(MARKER_END)
    return f"{existing[:start_match.start()]}{replacement}{existing[suffix_start:]}", warnings


def marker_warnings_for_path(
    output_path: Path,
    *,
    document_type: str,
    project_head: str | None,
) -> list[str]:
    if not output_path.exists() or output_path.is_dir():
        return []
    existing = output_path.read_text(encoding="utf-8")
    matches = list(MARKER_START_RE.finditer(existing))
    if len(matches) != 1:
        return []
    attrs = parse_marker_attrs(matches[0].group("attrs"))
    existing_type = attrs.get("document_type")
    if existing_type and existing_type != document_type:
        return []
    existing_head = attrs.get("project_head")
    current_head = _attr_value(project_head)
    if existing_head and existing_head != "null" and existing_head != current_head:
        return [f"Existing generated region project_head {existing_head} differs from current project_head {current_head}."]
    return []


def parse_marker_attrs(attrs: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for key, value in re.findall(r"([A-Za-z_][A-Za-z0-9_-]*)=([^\s>]+)", attrs):
        parsed[key] = value
    return parsed


def _attr_value(value: str | None) -> str:
    return value if value else "null"
