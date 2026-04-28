from __future__ import annotations

from typing import Any

from decide_me.constants import DECISION_STACK_LAYER_ORDER
from decide_me.events import utc_now
from decide_me.graph_traversal import build_graph_index, descendants_with_paths


CHANGE_KINDS = {
    "changed",
    "invalidated",
    "superseded",
    "challenged",
    "assumption_failed",
    "evidence_retracted",
}
SEVERITIES = ("none", "low", "medium", "high")
_SEVERITY_RANK = {severity: rank for rank, severity in enumerate(SEVERITIES)}
_HIGH_RELATIONS = {
    "invalidates",
    "constrains",
    "requires",
    "depends_on",
    "blocked_by",
    "accepts",
    "challenges",
    "supersedes",
}
_MEDIUM_RELATIONS = {
    "addresses",
    "supports",
    "verifies",
    "mitigates",
    "derived_from",
    "enables",
    "recommends",
}
_LOW_RELATIONS = {"revisits"}
_RELATION_SEVERITY = {
    **{relation: "high" for relation in _HIGH_RELATIONS},
    **{relation: "medium" for relation in _MEDIUM_RELATIONS},
    **{relation: "low" for relation in _LOW_RELATIONS},
}


def analyze_impact(
    project_state: dict[str, Any],
    object_id: str,
    *,
    change_kind: str,
    max_depth: int | None = None,
    include_invalidated: bool = False,
) -> dict[str, Any]:
    if change_kind not in CHANGE_KINDS:
        allowed = ", ".join(sorted(CHANGE_KINDS))
        raise ValueError(f"change_kind must be one of: {allowed}")

    index = build_graph_index(project_state)
    if object_id not in index["nodes_by_id"]:
        raise ValueError(f"unknown object_id: {object_id}")

    path_items = descendants_with_paths(
        index,
        object_id,
        direction="influence",
        max_depth=max_depth,
    )
    retained_items = [
        item
        for item in path_items
        if include_invalidated or not index["nodes_by_id"][item["object_id"]].get("is_invalidated", False)
    ]

    affected_by_id: dict[str, dict[str, Any]] = {}
    paths: list[dict[str, Any]] = []
    affected_links: list[str] = []
    seen_link_ids: set[str] = set()

    for item in retained_items:
        target_id = item["object_id"]
        node = index["nodes_by_id"][target_id]
        classification = _classify_impact(node, item["relation"])
        candidate = _affected_object(target_id, node, item, classification)
        current = affected_by_id.get(target_id)
        if current is None or _is_stronger(candidate, current):
            affected_by_id[target_id] = candidate

        path = item["path"]
        paths.append(
            {
                "target_object_id": target_id,
                "node_ids": list(path["node_ids"]),
                "link_ids": list(path["link_ids"]),
            }
        )
        for link_id in path["link_ids"]:
            if link_id in seen_link_ids:
                continue
            seen_link_ids.add(link_id)
            affected_links.append(link_id)

    affected_objects = list(affected_by_id.values())
    return {
        "root_object_id": object_id,
        "change_kind": change_kind,
        "generated_at": utc_now(),
        "summary": {
            "affected_count": len(affected_objects),
            "highest_severity": _highest_severity(affected_objects),
            "affected_layers": _affected_layers(affected_objects),
        },
        "affected_objects": affected_objects,
        "affected_links": affected_links,
        "paths": paths,
    }


def _affected_object(
    object_id: str,
    node: dict[str, Any],
    item: dict[str, Any],
    classification: dict[str, str],
) -> dict[str, Any]:
    return {
        "object_id": object_id,
        "object_type": node["object_type"],
        "title": node.get("title"),
        "status": node["status"],
        "layer": node["layer"],
        "distance": item["distance"],
        "via_link_id": item["via_link_id"],
        "via_relation": item["relation"],
        "impact_kind": classification["impact_kind"],
        "severity": classification["severity"],
        "recommended_action": classification["recommended_action"],
    }


def _classify_impact(node: dict[str, Any], relation: str) -> dict[str, str]:
    object_type = node["object_type"]
    status = node["status"]
    impact_kind, object_severity, recommended_action = _object_impact(object_type, status)
    relation_severity = _RELATION_SEVERITY.get(relation, "low")
    severity = _max_severity(object_severity, relation_severity)
    return {
        "impact_kind": impact_kind,
        "severity": severity,
        "recommended_action": recommended_action,
    }


def _object_impact(object_type: str, status: str) -> tuple[str, str, str]:
    if object_type == "decision":
        severity = "high" if status == "accepted" else "medium"
        return (
            "decision_review_required",
            severity,
            "Review whether the decision remains valid after the upstream change.",
        )
    if object_type == "action":
        return (
            "action_rework_candidate",
            "medium",
            "Review whether the action needs rework after the upstream change.",
        )
    if object_type == "verification":
        return (
            "verification_review_required",
            "medium",
            "Review whether verification remains valid after the upstream change.",
        )
    if object_type == "evidence":
        return (
            "evidence_review_required",
            "medium",
            "Review whether the evidence remains valid after the upstream change.",
        )
    if object_type == "risk":
        return (
            "risk_review_required",
            "medium",
            "Review whether risk handling remains valid after the upstream change.",
        )
    if object_type == "revisit_trigger":
        return (
            "revisit_condition_review",
            "low",
            "Review whether the revisit condition still matches the upstream change.",
        )
    return (
        "object_review_required",
        "low",
        "Review whether this object remains valid after the upstream change.",
    )


def _is_stronger(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
    candidate_rank = _SEVERITY_RANK[candidate["severity"]]
    current_rank = _SEVERITY_RANK[current["severity"]]
    if candidate_rank != current_rank:
        return candidate_rank > current_rank
    if candidate["distance"] != current["distance"]:
        return candidate["distance"] < current["distance"]
    return candidate["via_link_id"] < current["via_link_id"]


def _max_severity(left: str, right: str) -> str:
    return left if _SEVERITY_RANK[left] >= _SEVERITY_RANK[right] else right


def _highest_severity(affected_objects: list[dict[str, Any]]) -> str:
    highest = "none"
    for affected in affected_objects:
        highest = _max_severity(highest, affected["severity"])
    return highest


def _affected_layers(affected_objects: list[dict[str, Any]]) -> list[str]:
    layer_set = {affected["layer"] for affected in affected_objects}
    return [layer for layer in DECISION_STACK_LAYER_ORDER if layer in layer_set]
