from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml


SOURCE_STORE_SCHEMA_VERSION = 1
SOURCE_DOCUMENT_ID_PATTERN = re.compile(r"^SRC-[A-Za-z0-9_.:-]+$")
SOURCE_UNIT_ID_PATTERN = re.compile(r"^NU-[A-Za-z0-9_.:-]+$")
SOURCE_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_:-]*$")
SOURCE_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
SUPPORTED_DECOMPOSE_FORMATS = {"xml", "html", "markdown", "text"}


class SourceValidationError(ValueError):
    """Raised when source-store metadata is malformed."""


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def short_hash(*parts: Any, length: int = 12) -> str:
    material = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:length]


def source_document_id(document_type: str, title: str, version_label: str | None, content_hash: str) -> str:
    return f"SRC-{short_hash(document_type, title, version_label, content_hash, length=12)}"


def source_unit_id(source_document_id: str, path_slug: str, content_hash: str) -> str:
    digest = content_hash.removeprefix("sha256:")[:8]
    return f"NU-{source_document_id}-{path_slug}-{digest}"


def evidence_object_id(source_unit_id_value: str) -> str:
    return f"O-evidence-{source_unit_id_value}"


def source_paths(ai_dir: str | Path) -> dict[str, Path]:
    root = Path(ai_dir)
    sources_root = root / "sources"
    return {
        "ai_dir": root,
        "sources_root": sources_root,
        "registry": sources_root / "registry.yaml",
        "documents": sources_root / "documents",
        "index_dir": root / "index",
        "source_units_index": root / "index" / "source_units.sqlite",
    }


def document_dir(ai_dir: str | Path, source_id: str) -> Path:
    _require_source_id(source_id, "source_document_id")
    return source_paths(ai_dir)["documents"] / source_id


def load_registry(ai_dir: str | Path) -> dict[str, Any]:
    path = source_paths(ai_dir)["registry"]
    if not path.exists():
        return default_registry()
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    validate_registry(payload)
    return payload


def save_registry(ai_dir: str | Path, registry: dict[str, Any]) -> None:
    validate_registry(registry)
    path = source_paths(ai_dir)["registry"]
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, yaml.safe_dump(registry, allow_unicode=True, sort_keys=False))


def default_registry() -> dict[str, Any]:
    return {"schema_version": SOURCE_STORE_SCHEMA_VERSION, "documents": []}


def load_source_metadata(ai_dir: str | Path, source_id: str) -> dict[str, Any]:
    path = document_dir(ai_dir, source_id) / "metadata.yaml"
    if not path.exists():
        raise SourceValidationError(f"unknown source document: {source_id}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    validate_source_document(payload)
    return payload


def save_source_metadata(ai_dir: str | Path, metadata: dict[str, Any]) -> None:
    validate_source_document(metadata)
    path = document_dir(ai_dir, metadata["id"]) / "metadata.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False))


def load_units(ai_dir: str | Path, source_id: str) -> list[dict[str, Any]]:
    units_path = document_dir(ai_dir, source_id) / "units.jsonl"
    if not units_path.exists():
        return []
    units: list[dict[str, Any]] = []
    with units_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                unit = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise SourceValidationError(f"{units_path} line {line_number} contains malformed JSON") from exc
            validate_normative_unit(unit)
            units.append(unit)
    return sorted(units, key=lambda item: (item.get("order", 0), item["id"]))


def save_units(ai_dir: str | Path, source_id: str, units: list[dict[str, Any]]) -> None:
    for unit in units:
        validate_normative_unit(unit)
    path = document_dir(ai_dir, source_id) / "units.jsonl"
    body = "".join(json.dumps(unit, ensure_ascii=False, sort_keys=True) + "\n" for unit in units)
    _atomic_write_text(path, body)


def find_unit(ai_dir: str | Path, source_unit_id_value: str) -> dict[str, Any]:
    registry = load_registry(ai_dir)
    for entry in registry.get("documents", []):
        for unit in load_units(ai_dir, entry["id"]):
            if unit["id"] == source_unit_id_value:
                return unit
    raise SourceValidationError(f"unknown source unit: {source_unit_id_value}")


def validate_registry(registry: dict[str, Any]) -> None:
    _require_dict(registry, "registry")
    if registry.get("schema_version") != SOURCE_STORE_SCHEMA_VERSION:
        raise SourceValidationError(f"registry.schema_version must be {SOURCE_STORE_SCHEMA_VERSION}")
    documents = registry.get("documents")
    if not isinstance(documents, list):
        raise SourceValidationError("registry.documents must be a list")
    seen: set[str] = set()
    for index, item in enumerate(documents):
        _require_dict(item, f"registry.documents[{index}]")
        for key in ("id", "title", "document_type", "content_hash", "metadata_path"):
            _require_non_empty_string(item.get(key), f"registry.documents[{index}].{key}")
        _require_source_id(item["id"], f"registry.documents[{index}].id")
        _require_hash(item["content_hash"], f"registry.documents[{index}].content_hash")
        if item["id"] in seen:
            raise SourceValidationError(f"duplicate source document id in registry: {item['id']}")
        seen.add(item["id"])


def validate_source_document(document: dict[str, Any]) -> None:
    _require_dict(document, "source_document")
    required = (
        "id",
        "title",
        "authority",
        "document_type",
        "source_uri",
        "version_label",
        "effective_from",
        "effective_to",
        "retrieved_at",
        "content_hash",
        "format",
        "canonical",
        "original_path",
        "text_path",
        "units_path",
    )
    for key in required:
        if key not in document:
            raise SourceValidationError(f"source_document.{key} is required")
    _require_source_id(document["id"], "source_document.id")
    _require_non_empty_string(document["title"], "source_document.title")
    _require_string_or_null(document["authority"], "source_document.authority")
    _require_document_type(document["document_type"], "source_document.document_type")
    _require_string_or_null(document["source_uri"], "source_document.source_uri")
    _require_string_or_null(document["version_label"], "source_document.version_label")
    _require_date(document["effective_from"], "source_document.effective_from")
    _require_date_or_null(document["effective_to"], "source_document.effective_to")
    _require_timestamp(document["retrieved_at"], "source_document.retrieved_at")
    _require_hash(document["content_hash"], "source_document.content_hash")
    _require_non_empty_string(document["format"], "source_document.format")
    if not isinstance(document["canonical"], bool):
        raise SourceValidationError("source_document.canonical must be a boolean")
    for key in ("original_path", "text_path", "units_path"):
        _require_non_empty_string(document[key], f"source_document.{key}")
    if "unit_count" in document and (
        not isinstance(document["unit_count"], int) or document["unit_count"] < 0
    ):
        raise SourceValidationError("source_document.unit_count must be a non-negative integer")


def validate_normative_unit(unit: dict[str, Any]) -> None:
    _require_dict(unit, "normative_unit")
    required = (
        "id",
        "source_document_id",
        "order",
        "unit_type",
        "path",
        "citation",
        "text_exact",
        "text_normalized",
        "content_hash",
        "anchors",
        "effective_from",
        "effective_to",
    )
    for key in required:
        if key not in unit:
            raise SourceValidationError(f"normative_unit.{key} is required")
    _require_unit_id(unit["id"], "normative_unit.id")
    _require_source_id(unit["source_document_id"], "normative_unit.source_document_id")
    if not isinstance(unit["order"], int) or unit["order"] < 1:
        raise SourceValidationError("normative_unit.order must be a positive integer")
    _require_non_empty_string(unit["unit_type"], "normative_unit.unit_type")
    _require_dict(unit["path"], "normative_unit.path")
    _require_non_empty_string(unit["citation"], "normative_unit.citation")
    _require_non_empty_string(unit["text_exact"], "normative_unit.text_exact")
    _require_non_empty_string(unit["text_normalized"], "normative_unit.text_normalized")
    _require_hash(unit["content_hash"], "normative_unit.content_hash")
    _require_dict(unit["anchors"], "normative_unit.anchors")
    _require_date(unit["effective_from"], "normative_unit.effective_from")
    _require_date_or_null(unit["effective_to"], "normative_unit.effective_to")


def relative_source_path(ai_dir: str | Path, path: Path) -> str:
    root = source_paths(ai_dir)["sources_root"]
    return path.relative_to(root).as_posix()


def source_path_from_metadata(ai_dir: str | Path, metadata: dict[str, Any], key: str) -> Path:
    return source_paths(ai_dir)["sources_root"] / metadata[key]


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def path_slug(parts: list[str]) -> str:
    raw = "-".join(parts) or "unit"
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", raw)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized or "unit"


def _atomic_write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(body, encoding="utf-8")
    tmp_path.replace(path)


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SourceValidationError(f"{label} must be an object")
    return value


def _require_non_empty_string(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SourceValidationError(f"{label} must be a non-empty string")


def _require_string_or_null(value: Any, label: str) -> None:
    if value is not None and not isinstance(value, str):
        raise SourceValidationError(f"{label} must be a string or null")


def _require_timestamp(value: Any, label: str) -> None:
    _require_non_empty_string(value, label)
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceValidationError(f"{label} must be ISO-8601/RFC3339-like") from exc


def _require_date(value: Any, label: str) -> None:
    _require_non_empty_string(value, label)
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise SourceValidationError(f"{label} must be YYYY-MM-DD") from exc


def _require_date_or_null(value: Any, label: str) -> None:
    if value is None:
        return
    _require_date(value, label)


def _require_source_id(value: Any, label: str) -> None:
    _require_non_empty_string(value, label)
    if not SOURCE_DOCUMENT_ID_PATTERN.fullmatch(str(value)):
        raise SourceValidationError(f"{label} must match ^SRC-[A-Za-z0-9_.:-]+$")


def _require_unit_id(value: Any, label: str) -> None:
    _require_non_empty_string(value, label)
    if not SOURCE_UNIT_ID_PATTERN.fullmatch(str(value)):
        raise SourceValidationError(f"{label} must match ^NU-[A-Za-z0-9_.:-]+$")


def _require_document_type(value: Any, label: str) -> None:
    _require_non_empty_string(value, label)
    if not SOURCE_TYPE_PATTERN.fullmatch(str(value)):
        raise SourceValidationError(f"{label} must match ^[a-z][a-z0-9_:-]*$")


def _require_hash(value: Any, label: str) -> None:
    _require_non_empty_string(value, label)
    if not SOURCE_HASH_PATTERN.fullmatch(str(value)):
        raise SourceValidationError(f"{label} must be sha256:<64 lowercase hex chars>")
