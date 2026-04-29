from __future__ import annotations

from pathlib import Path
from typing import Any

from decide_me.documents.compiler import compile_document
from decide_me.documents.merge import marker_warnings_for_path, merge_managed_content
from decide_me.documents.model import CSV_DOCUMENT_TYPES, DOCUMENT_TYPES, normalize_document_type
from decide_me.documents.render_csv import render_csv_document
from decide_me.documents.render_json import render_json_document
from decide_me.documents.render_markdown import render_markdown_document
from decide_me.store import runtime_paths


DOCUMENT_FORMATS = {"markdown", "json", "csv"}


def export_document(
    ai_dir: str | Path,
    *,
    document_type: str,
    format: str,
    output: str | Path,
    session_ids: list[str] | None = None,
    object_ids: list[str] | None = None,
    include_invalidated: bool = False,
    now: str | None = None,
    force: bool = False,
    managed_region: bool = True,
) -> Path:
    normalized_type = normalize_document_type(document_type)
    if format not in DOCUMENT_FORMATS:
        raise ValueError("format must be one of: markdown, json, csv")
    if format == "csv" and normalized_type not in CSV_DOCUMENT_TYPES:
        supported = ", ".join(sorted(CSV_DOCUMENT_TYPES))
        raise ValueError(f"CSV export is supported only for: {supported}")

    paths = runtime_paths(ai_dir)
    output_path = Path(output)
    _assert_safe_document_output(paths.exports_dir, output_path)
    if output_path.is_dir():
        raise ValueError(f"document output path is a directory: {output_path}")

    model = compile_document(
        ai_dir,
        document_type=normalized_type,
        session_ids=session_ids,
        object_ids=object_ids,
        include_invalidated=include_invalidated,
        now=now,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if format == "json":
        _write_text(output_path, render_json_document(model))
        return output_path
    if format == "csv":
        _write_text(output_path, render_csv_document(model))
        return output_path

    if managed_region:
        model["warnings"].extend(
            warning
            for warning in marker_warnings_for_path(
                output_path,
                document_type=normalized_type,
                project_head=model.get("project_head"),
            )
            if warning not in model["warnings"]
        )
    markdown = render_markdown_document(model)
    if managed_region:
        existing = output_path.read_text(encoding="utf-8") if output_path.exists() else None
        merged, warnings = merge_managed_content(
            existing,
            markdown,
            document_type=normalized_type,
            project_head=model.get("project_head"),
            force=force,
        )
        if warnings and not all(warning in model["warnings"] for warning in warnings):
            for warning in warnings:
                if warning not in model["warnings"]:
                    model["warnings"].append(warning)
            markdown = render_markdown_document(model)
            merged, _warnings = merge_managed_content(
                existing,
                markdown,
                document_type=normalized_type,
                project_head=model.get("project_head"),
                force=force,
            )
        _write_text(output_path, merged)
    else:
        _write_text(output_path, markdown)
    return output_path


def _assert_safe_document_output(exports_dir: Path, output_path: Path) -> None:
    resolved_output = output_path.resolve()
    documents_dir = (exports_dir / "documents").resolve()
    if not resolved_output.is_relative_to(documents_dir):
        supported = ", ".join(sorted(DOCUMENT_TYPES))
        raise ValueError(
            "document output must be inside ai-dir exports/documents/ "
            f"for supported document types: {supported}"
        )


def _write_text(path: Path, body: str) -> None:
    if path.is_dir():
        raise ValueError(f"document output path is a directory: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
