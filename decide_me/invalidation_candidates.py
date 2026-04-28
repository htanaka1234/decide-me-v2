from __future__ import annotations

from hashlib import sha256
from typing import Any

from decide_me.graph_traversal import build_graph_index, descendants
from decide_me.impact_analysis import analyze_impact


CANDIDATE_KINDS = {
    "review",
    "revalidate",
    "revise",
    "invalidate",
    "supersede",
    "add_verification",
    "update_revisit_trigger",
}
_UNRESOLVED_DECISION_STATUSES = {"unresolved", "proposed", "blocked"}


def generate_invalidation_candidates(
    project_state: dict[str, Any],
    object_id: str,
    *,
    change_kind: str,
    max_depth: int | None = None,
    include_low_severity: bool = False,
    include_invalidated: bool = False,
) -> dict[str, Any]:
    impact = analyze_impact(
        project_state,
        object_id,
        change_kind=change_kind,
        max_depth=max_depth,
        include_invalidated=include_invalidated,
    )
    index = build_graph_index(project_state)
    root_node = index["nodes_by_id"][object_id]

    candidates: list[dict[str, Any]] = []
    for affected in impact["affected_objects"]:
        if affected["severity"] == "low" and not include_low_severity:
            continue
        for candidate_kind, requires_human_approval, reason in _candidate_rules(
            index,
            root_node,
            affected,
            change_kind,
        ):
            candidates.append(
                _candidate(
                    root_object_id=object_id,
                    change_kind=change_kind,
                    affected=affected,
                    candidate_kind=candidate_kind,
                    requires_human_approval=requires_human_approval,
                    reason=reason,
                )
            )

    return {
        "root_object_id": object_id,
        "change_kind": change_kind,
        "generated_at": impact["generated_at"],
        "impact_summary": {
            "affected_count": impact["summary"]["affected_count"],
            "highest_severity": impact["summary"]["highest_severity"],
            "affected_layers": list(impact["summary"]["affected_layers"]),
        },
        "candidates": candidates,
    }


def _candidate_rules(
    index: dict[str, Any],
    root_node: dict[str, Any],
    affected: dict[str, Any],
    change_kind: str,
) -> list[tuple[str, bool, str]]:
    object_type = affected["object_type"]
    status = affected["status"]
    severity = affected["severity"]

    if object_type == "decision":
        if status == "accepted" and change_kind == "invalidated":
            return [("invalidate", True, "Accepted decision is affected by an invalidated upstream object.")]
        if status == "accepted" and change_kind == "superseded":
            return [("supersede", True, "Accepted decision is affected by a superseded upstream object.")]
        if status == "accepted" and severity == "high":
            return [("revalidate", True, "Accepted decision is affected by a high severity upstream change.")]
        if status in _UNRESOLVED_DECISION_STATUSES:
            return [("review", False, "Unresolved decision is affected by an upstream change.")]
        return [("review", False, "Decision is affected by an upstream change.")]

    if object_type == "action":
        candidates = [("revise", False, "Action may need revision after an upstream change.")]
        if root_node["object_type"] == "decision" and change_kind == "invalidated":
            candidates.append(("invalidate", True, "Action depends on an invalidated upstream decision."))
        if not _has_live_downstream_verification(index, affected["object_id"]):
            candidates.append(("add_verification", False, "Action has no live downstream verification or evidence."))
        return candidates

    if object_type == "verification":
        return [("revalidate", False, "Verification is affected by an upstream change.")]

    if object_type == "evidence":
        if change_kind == "evidence_retracted":
            return [("invalidate", True, "Evidence is affected by retracted upstream evidence.")]
        return [("revalidate", False, "Evidence is affected by an upstream change.")]

    if object_type == "risk":
        return [("review", False, "Risk handling is affected by an upstream change.")]

    if object_type == "revisit_trigger":
        return [
            (
                "update_revisit_trigger",
                False,
                "Revisit trigger may need to be updated after an upstream change.",
            )
        ]

    return [("review", False, "Object is affected by an upstream change.")]


def _candidate(
    *,
    root_object_id: str,
    change_kind: str,
    affected: dict[str, Any],
    candidate_kind: str,
    requires_human_approval: bool,
    reason: str,
) -> dict[str, Any]:
    return {
        "candidate_id": _candidate_id(
            root_object_id,
            change_kind,
            affected["object_id"],
            candidate_kind,
            affected["via_link_id"],
        ),
        "target_object_id": affected["object_id"],
        "target_object_type": affected["object_type"],
        "target_status": affected["status"],
        "layer": affected["layer"],
        "severity": affected["severity"],
        "candidate_kind": candidate_kind,
        "reason": reason,
        "proposed_events": [],
        "requires_human_approval": requires_human_approval,
        "source_impact": {
            "via_link_id": affected["via_link_id"],
            "via_relation": affected["via_relation"],
            "distance": affected["distance"],
            "impact_kind": affected["impact_kind"],
        },
    }


def _candidate_id(
    root_object_id: str,
    change_kind: str,
    target_object_id: str,
    candidate_kind: str,
    via_link_id: str,
) -> str:
    digest = sha256(
        f"{root_object_id}|{change_kind}|{target_object_id}|{candidate_kind}|{via_link_id}".encode("utf-8")
    ).hexdigest()
    return f"IC-{digest[:12]}"


def _has_live_downstream_verification(index: dict[str, Any], object_id: str) -> bool:
    for item in descendants(index, object_id, direction="influence"):
        node = index["nodes_by_id"][item["object_id"]]
        if node.get("is_invalidated") is True:
            continue
        if node["object_type"] in {"verification", "evidence"}:
            return True
    return False
