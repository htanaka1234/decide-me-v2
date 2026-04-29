from __future__ import annotations

import re
from typing import Any

from decide_me.taxonomy import stable_unique


DOCUMENT_SCHEMA_VERSION = 1
DOCUMENT_TYPES = {
    "decision-brief",
    "action-plan",
    "risk-register",
    "review-memo",
    "research-plan",
    "comparison-table",
}
CSV_DOCUMENT_TYPES = {"risk-register", "comparison-table"}
DOCUMENT_AUDIENCE = "human"


def normalize_document_type(value: str) -> str:
    normalized = value.strip().replace("_", "-")
    if normalized not in DOCUMENT_TYPES:
        raise ValueError(f"unsupported document type: {value}")
    return normalized


def build_document(
    context: Any,
    *,
    document_type: str,
    title: str,
    sections: list[dict[str, Any]],
    diagnostic_types: list[str] | None = None,
    warnings: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document_type = normalize_document_type(document_type)
    sorted_sections = _profiled_sections(context, sections)
    missing_sections = _missing_profile_sections(context, sorted_sections)
    if missing_sections:
        profile_id = getattr(getattr(context, "document_profile", None), "profile_id", None)
        raise ValueError(
            f"document profile {profile_id} requires missing sections: {', '.join(missing_sections)}"
        )
    source_object_ids = stable_unique(
        object_id
        for section in sorted_sections
        for object_id in section.get("source_object_ids", [])
    )
    source_link_ids = stable_unique(
        link_id
        for section in sorted_sections
        for link_id in section.get("source_link_ids", [])
    )
    return {
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "document_id": document_id(document_type, context.generated_at),
        "document_type": document_type,
        "audience": DOCUMENT_AUDIENCE,
        "generated_at": context.generated_at,
        "project_head": context.project_head,
        "source": {
            "session_ids": list(context.source_session_ids),
            "object_ids": source_object_ids,
            "link_ids": source_link_ids,
            "diagnostic_types": sorted(stable_unique(diagnostic_types or [])),
        },
        "title": title,
        "sections": sorted_sections,
        "warnings": list(warnings or []),
        "metadata": _document_metadata(context, metadata),
    }


def document_id(document_type: str, generated_at: str | None) -> str:
    date_part = "unknown"
    if generated_at:
        digits = re.sub(r"\D", "", generated_at[:10])
        if digits:
            date_part = digits
    return f"DOC-{date_part}-{normalize_document_type(document_type)}"


def _profiled_sections(context: Any, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = sorted(sections, key=lambda section: (section["order"], section["id"]))
    profile = getattr(context, "document_profile", None)
    required_sections = tuple(getattr(profile, "required_sections", ()) or ())
    if not required_sections:
        return base
    priority = {section_id: index for index, section_id in enumerate(required_sections)}
    return sorted(
        base,
        key=lambda item: (
            0 if item["id"] in priority else 1,
            priority.get(item["id"], item["order"]),
            item["order"],
            item["id"],
        ),
    )


def _missing_profile_sections(context: Any, sections: list[dict[str, Any]]) -> list[str]:
    profile = getattr(context, "document_profile", None)
    required_sections = tuple(getattr(profile, "required_sections", ()) or ())
    if not required_sections:
        return []
    present = {section["id"] for section in sections}
    return [section_id for section_id in required_sections if section_id not in present]


def _document_metadata(context: Any, metadata: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(metadata or {})
    profile = getattr(context, "document_profile", None)
    pack = getattr(context, "domain_pack", None)
    digest = getattr(context, "domain_pack_digest", None)
    if profile is not None and pack is not None and digest is not None:
        merged.update(
            {
                "domain_pack_id": pack.pack_id,
                "domain_pack_version": pack.version,
                "domain_pack_digest": digest,
                "document_profile_id": profile.profile_id,
            }
        )
    return merged


def section(
    section_id: str,
    title: str,
    order: int,
    blocks: list[dict[str, Any]],
    *,
    source_object_ids: list[str] | None = None,
    source_link_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": section_id,
        "title": title,
        "order": order,
        "blocks": blocks,
        "source_object_ids": sorted(stable_unique(source_object_ids or [])),
        "source_link_ids": sorted(stable_unique(source_link_ids or [])),
    }


def text_block(text: str | None) -> dict[str, Any]:
    return {"type": "text", "text": text}


def list_block(items: list[Any]) -> dict[str, Any]:
    return {"type": "list", "items": list(items)}


def table_block(columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    return {"type": "table", "columns": list(columns), "rows": list(rows)}


def callout_block(severity: str, text: str) -> dict[str, Any]:
    return {"type": "callout", "severity": severity, "text": text}


def object_refs_block(object_ids: list[str]) -> dict[str, Any]:
    return {"type": "object_refs", "object_ids": sorted(stable_unique(object_ids))}
