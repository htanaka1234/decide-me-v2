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
            max_depth,
        ):
            candidates.append(
                _candidate(
                    root_object_id=object_id,
                    change_kind=change_kind,
                    root_node=root_node,
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
    max_depth: int | None,
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
        remaining_depth = None if max_depth is None else max(0, max_depth - affected["distance"])
        if not _has_live_downstream_verification(index, affected["object_id"], max_depth=remaining_depth):
            candidates.append(("add_verification", False, "Action has no live downstream verification or evidence."))
        return candidates

    if object_type == "verification":
        return [("revalidate", False, "Verification is affected by an upstream change.")]

    if object_type == "evidence":
        if change_kind == "evidence_retracted":
            return [("invalidate", True, "Evidence is affected by retracted upstream evidence.")]
        return [("revalidate", False, "Evidence is affected by an upstream change.")]

    if object_type == "risk":
        if affected["via_relation"] == "mitigates":
            return [("revalidate", False, "Mitigated risk should be revalidated after its mitigation changes.")]
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
    root_node: dict[str, Any],
    affected: dict[str, Any],
    candidate_kind: str,
    requires_human_approval: bool,
    reason: str,
) -> dict[str, Any]:
    candidate_id = _candidate_id(
        root_object_id,
        change_kind,
        affected["object_id"],
        candidate_kind,
        affected["via_link_id"],
    )
    proposed_events = _proposed_events(
        candidate_id=candidate_id,
        root_object_id=root_object_id,
        root_node=root_node,
        change_kind=change_kind,
        affected=affected,
        candidate_kind=candidate_kind,
        reason=reason,
    )
    materialization_status = "materialized" if proposed_events else "manual"
    return {
        "candidate_id": candidate_id,
        "target_object_id": affected["object_id"],
        "target_object_type": affected["object_type"],
        "target_status": affected["status"],
        "layer": affected["layer"],
        "severity": affected["severity"],
        "candidate_kind": candidate_kind,
        "reason": reason,
        "requires_human_approval": requires_human_approval,
        "approval_threshold": "explicit_acceptance" if requires_human_approval else "none",
        "materialization_status": materialization_status,
        "materialization_reason": _materialization_reason(materialization_status, candidate_kind),
        "proposed_events": proposed_events,
        "source_impact": {
            "via_link_id": affected["via_link_id"],
            "via_relation": affected["via_relation"],
            "distance": affected["distance"],
            "impact_kind": affected["impact_kind"],
        },
    }


def _proposed_events(
    *,
    candidate_id: str,
    root_object_id: str,
    root_node: dict[str, Any],
    change_kind: str,
    affected: dict[str, Any],
    candidate_kind: str,
    reason: str,
) -> list[dict[str, Any]]:
    if candidate_kind == "invalidate":
        return _invalidation_events(
            root_object_id=root_object_id,
            target_object_id=affected["object_id"],
            target_object_type=affected["object_type"],
            target_status=affected["status"],
            reason=reason,
        )
    if candidate_kind == "supersede":
        return _supersession_events(
            root_object_id=root_object_id,
            root_node=root_node,
            target_object_id=affected["object_id"],
            target_status=affected["status"],
            reason=reason,
        )
    if candidate_kind == "add_verification":
        return _add_verification_events(
            candidate_id=candidate_id,
            root_object_id=root_object_id,
            change_kind=change_kind,
            target_object_id=affected["object_id"],
        )
    return []


def _invalidation_events(
    *,
    root_object_id: str,
    target_object_id: str,
    target_object_type: str,
    target_status: str,
    reason: str,
) -> list[dict[str, Any]]:
    events = [_status_change_event(target_object_id, target_status, "invalidated", reason)]
    if target_object_type == "decision":
        events.append(_decision_invalidated_by_event(target_object_id, root_object_id, reason))
    return events


def _supersession_events(
    *,
    root_object_id: str,
    root_node: dict[str, Any],
    target_object_id: str,
    target_status: str,
    reason: str,
) -> list[dict[str, Any]]:
    events = [
        _status_change_event(target_object_id, target_status, "invalidated", reason),
        _decision_invalidated_by_event(target_object_id, root_object_id, reason),
    ]
    if root_node["object_type"] == "decision":
        events.append(
            {
                "event_type": "object_linked",
                "payload": {
                    "link": {
                        "id": f"L-{root_object_id}-supersedes-{target_object_id}",
                        "source_object_id": root_object_id,
                        "relation": "supersedes",
                        "target_object_id": target_object_id,
                        "rationale": reason,
                    }
                },
            }
        )
    return events


def _add_verification_events(
    *,
    candidate_id: str,
    root_object_id: str,
    change_kind: str,
    target_object_id: str,
) -> list[dict[str, Any]]:
    verification_id = f"VER-{candidate_id[3:]}"
    rationale = f"Add verification for {target_object_id} after {change_kind} impact from {root_object_id}."
    return [
        {
            "event_type": "object_recorded",
            "payload": {
                "object": {
                    "id": verification_id,
                    "type": "verification",
                    "title": f"Verify {target_object_id}",
                    "body": rationale,
                    "status": "planned",
                    "metadata": {
                        "method": "review",
                        "expected_result": (
                            f"{target_object_id} remains valid after {change_kind} impact "
                            f"from {root_object_id}."
                        ),
                        "verified_at": None,
                        "result": "pending",
                    },
                }
            },
        },
        {
            "event_type": "object_linked",
            "payload": {
                "link": {
                    "id": f"L-{verification_id}-verifies-{target_object_id}",
                    "source_object_id": verification_id,
                    "relation": "verifies",
                    "target_object_id": target_object_id,
                    "rationale": rationale,
                }
            },
        },
    ]


def _status_change_event(target_object_id: str, from_status: str, to_status: str, reason: str) -> dict[str, Any]:
    return {
        "event_type": "object_status_changed",
        "payload": {
            "object_id": target_object_id,
            "from_status": from_status,
            "to_status": to_status,
            "reason": reason,
        },
    }


def _decision_invalidated_by_event(target_object_id: str, root_object_id: str, reason: str) -> dict[str, Any]:
    return {
        "event_type": "object_updated",
        "payload": {
            "object_id": target_object_id,
            "patch": {
                "metadata": {
                    "invalidated_by": {
                        "decision_id": root_object_id,
                        "reason": reason,
                    }
                }
            },
        },
    }


def _materialization_reason(materialization_status: str, candidate_kind: str) -> str:
    if materialization_status == "materialized":
        return f"{candidate_kind} candidate can be represented as deterministic event drafts."
    return f"{candidate_kind} candidate requires human-authored runtime changes before materialization."


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


def _has_live_downstream_verification(index: dict[str, Any], object_id: str, *, max_depth: int | None) -> bool:
    for item in descendants(index, object_id, direction="influence", max_depth=max_depth):
        node = index["nodes_by_id"][item["object_id"]]
        if node.get("is_invalidated") is True:
            continue
        if node["object_type"] in {"verification", "evidence"}:
            return True
    return False
