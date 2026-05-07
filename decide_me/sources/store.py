from __future__ import annotations

import shutil
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
from decide_me.store import read_event_log, runtime_paths, transact_with_precommit


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
    previous_source_id: str | None = None,
) -> dict[str, Any]:
    if bool(file) == bool(uri):
        raise ValueError("exactly one of file or uri is required")
    title = title.strip()
    if not title:
        raise ValueError("title must be a non-empty string")

    raw, source_uri, suffix, import_method = _read_source_input(file=file, uri=uri)
    content_hash = sha256_bytes(raw)
    source_format = _detect_format(suffix)
    source_id = source_id or source_document_id(document_type, title, version_label, content_hash)
    now = utc_now()
    target_dir = document_dir(ai_dir, source_id)
    original_path = target_dir / f"original{ORIGINAL_SUFFIX_BY_FORMAT.get(source_format, '.bin')}"
    text_path = target_dir / "text.txt"
    units_path = target_dir / "units.jsonl"

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
    validate_source_document(metadata)
    outcome: dict[str, Any] = {"status": "imported", "source_document": metadata}
    old_registry: dict[str, Any] | None = None
    new_registry: dict[str, Any] | None = None
    selected_previous: dict[str, Any] | None = None

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        nonlocal old_registry, new_registry, selected_previous
        if target_dir.exists():
            existing = load_source_metadata(ai_dir, source_id)
            if existing["content_hash"] != content_hash:
                raise SourceValidationError(f"source document {source_id} already exists with a different hash")
            existing_registry = load_registry(ai_dir)
            if not any(entry.get("id") == source_id for entry in existing_registry.get("documents", [])):
                raise SourceValidationError(f"source document {source_id} exists without a registry entry")
            if not _source_import_event_exists(ai_dir, source_id=source_id, content_hash=content_hash):
                raise SourceValidationError(f"source document {source_id} exists without an audit import event")
            outcome["status"] = "exists"
            outcome["source_document"] = existing
            return []

        old_registry = load_registry(ai_dir)
        selected_previous = _select_previous_source(
            ai_dir,
            old_registry,
            document_type=document_type,
            title=title,
            content_hash=content_hash,
            previous_source_id=previous_source_id,
        )
        new_registry = deepcopy(old_registry)
        new_registry["documents"] = sorted(
            [
                *new_registry.get("documents", []),
                _registry_entry(metadata),
            ],
            key=lambda item: item["id"],
        )
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
        if selected_previous is not None:
            events.append(
                {
                    "session_id": "SYSTEM",
                    "event_type": "source_version_updated",
                    "payload": {
                        "source_document_id": source_id,
                        "previous_source_document_id": selected_previous["id"],
                        "old_source_hash": selected_previous["content_hash"],
                        "new_source_hash": content_hash,
                        "updated_at": now,
                        "reason": "source_document_imported",
                    },
                }
            )
        return events

    def precommit(events: list[dict[str, Any]], bundle: dict[str, Any]) -> None:
        assert new_registry is not None
        target_dir.mkdir(parents=True, exist_ok=False)
        original_path.write_bytes(raw)
        text_path.write_text(_source_snapshot_text(raw, source_format), encoding="utf-8")
        units_path.write_text("", encoding="utf-8")
        save_source_metadata(ai_dir, metadata)
        save_registry(ai_dir, new_registry)

    def rollback(exc: BaseException) -> None:
        if target_dir.exists():
            shutil.rmtree(target_dir)
        if old_registry is not None:
            save_registry(ai_dir, old_registry)

    events, _ = transact_with_precommit(ai_dir, builder, precommit=precommit, rollback=rollback)
    return {
        "status": outcome["status"],
        "source_document": outcome["source_document"],
        "event_ids": [event["event_id"] for event in events],
    }


def decompose_source(
    ai_dir: str | Path,
    *,
    source_id: str,
    strategy: str,
) -> dict[str, Any]:
    state: dict[str, Any] = {}

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        old_metadata = load_source_metadata(ai_dir, source_id)
        units, parser_version, quality_flags = decompose_document(ai_dir, old_metadata, strategy=strategy)
        extracted_at = utc_now()
        new_metadata = deepcopy(old_metadata)
        new_metadata.update(
            {
                "unit_count": len(units),
                "decomposed_at": extracted_at,
                "parser_version": parser_version,
                "quality_flags": quality_flags,
            }
        )
        validate_source_document(new_metadata)
        old_registry = load_registry(ai_dir)
        new_registry = deepcopy(old_registry)
        for entry in new_registry["documents"]:
            if entry["id"] == source_id:
                entry["unit_count"] = len(units)
                entry["parser_version"] = parser_version
                entry["retrieved_at"] = old_metadata["retrieved_at"]
                entry["effective_to"] = old_metadata["effective_to"]
        state.update(
            {
                "old_metadata": old_metadata,
                "old_units": load_units(ai_dir, source_id),
                "old_registry": old_registry,
                "new_metadata": new_metadata,
                "new_units": units,
                "new_registry": new_registry,
                "parser_version": parser_version,
                "quality_flags": quality_flags,
                "extracted_at": extracted_at,
                "old_index": _read_index_snapshot(ai_dir),
            }
        )
        return [
            {
                "session_id": "SYSTEM",
                "event_type": "normative_units_extracted",
                "payload": {
                    "source_document_id": source_id,
                    "unit_count": len(state["new_units"]),
                    "parser_version": parser_version,
                    "quality_flags": quality_flags,
                    "extracted_at": extracted_at,
                    "source_content_hash": old_metadata["content_hash"],
                },
            }
        ]

    def precommit(events: list[dict[str, Any]], bundle: dict[str, Any]) -> None:
        save_units(ai_dir, source_id, state["new_units"])
        save_source_metadata(ai_dir, state["new_metadata"])
        save_registry(ai_dir, state["new_registry"])
        rebuild_evidence_index(ai_dir)

    def rollback(exc: BaseException) -> None:
        save_units(ai_dir, source_id, state["old_units"])
        save_source_metadata(ai_dir, state["old_metadata"])
        save_registry(ai_dir, state["old_registry"])
        _restore_index_snapshot(ai_dir, state["old_index"])

    events, _ = transact_with_precommit(ai_dir, builder, precommit=precommit, rollback=rollback)
    return {
        "status": "decomposed",
        "source_document_id": source_id,
        "unit_count": len(state["new_units"]),
        "parser_version": state["parser_version"],
        "quality_flags": state["quality_flags"],
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


def _registry_entry(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": metadata["id"],
        "title": metadata["title"],
        "document_type": metadata["document_type"],
        "content_hash": metadata["content_hash"],
        "metadata_path": f"documents/{metadata['id']}/metadata.yaml",
        "canonical": metadata["canonical"],
        "effective_from": metadata["effective_from"],
        "effective_to": metadata["effective_to"],
        "retrieved_at": metadata["retrieved_at"],
        "version_label": metadata["version_label"],
        "source_uri": metadata["source_uri"],
        "unit_count": metadata.get("unit_count", 0),
    }


def _select_previous_source(
    ai_dir: str | Path,
    registry: dict[str, Any],
    *,
    document_type: str,
    title: str,
    content_hash: str,
    previous_source_id: str | None,
) -> dict[str, Any] | None:
    if previous_source_id is not None:
        for entry in registry.get("documents", []):
            if entry.get("id") != previous_source_id:
                continue
            candidate = _entry_with_temporal_fields(ai_dir, entry)
            if candidate.get("content_hash") == content_hash:
                raise SourceValidationError(f"previous source document has the same content hash: {previous_source_id}")
            return candidate
        raise SourceValidationError(f"unknown previous source document: {previous_source_id}")

    candidates = [
        _entry_with_temporal_fields(ai_dir, entry)
        for entry in registry.get("documents", [])
        if entry.get("title") == title
        and entry.get("document_type") == document_type
        and entry.get("content_hash") != content_hash
    ]
    if not candidates:
        return None
    return sorted(candidates, key=_source_version_sort_key)[-1]


def _entry_with_temporal_fields(ai_dir: str | Path, entry: dict[str, Any]) -> dict[str, Any]:
    enriched = deepcopy(entry)
    if "retrieved_at" not in enriched or "effective_from" not in enriched:
        try:
            metadata = load_source_metadata(ai_dir, entry["id"])
        except SourceValidationError:
            return enriched
        enriched.setdefault("retrieved_at", metadata.get("retrieved_at"))
        enriched.setdefault("effective_from", metadata.get("effective_from"))
    return enriched


def _source_import_event_exists(ai_dir: str | Path, *, source_id: str, content_hash: str) -> bool:
    for event in read_event_log(runtime_paths(ai_dir)):
        if event.get("event_type") != "source_document_imported":
            continue
        payload = event.get("payload", {})
        if payload.get("source_document_id") == source_id and payload.get("content_hash") == content_hash:
            return True
    return False


def _source_version_sort_key(entry: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(entry.get("retrieved_at") or ""),
        str(entry.get("effective_from") or ""),
        str(entry.get("id") or ""),
    )


def _read_index_snapshot(ai_dir: str | Path) -> bytes | None:
    index_path = source_paths(ai_dir)["source_units_index"]
    return index_path.read_bytes() if index_path.exists() else None


def _restore_index_snapshot(ai_dir: str | Path, snapshot: bytes | None) -> None:
    index_path = source_paths(ai_dir)["source_units_index"]
    if snapshot is None:
        if index_path.exists():
            index_path.unlink()
        return
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_bytes(snapshot)
