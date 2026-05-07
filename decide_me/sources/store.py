from __future__ import annotations

import urllib.request
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

from decide_me.events import utc_now
from decide_me.sources.decompose import decompose_document, html_to_text
from decide_me.sources.index import rebuild_evidence_index
from decide_me.sources.model import (
    SourceValidationError,
    document_dir,
    find_unit,
    load_registry,
    load_source_metadata,
    load_units,
    relative_source_path,
    save_registry,
    save_source_metadata,
    save_units,
    sha256_bytes,
    sha256_text,
    source_document_id,
    source_path_from_metadata,
    source_paths,
    validate_normative_unit,
    validate_source_document,
)
from decide_me.store import load_runtime, runtime_paths, transact


SOURCE_FORMAT_BY_SUFFIX = {
    ".xml": "xml",
    ".html": "html",
    ".htm": "html",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".pdf": "pdf",
}
ORIGINAL_SUFFIX_BY_FORMAT = {
    "xml": ".xml",
    "html": ".html",
    "markdown": ".md",
    "text": ".txt",
    "pdf": ".pdf",
    "binary": ".bin",
}


def import_source(
    ai_dir: str | Path,
    *,
    document_type: str,
    title: str,
    effective_from: str,
    file: str | Path | None = None,
    uri: str | None = None,
    source_id: str | None = None,
    authority: str | None = None,
    version_label: str | None = None,
    canonical: bool = True,
) -> dict[str, Any]:
    if bool(file) == bool(uri):
        raise ValueError("exactly one of file or uri is required")
    title = title.strip()
    if not title:
        raise ValueError("title must be a non-empty string")
    # Source import is audited by the event runtime, so require a valid runtime first.
    load_runtime(runtime_paths(ai_dir))

    raw, source_uri, suffix, import_method = _read_source_input(file=file, uri=uri)
    content_hash = sha256_bytes(raw)
    source_format = _detect_format(suffix)
    source_id = source_id or source_document_id(document_type, title, version_label, content_hash)
    now = utc_now()
    paths = source_paths(ai_dir)
    paths["sources_root"].mkdir(parents=True, exist_ok=True)
    paths["documents"].mkdir(parents=True, exist_ok=True)
    target_dir = document_dir(ai_dir, source_id)
    original_path = target_dir / f"original{ORIGINAL_SUFFIX_BY_FORMAT.get(source_format, '.bin')}"
    text_path = target_dir / "text.txt"
    units_path = target_dir / "units.jsonl"

    if target_dir.exists():
        existing = load_source_metadata(ai_dir, source_id)
        if existing["content_hash"] != content_hash:
            raise SourceValidationError(f"source document {source_id} already exists with a different hash")
        return {"status": "exists", "source_document": existing}

    registry = load_registry(ai_dir)
    previous_versions = [
        entry
        for entry in registry.get("documents", [])
        if entry.get("title") == title
        and entry.get("document_type") == document_type
        and entry.get("content_hash") != content_hash
    ]

    target_dir.mkdir(parents=True, exist_ok=False)
    original_path.write_bytes(raw)
    text_path.write_text(_source_snapshot_text(raw, source_format), encoding="utf-8")
    units_path.write_text("", encoding="utf-8")

    metadata = {
        "id": source_id,
        "title": title,
        "authority": authority,
        "document_type": document_type,
        "source_uri": source_uri,
        "version_label": version_label,
        "effective_from": effective_from,
        "effective_to": None,
        "retrieved_at": now,
        "content_hash": content_hash,
        "format": source_format,
        "canonical": canonical,
        "original_path": relative_source_path(ai_dir, original_path),
        "text_path": relative_source_path(ai_dir, text_path),
        "units_path": relative_source_path(ai_dir, units_path),
        "unit_count": 0,
    }
    save_source_metadata(ai_dir, metadata)
    registry["documents"] = sorted(
        [
            *registry.get("documents", []),
            {
                "id": source_id,
                "title": title,
                "document_type": document_type,
                "content_hash": content_hash,
                "metadata_path": relative_source_path(ai_dir, target_dir / "metadata.yaml"),
                "canonical": canonical,
                "effective_from": effective_from,
                "version_label": version_label,
            },
        ],
        key=lambda item: item["id"],
    )
    save_registry(ai_dir, registry)

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        events = [
            {
                "session_id": "SYSTEM",
                "event_type": "source_document_imported",
                "payload": {
                    "source_document_id": source_id,
                    "retrieved_at": now,
                    "content_hash": content_hash,
                    "import_method": import_method,
                    "format": source_format,
                    "source_uri": source_uri,
                    "snapshot_path": metadata["original_path"],
                },
            }
        ]
        if previous_versions:
            previous = sorted(previous_versions, key=lambda item: item["id"])[-1]
            events.append(
                {
                    "session_id": "SYSTEM",
                    "event_type": "source_version_updated",
                    "payload": {
                        "source_document_id": source_id,
                        "previous_source_document_id": previous["id"],
                        "old_source_hash": previous["content_hash"],
                        "new_source_hash": content_hash,
                        "updated_at": now,
                        "reason": "source_document_imported",
                    },
                }
            )
        return events

    events, _ = transact(ai_dir, builder)
    return {
        "status": "imported",
        "source_document": metadata,
        "event_ids": [event["event_id"] for event in events],
    }


def decompose_source(
    ai_dir: str | Path,
    *,
    source_id: str,
    strategy: str,
) -> dict[str, Any]:
    load_runtime(runtime_paths(ai_dir))
    metadata = load_source_metadata(ai_dir, source_id)
    units, parser_version, quality_flags = decompose_document(ai_dir, metadata, strategy=strategy)
    extracted_at = utc_now()
    save_units(ai_dir, source_id, units)
    metadata = deepcopy(metadata)
    metadata.update(
        {
            "unit_count": len(units),
            "decomposed_at": extracted_at,
            "parser_version": parser_version,
            "quality_flags": quality_flags,
        }
    )
    save_source_metadata(ai_dir, metadata)
    registry = load_registry(ai_dir)
    for entry in registry["documents"]:
        if entry["id"] == source_id:
            entry["unit_count"] = len(units)
            entry["parser_version"] = parser_version
    save_registry(ai_dir, registry)
    rebuild_evidence_index(ai_dir)

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "session_id": "SYSTEM",
                "event_type": "normative_units_extracted",
                "payload": {
                    "source_document_id": source_id,
                    "unit_count": len(units),
                    "parser_version": parser_version,
                    "quality_flags": quality_flags,
                    "extracted_at": extracted_at,
                    "source_content_hash": metadata["content_hash"],
                },
            }
        ]

    events, _ = transact(ai_dir, builder)
    return {
        "status": "decomposed",
        "source_document_id": source_id,
        "unit_count": len(units),
        "parser_version": parser_version,
        "quality_flags": quality_flags,
        "event_ids": [event["event_id"] for event in events],
    }


def list_sources(ai_dir: str | Path) -> dict[str, Any]:
    registry = load_registry(ai_dir)
    return {
        "status": "ok",
        "count": len(registry.get("documents", [])),
        "sources": registry.get("documents", []),
    }


def show_source(ai_dir: str | Path, source_id: str) -> dict[str, Any]:
    metadata = load_source_metadata(ai_dir, source_id)
    units = load_units(ai_dir, source_id)
    return {"status": "ok", "source_document": metadata, "unit_count": len(units)}


def show_source_unit(ai_dir: str | Path, source_unit_id: str) -> dict[str, Any]:
    unit = find_unit(ai_dir, source_unit_id)
    metadata = load_source_metadata(ai_dir, unit["source_document_id"])
    return {"status": "ok", "source_document": metadata, "source_unit": unit}


def validate_sources(ai_dir: str | Path) -> dict[str, Any]:
    issues: list[str] = []
    try:
        registry = load_registry(ai_dir)
    except SourceValidationError as exc:
        return {"ok": False, "issues": [str(exc)]}

    for entry in registry.get("documents", []):
        source_id = entry["id"]
        try:
            metadata = load_source_metadata(ai_dir, source_id)
            validate_source_document(metadata)
            original = source_path_from_metadata(ai_dir, metadata, "original_path")
            if not original.exists():
                issues.append(f"{source_id}: missing original snapshot")
            elif sha256_bytes(original.read_bytes()) != metadata["content_hash"]:
                issues.append(f"{source_id}: original snapshot hash mismatch")
            text_path = source_path_from_metadata(ai_dir, metadata, "text_path")
            if not text_path.exists():
                issues.append(f"{source_id}: missing text snapshot")
            units = load_units(ai_dir, source_id)
            seen_unit_ids: set[str] = set()
            for unit in units:
                validate_normative_unit(unit)
                if unit["id"] in seen_unit_ids:
                    issues.append(f"{source_id}: duplicate unit id {unit['id']}")
                seen_unit_ids.add(unit["id"])
                if sha256_text(unit["text_exact"]) != unit["content_hash"]:
                    issues.append(f"{unit['id']}: unit text hash mismatch")
            if metadata.get("unit_count", 0) != len(units):
                issues.append(f"{source_id}: unit_count does not match units.jsonl")
        except (OSError, SourceValidationError, ValueError) as exc:
            issues.append(f"{source_id}: {exc}")

    return {"ok": not issues, "issues": issues}


def _read_source_input(
    *,
    file: str | Path | None,
    uri: str | None,
) -> tuple[bytes, str | None, str, str]:
    if file is not None:
        path = Path(file)
        return path.read_bytes(), str(path), path.suffix.lower(), "local_file"
    assert uri is not None
    with urllib.request.urlopen(uri) as response:  # nosec: runtime user-selected source URI
        data = response.read()
    suffix = Path(urlparse(uri).path).suffix.lower()
    return data, uri, suffix, "uri_fetch"


def _detect_format(suffix: str) -> str:
    return SOURCE_FORMAT_BY_SUFFIX.get(suffix.lower(), "binary")


def _source_snapshot_text(raw: bytes, source_format: str) -> str:
    if source_format == "html":
        return html_to_text(raw)
    if source_format in {"xml", "markdown", "text"}:
        return raw.decode("utf-8", errors="replace")
    if source_format == "pdf":
        return ""
    return raw.decode("utf-8", errors="replace")
