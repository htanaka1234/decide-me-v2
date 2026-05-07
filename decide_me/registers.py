from __future__ import annotations

from copy import deepcopy
from typing import Any


REGISTER_SCHEMA_VERSION = 1


def build_evidence_register(project_state: dict[str, Any]) -> dict[str, Any]:
    links = _links_by_source(project_state)
    items = []
    for obj in _objects_of_type(project_state, "evidence"):
        metadata = obj.get("metadata", {})
        supports = _target_ids(links.get(obj["id"], []), "supports")
        challenges = _target_ids(links.get(obj["id"], []), "challenges")
        verifies = _target_ids(links.get(obj["id"], []), "verifies")
        constrains = _target_ids(links.get(obj["id"], []), "constrains")
        source_store_links = _source_store_links(links.get(obj["id"], []))
        related_links = _link_ids(links.get(obj["id"], []), {"supports", "challenges", "verifies", "constrains"})
        items.append(
            {
                **_common_item_fields(obj),
                "source": metadata.get("source"),
                "source_ref": metadata.get("source_ref"),
                "summary": metadata.get("summary"),
                "confidence": metadata.get("confidence"),
                "freshness": metadata.get("freshness"),
                "observed_at": metadata.get("observed_at"),
                "valid_until": metadata.get("valid_until"),
                "source_document_id": metadata.get("source_document_id"),
                "source_unit_id": metadata.get("source_unit_id"),
                "source_unit_hash": metadata.get("source_unit_hash"),
                "citation": metadata.get("citation"),
                "quote": metadata.get("quote"),
                "interpretation_note": metadata.get("interpretation_note"),
                "effective_from": metadata.get("effective_from"),
                "effective_to": metadata.get("effective_to"),
                "supports_object_ids": supports,
                "challenges_object_ids": challenges,
                "verifies_object_ids": verifies,
                "constrains_object_ids": constrains,
                "source_store_links": source_store_links,
                "related_link_ids": related_links,
            }
        )
    return _register_payload(
        project_state,
        register_type="evidence",
        summary={
            "item_count": len(items),
            "by_status": _count_by(items, "status"),
            "by_confidence": _count_by(items, "confidence"),
            "by_freshness": _count_by(items, "freshness"),
        },
        items=items,
    )


def build_assumption_register(project_state: dict[str, Any]) -> dict[str, Any]:
    links = _links_by_source(project_state)
    links_by_target = _links_by_target(project_state)
    items = []
    for obj in _objects_of_type(project_state, "assumption"):
        metadata = obj.get("metadata", {})
        constrains = _target_ids(links.get(obj["id"], []), "constrains")
        requires = _target_ids(links.get(obj["id"], []), "requires")
        derived_from = _target_ids(links.get(obj["id"], []), "derived_from")
        invalidates = _target_ids(links.get(obj["id"], []), "invalidates")
        outgoing_related_links = _link_ids(
            links.get(obj["id"], []),
            {"constrains", "requires", "derived_from", "invalidates"},
        )
        incoming_dependency_links = _links_with_relation(links_by_target.get(obj["id"], []), "requires")
        incoming_derived_links = _links_with_relation(links_by_target.get(obj["id"], []), "derived_from")
        required_by = _sorted_strings(link["source_object_id"] for link in incoming_dependency_links)
        derived_into = _sorted_strings(link["source_object_id"] for link in incoming_derived_links)
        related_links = _sorted_strings(
            [
                *outgoing_related_links,
                *(link["id"] for link in incoming_dependency_links),
                *(link["id"] for link in incoming_derived_links),
            ]
        )
        items.append(
            {
                **_common_item_fields(obj),
                "statement": metadata.get("statement"),
                "confidence": metadata.get("confidence"),
                "validation": metadata.get("validation"),
                "invalidates_if_false": _sorted_strings(metadata.get("invalidates_if_false", [])),
                "expires_at": metadata.get("expires_at"),
                "owner": metadata.get("owner"),
                "constrains_object_ids": constrains,
                "requires_object_ids": requires,
                "derived_from_object_ids": derived_from,
                "invalidates_object_ids": invalidates,
                "required_by_object_ids": required_by,
                "derived_into_object_ids": derived_into,
                "related_link_ids": related_links,
            }
        )
    return _register_payload(
        project_state,
        register_type="assumption",
        summary={
            "item_count": len(items),
            "by_status": _count_by(items, "status"),
            "by_confidence": _count_by(items, "confidence"),
        },
        items=items,
    )


def build_risk_register(project_state: dict[str, Any]) -> dict[str, Any]:
    links_by_target = _links_by_target(project_state)
    items = []
    for obj in _objects_of_type(project_state, "risk"):
        metadata = obj.get("metadata", {})
        mitigation_links = _links_with_relation(links_by_target.get(obj["id"], []), "mitigates")
        mitigated_by = _sorted_strings(link["source_object_id"] for link in mitigation_links)
        items.append(
            {
                **_common_item_fields(obj),
                "statement": metadata.get("statement"),
                "severity": metadata.get("severity"),
                "likelihood": metadata.get("likelihood"),
                "risk_tier": metadata.get("risk_tier"),
                "reversibility": metadata.get("reversibility"),
                "mitigation_object_ids": _sorted_strings(metadata.get("mitigation_object_ids", [])),
                "approval_threshold": metadata.get("approval_threshold"),
                "mitigated_by_object_ids": mitigated_by,
                "mitigation_link_ids": _sorted_strings(link["id"] for link in mitigation_links),
                "related_link_ids": _sorted_strings(link["id"] for link in mitigation_links),
            }
        )
    return _register_payload(
        project_state,
        register_type="risk",
        summary={
            "item_count": len(items),
            "by_status": _count_by(items, "status"),
            "by_risk_tier": _count_by(items, "risk_tier"),
            "by_approval_threshold": _count_by(items, "approval_threshold"),
            "by_reversibility": _count_by(items, "reversibility"),
        },
        items=items,
    )


def _register_payload(
    project_state: dict[str, Any],
    *,
    register_type: str,
    summary: dict[str, Any],
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    state = project_state.get("state", {})
    return {
        "schema_version": REGISTER_SCHEMA_VERSION,
        "register_type": register_type,
        "project_head": state.get("project_head"),
        "generated_at": state.get("updated_at"),
        "summary": summary,
        "items": sorted(items, key=lambda item: item["object_id"]),
    }


def _objects_of_type(project_state: dict[str, Any], object_type: str) -> list[dict[str, Any]]:
    return sorted(
        (obj for obj in project_state.get("objects", []) if obj.get("type") == object_type),
        key=lambda obj: obj["id"],
    )


def _common_item_fields(obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "object_id": obj["id"],
        "title": obj.get("title"),
        "status": obj.get("status"),
        "created_at": obj.get("created_at"),
        "updated_at": obj.get("updated_at"),
        "source_event_ids": _sorted_strings(obj.get("source_event_ids", [])),
    }


def _links_by_source(project_state: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_source: dict[str, list[dict[str, Any]]] = {}
    for link in project_state.get("links", []):
        by_source.setdefault(link["source_object_id"], []).append(deepcopy(link))
    for links in by_source.values():
        links.sort(key=lambda link: link["id"])
    return by_source


def _links_by_target(project_state: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_target: dict[str, list[dict[str, Any]]] = {}
    for link in project_state.get("links", []):
        by_target.setdefault(link["target_object_id"], []).append(deepcopy(link))
    for links in by_target.values():
        links.sort(key=lambda link: link["id"])
    return by_target


def _links_with_relation(links: list[dict[str, Any]], relation: str) -> list[dict[str, Any]]:
    return sorted((link for link in links if link.get("relation") == relation), key=lambda link: link["id"])


def _target_ids(links: list[dict[str, Any]], relation: str) -> list[str]:
    return _sorted_strings(link["target_object_id"] for link in _links_with_relation(links, relation))


def _link_ids(links: list[dict[str, Any]], relations: set[str]) -> list[str]:
    return _sorted_strings(link["id"] for link in links if link.get("relation") in relations)


def _source_store_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for link in links:
        metadata = link.get("metadata") or {}
        if not metadata.get("source_unit_id"):
            continue
        rows.append(
            {
                "link_id": link["id"],
                "target_object_id": link["target_object_id"],
                "relevance": link["relation"],
                "source_document_id": metadata.get("source_document_id"),
                "source_unit_id": metadata.get("source_unit_id"),
                "source_unit_hash": metadata.get("source_unit_hash"),
                "citation": metadata.get("citation"),
                "quote": metadata.get("quote"),
                "interpretation_note": metadata.get("interpretation_note"),
                "effective_from": metadata.get("effective_from"),
                "effective_to": metadata.get("effective_to"),
                "linked_at": metadata.get("linked_at"),
            }
        )
    return sorted(rows, key=lambda item: item["link_id"])


def _sorted_strings(values: Any) -> list[str]:
    return sorted({str(value) for value in values})


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = item.get(key)
        if value is None:
            continue
        counts[str(value)] = counts.get(str(value), 0) + 1
    return {key: counts[key] for key in sorted(counts)}
