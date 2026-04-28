from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from decide_me.events import utc_now


STALE_DIAGNOSTIC_SCHEMA_VERSION = 1


def detect_stale_assumptions(project_state: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    as_of, reference = _reference_time(now)
    items = []
    for obj in _objects_of_type(project_state, "assumption"):
        metadata = obj.get("metadata", {})
        expires_at = metadata.get("expires_at")
        if not expires_at or _parse_timestamp(expires_at, f"assumption {obj['id']}.metadata.expires_at") >= reference:
            continue
        related_links = _links_touching(project_state, obj["id"])
        items.append(
            {
                **_common_item(obj),
                "statement": metadata.get("statement"),
                "confidence": metadata.get("confidence"),
                "expires_at": expires_at,
                "owner": metadata.get("owner"),
                "invalidates_if_false": _sorted_strings(metadata.get("invalidates_if_false", [])),
                "related_object_ids": _related_object_ids(related_links, obj["id"]),
                "related_link_ids": _sorted_strings(link["id"] for link in related_links),
                "stale_reason": "expires_at_elapsed",
            }
        )
    return _diagnostic_payload(project_state, "stale_assumptions", as_of, items)


def detect_stale_evidence(project_state: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    as_of, reference = _reference_time(now)
    evidence_items: dict[str, dict[str, Any]] = {}
    for obj in _objects_of_type(project_state, "evidence"):
        metadata = obj.get("metadata", {})
        reasons = []
        valid_until = metadata.get("valid_until")
        if valid_until and _parse_timestamp(valid_until, f"evidence {obj['id']}.metadata.valid_until") < reference:
            reasons.append("valid_until_elapsed")
        if metadata.get("freshness") == "stale":
            reasons.append("freshness_stale")
        if not reasons:
            continue
        outgoing_links = _links_from(project_state, obj["id"], {"supports", "verifies", "challenges"})
        evidence_items[obj["id"]] = {
            **_common_item(obj),
            "source": metadata.get("source"),
            "source_ref": metadata.get("source_ref"),
            "summary": metadata.get("summary"),
            "confidence": metadata.get("confidence"),
            "freshness": metadata.get("freshness"),
            "observed_at": metadata.get("observed_at"),
            "valid_until": valid_until,
            "stale_reasons": sorted(reasons),
            "affected_object_ids": _sorted_strings(link["target_object_id"] for link in outgoing_links),
            "affected_decision_ids": [],
            "related_link_ids": _sorted_strings(link["id"] for link in outgoing_links),
        }

    objects_by_id = _objects_by_id(project_state)
    for link in project_state.get("links", []):
        if link.get("relation") not in {"supports", "verifies"}:
            continue
        evidence = evidence_items.get(link.get("source_object_id"))
        if evidence is None:
            continue
        decision = objects_by_id.get(link.get("target_object_id"))
        if not decision or decision.get("type") != "decision" or not _is_live(decision):
            continue
        if decision.get("status") not in {"accepted", "active", "unresolved", "proposed", "blocked"}:
            continue
        evidence["affected_decision_ids"] = _sorted_strings([*evidence["affected_decision_ids"], decision["id"]])
        evidence["related_link_ids"] = _sorted_strings([*evidence["related_link_ids"], link["id"]])

    items = [evidence_items[object_id] for object_id in sorted(evidence_items)]
    return _diagnostic_payload(project_state, "stale_evidence", as_of, items)


def detect_verification_gaps(project_state: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    as_of, _reference = _reference_time(now)
    items = []
    for obj in _objects_of_type(project_state, "action"):
        supporting_links = _verification_links(project_state, obj["id"])
        if supporting_links:
            continue
        gap_severity = "high" if obj.get("status") == "completed" else "medium"
        items.append(
            {
                **_common_item(obj),
                "gap_severity": gap_severity,
                "gap_reason": "missing_verification",
                "verification_object_ids": [],
                "evidence_object_ids": [],
                "related_link_ids": [],
            }
        )
    return _diagnostic_payload(project_state, "verification_gaps", as_of, items)


def detect_revisit_due(project_state: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    as_of, reference = _reference_time(now)
    items = []
    for obj in _objects_of_type(project_state, "revisit_trigger"):
        metadata = obj.get("metadata", {})
        due_at = metadata.get("due_at")
        if not due_at or _parse_timestamp(due_at, f"revisit_trigger {obj['id']}.metadata.due_at") >= reference:
            continue
        outgoing_links = _links_from(project_state, obj["id"], {"revisits"})
        target_object_ids = _sorted_strings(metadata.get("target_object_ids", []))
        items.append(
            {
                **_common_item(obj),
                "trigger_type": metadata.get("trigger_type"),
                "condition": metadata.get("condition"),
                "due_at": due_at,
                "target_object_ids": target_object_ids,
                "related_link_ids": _sorted_strings(link["id"] for link in outgoing_links),
                "due_reason": "due_at_elapsed",
            }
        )
    return _diagnostic_payload(project_state, "revisit_due", as_of, items)


def _diagnostic_payload(
    project_state: dict[str, Any],
    diagnostic_type: str,
    as_of: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    state = project_state.get("state", {})
    sorted_items = sorted(items, key=lambda item: item["object_id"])
    return {
        "schema_version": STALE_DIAGNOSTIC_SCHEMA_VERSION,
        "diagnostic_type": diagnostic_type,
        "project_head": state.get("project_head"),
        "generated_at": state.get("updated_at"),
        "as_of": as_of,
        "summary": _summary(diagnostic_type, sorted_items),
        "items": sorted_items,
    }


def _summary(diagnostic_type: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"item_count": len(items), "by_status": _count_by(items, "status")}
    if diagnostic_type == "verification_gaps":
        summary["by_gap_severity"] = _count_by(items, "gap_severity")
    elif diagnostic_type == "stale_evidence":
        summary["affected_decision_count"] = len(
            {decision_id for item in items for decision_id in item["affected_decision_ids"]}
        )
    return summary


def _verification_links(project_state: dict[str, Any], action_id: str) -> list[dict[str, Any]]:
    objects_by_id = _objects_by_id(project_state)
    links = []
    for link in project_state.get("links", []):
        if link.get("target_object_id") != action_id or link.get("relation") not in {"verifies", "supports"}:
            continue
        obj = objects_by_id.get(link.get("source_object_id"))
        if not obj or not _is_live(obj):
            continue
        if obj.get("type") in {"verification", "evidence"}:
            links.append(deepcopy(link))
    return sorted(links, key=lambda link: link["id"])


def _objects_by_id(project_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {obj["id"]: deepcopy(obj) for obj in project_state.get("objects", [])}


def _objects_of_type(project_state: dict[str, Any], object_type: str) -> list[dict[str, Any]]:
    return sorted(
        (deepcopy(obj) for obj in project_state.get("objects", []) if obj.get("type") == object_type and _is_live(obj)),
        key=lambda obj: obj["id"],
    )


def _links_from(project_state: dict[str, Any], object_id: str, relations: set[str]) -> list[dict[str, Any]]:
    return sorted(
        (
            deepcopy(link)
            for link in project_state.get("links", [])
            if link.get("source_object_id") == object_id and link.get("relation") in relations
        ),
        key=lambda link: link["id"],
    )


def _links_touching(project_state: dict[str, Any], object_id: str) -> list[dict[str, Any]]:
    return sorted(
        (
            deepcopy(link)
            for link in project_state.get("links", [])
            if link.get("source_object_id") == object_id or link.get("target_object_id") == object_id
        ),
        key=lambda link: link["id"],
    )


def _related_object_ids(links: list[dict[str, Any]], object_id: str) -> list[str]:
    related = []
    for link in links:
        if link.get("source_object_id") != object_id:
            related.append(link["source_object_id"])
        if link.get("target_object_id") != object_id:
            related.append(link["target_object_id"])
    return _sorted_strings(related)


def _common_item(obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "object_id": obj["id"],
        "title": obj.get("title"),
        "status": obj.get("status"),
        "created_at": obj.get("created_at"),
        "updated_at": obj.get("updated_at"),
        "source_event_ids": _sorted_strings(obj.get("source_event_ids", [])),
    }


def _reference_time(now: str | None) -> tuple[str, datetime]:
    as_of = now or utc_now()
    return as_of, _parse_timestamp(as_of, "now")


def _parse_timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be ISO-8601/RFC3339-like") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include timezone information")
    return parsed


def _is_live(obj: dict[str, Any]) -> bool:
    return obj.get("status") != "invalidated"


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = item.get(key)
        if value is None:
            continue
        counts[str(value)] = counts.get(str(value), 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def _sorted_strings(values: Any) -> list[str]:
    return sorted({str(value) for value in values})
