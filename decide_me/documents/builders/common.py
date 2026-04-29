from __future__ import annotations

from typing import Any

from decide_me.documents.context import DocumentContext
from decide_me.taxonomy import stable_unique


FINAL_DECISION_STATUSES = {"accepted", "resolved-by-evidence"}
LIVE_STATUSES_EXCLUDED_BY_DEFAULT = {"invalidated"}


def objects_by_id(context: DocumentContext) -> dict[str, dict[str, Any]]:
    return {obj["id"]: obj for obj in context.project_state.get("objects", [])}


def links_by_id(context: DocumentContext) -> dict[str, dict[str, Any]]:
    return {link["id"]: link for link in context.project_state.get("links", [])}


def objects_of_type(context: DocumentContext, object_type: str) -> list[dict[str, Any]]:
    return [
        obj
        for obj in sorted(context.project_state.get("objects", []), key=lambda item: item["id"])
        if obj.get("type") == object_type and selected_object(context, obj)
    ]


def objects_of_types(context: DocumentContext, object_types: set[str]) -> list[dict[str, Any]]:
    return [
        obj
        for obj in sorted(context.project_state.get("objects", []), key=lambda item: (item["type"], item["id"]))
        if obj.get("type") in object_types and selected_object(context, obj)
    ]


def selected_object(context: DocumentContext, obj: dict[str, Any]) -> bool:
    if context.object_ids and obj["id"] not in set(context.object_ids):
        return False
    if not context.include_invalidated and obj.get("status") in LIVE_STATUSES_EXCLUDED_BY_DEFAULT:
        return False
    return True


def link_ids_touching(context: DocumentContext, object_ids: list[str]) -> list[str]:
    ids = set(object_ids)
    return sorted(
        stable_unique(
            link["id"]
            for link in context.project_state.get("links", [])
            if link.get("source_object_id") in ids or link.get("target_object_id") in ids
        )
    )


def related_object_ids(context: DocumentContext, object_id: str, *, types: set[str] | None = None) -> list[str]:
    by_id = objects_by_id(context)
    related: list[str] = []
    for link in context.project_state.get("links", []):
        candidate = None
        if link.get("source_object_id") == object_id:
            candidate = link.get("target_object_id")
        elif link.get("target_object_id") == object_id:
            candidate = link.get("source_object_id")
        if not candidate:
            continue
        obj = by_id.get(candidate)
        if not obj:
            continue
        if types is not None and obj.get("type") not in types:
            continue
        related.append(candidate)
    return sorted(stable_unique(related))


def diagnostic_object_ids(payload: dict[str, Any], *keys: str) -> list[str]:
    ids: list[str] = []
    for item in payload.get("items", []):
        ids.append(item.get("object_id"))
        for key in keys:
            value = item.get(key)
            if isinstance(value, list):
                ids.extend(value)
    return sorted(stable_unique(value for value in ids if value))


def diagnostic_link_ids(payload: dict[str, Any]) -> list[str]:
    return sorted(
        stable_unique(
            link_id
            for item in payload.get("items", [])
            for link_id in item.get("related_link_ids", [])
        )
    )


def safety_object_ids(payload: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for result in payload.get("results", []):
        ids.append(result.get("object_id"))
        ids.extend(item.get("object_id") for item in result.get("evidence", []))
        ids.extend(item.get("object_id") for item in result.get("assumptions", []))
        ids.extend(item.get("object_id") for item in result.get("risks", []))
    return sorted(stable_unique(value for value in ids if value))


def safety_link_ids(payload: dict[str, Any]) -> list[str]:
    return sorted(
        stable_unique(
            link_id
            for result in payload.get("results", [])
            for link_id in result.get("source_link_ids", [])
            if link_id
        )
    )


def object_label(obj: dict[str, Any] | None) -> str:
    if not obj:
        return ""
    return obj.get("title") or obj.get("body") or obj.get("id") or ""


def metadata_value(obj: dict[str, Any], key: str) -> Any:
    return obj.get("metadata", {}).get(key)


def source_traceability_section(context: DocumentContext, order: int) -> dict[str, Any]:
    from decide_me.documents.model import list_block, section

    close_object_ids = []
    close_link_ids = []
    for session in context.sessions:
        close_summary = session.get("close_summary", {})
        for values in close_summary.get("object_ids", {}).values():
            close_object_ids.extend(values)
        close_link_ids.extend(close_summary.get("link_ids", []))
    source_object_ids = sorted(stable_unique(close_object_ids))
    source_link_ids = sorted(stable_unique(close_link_ids))
    return section(
        "source-traceability",
        "Source Traceability",
        order,
        [
            list_block(
                [
                    f"Sessions: {', '.join(context.source_session_ids) if context.source_session_ids else 'none recorded'}",
                    f"Objects: {', '.join(source_object_ids) if source_object_ids else 'none recorded'}",
                    f"Links: {', '.join(source_link_ids) if source_link_ids else 'none recorded'}",
                ]
            )
        ],
        source_object_ids=source_object_ids,
        source_link_ids=source_link_ids,
    )
