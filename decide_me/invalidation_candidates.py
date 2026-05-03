from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from decide_me.domains import load_domain_registry
from decide_me.graph_traversal import build_graph_index, descendants
from decide_me.impact_analysis import analyze_impact
from decide_me.safety_gate import evaluate_safety_gate
from decide_me.store import load_runtime, runtime_paths, transact


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
_REASON_REQUIRED_SEVERITIES = {"medium", "high"}


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
                    materialized_at=impact["generated_at"],
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


def apply_invalidation_candidate(
    ai_dir: str | Path,
    *,
    object_id: str,
    change_kind: str,
    candidate_id: str,
    session_id: str | None = None,
    max_depth: int | None = None,
    include_low_severity: bool = False,
    include_invalidated: bool = False,
    approve: bool = False,
    actor: str | None = None,
    reason: str | None = None,
    safety_approval_id: str | None = None,
) -> dict[str, Any]:
    candidate_id = _require_text(candidate_id, "candidate_id")
    actor = _optional_text(actor, "actor")
    reason = _optional_text(reason, "reason")
    safety_approval_id = _optional_text(safety_approval_id, "safety_approval_id")
    domain_registry = load_domain_registry(ai_dir)

    if not approve:
        bundle = load_runtime(runtime_paths(ai_dir))
        dry_run_session_id = _select_apply_session(bundle, session_id) if session_id is not None else None
        report = generate_invalidation_candidates(
            bundle["project_state"],
            object_id,
            change_kind=change_kind,
            max_depth=max_depth,
            include_low_severity=include_low_severity,
            include_invalidated=include_invalidated,
        )
        candidate = _require_candidate(report, candidate_id)
        gate = evaluate_safety_gate(
            bundle["project_state"],
            candidate["target_object_id"],
            domain_registry=domain_registry,
        )
        return _apply_result(
            "dry_run",
            candidate,
            gate,
            approved=False,
            event_ids=[],
            session_id=dry_run_session_id,
            reason=reason,
            actor=actor,
        )

    outcome: dict[str, Any] = {}

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        report = generate_invalidation_candidates(
            bundle["project_state"],
            object_id,
            change_kind=change_kind,
            max_depth=max_depth,
            include_low_severity=include_low_severity,
            include_invalidated=include_invalidated,
        )
        candidate = _require_candidate(report, candidate_id)
        gate = evaluate_safety_gate(
            bundle["project_state"],
            candidate["target_object_id"],
            domain_registry=domain_registry,
        )
        apply_session_id = _select_apply_session(bundle, session_id)
        _validate_candidate_application(
            candidate,
            gate,
            reason=reason,
            safety_approval_id=safety_approval_id,
        )
        specs = _candidate_event_specs(
            candidate,
            session_id=apply_session_id,
            reason=reason,
            actor=actor,
        )
        outcome["candidate"] = candidate
        outcome["gate_before"] = gate
        outcome["session_id"] = apply_session_id
        return specs

    events, bundle = transact(ai_dir, builder)
    candidate = outcome["candidate"]
    gate_after = evaluate_safety_gate(
        bundle["project_state"],
        candidate["target_object_id"],
        domain_registry=domain_registry,
    )
    return _apply_result(
        "applied",
        candidate,
        gate_after,
        approved=True,
        event_ids=[event["event_id"] for event in events],
        session_id=outcome.get("session_id"),
        reason=reason,
        actor=actor,
        committed_events=_event_summaries(events),
        gate_before=outcome.get("gate_before"),
    )


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
    materialized_at: str,
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
        materialized_at=materialized_at,
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
    materialized_at: str,
    affected: dict[str, Any],
    candidate_kind: str,
    reason: str,
) -> list[dict[str, Any]]:
    if candidate_kind == "invalidate":
        return _invalidation_events(
            candidate_id=candidate_id,
            root_object_id=root_object_id,
            root_node=root_node,
            target_object_id=affected["object_id"],
            target_object_type=affected["object_type"],
            target_status=affected["status"],
            materialized_at=materialized_at,
            reason=reason,
        )
    if candidate_kind == "supersede":
        return _supersession_events(
            candidate_id=candidate_id,
            root_object_id=root_object_id,
            root_node=root_node,
            target_object_id=affected["object_id"],
            target_status=affected["status"],
            materialized_at=materialized_at,
            reason=reason,
        )
    if candidate_kind == "add_verification":
        return _add_verification_events(
            candidate_id=candidate_id,
            root_object_id=root_object_id,
            change_kind=change_kind,
            target_object_id=affected["object_id"],
            materialized_at=materialized_at,
        )
    return []


def _invalidation_events(
    *,
    candidate_id: str,
    root_object_id: str,
    root_node: dict[str, Any],
    target_object_id: str,
    target_object_type: str,
    target_status: str,
    materialized_at: str,
    reason: str,
) -> list[dict[str, Any]]:
    if target_object_type == "decision" and not _can_invalidate_decision(root_node):
        return []
    events = [
        _status_change_event(
            candidate_id,
            1,
            target_object_id,
            target_status,
            "invalidated",
            materialized_at,
            reason,
        )
    ]
    if target_object_type == "decision":
        events.append(
            _decision_invalidated_by_event(
                candidate_id,
                2,
                target_object_id,
                root_object_id,
                materialized_at,
                reason,
            )
        )
    return events


def _supersession_events(
    *,
    candidate_id: str,
    root_object_id: str,
    root_node: dict[str, Any],
    target_object_id: str,
    target_status: str,
    materialized_at: str,
    reason: str,
) -> list[dict[str, Any]]:
    if not _can_invalidate_decision(root_node):
        return []
    events = [
        _status_change_event(
            candidate_id,
            1,
            target_object_id,
            target_status,
            "invalidated",
            materialized_at,
            reason,
        ),
        _decision_invalidated_by_event(
            candidate_id,
            2,
            target_object_id,
            root_object_id,
            materialized_at,
            reason,
        ),
    ]
    if root_node["object_type"] == "decision":
        event_id = _proposed_event_id(candidate_id, 3)
        events.append(
            _event_spec(
                event_id=event_id,
                event_type="object_linked",
                ts=materialized_at,
                payload={
                    "link": {
                        "id": f"L-{root_object_id}-supersedes-{target_object_id}",
                        "source_object_id": root_object_id,
                        "relation": "supersedes",
                        "target_object_id": target_object_id,
                        "rationale": reason,
                        "created_at": materialized_at,
                        "source_event_ids": [event_id],
                    }
                },
            )
        )
    return events


def _add_verification_events(
    *,
    candidate_id: str,
    root_object_id: str,
    change_kind: str,
    target_object_id: str,
    materialized_at: str,
) -> list[dict[str, Any]]:
    verification_id = f"VER-{candidate_id[3:]}"
    rationale = f"Add verification for {target_object_id} after {change_kind} impact from {root_object_id}."
    object_event_id = _proposed_event_id(candidate_id, 1)
    link_event_id = _proposed_event_id(candidate_id, 2)
    return [
        _event_spec(
            event_id=object_event_id,
            event_type="object_recorded",
            ts=materialized_at,
            payload={
                "object": {
                    "id": verification_id,
                    "type": "verification",
                    "title": f"Verify {target_object_id}",
                    "body": rationale,
                    "status": "planned",
                    "created_at": materialized_at,
                    "updated_at": None,
                    "source_event_ids": [object_event_id],
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
        ),
        _event_spec(
            event_id=link_event_id,
            event_type="object_linked",
            ts=materialized_at,
            payload={
                "link": {
                    "id": f"L-{verification_id}-verifies-{target_object_id}",
                    "source_object_id": verification_id,
                    "relation": "verifies",
                    "target_object_id": target_object_id,
                    "rationale": rationale,
                    "created_at": materialized_at,
                    "source_event_ids": [link_event_id],
                }
            },
        ),
    ]


def _status_change_event(
    candidate_id: str,
    sequence: int,
    target_object_id: str,
    from_status: str,
    to_status: str,
    changed_at: str,
    reason: str,
) -> dict[str, Any]:
    return _event_spec(
        event_id=_proposed_event_id(candidate_id, sequence),
        event_type="object_status_changed",
        ts=changed_at,
        payload={
            "object_id": target_object_id,
            "from_status": from_status,
            "to_status": to_status,
            "reason": reason,
            "changed_at": changed_at,
        },
    )


def _decision_invalidated_by_event(
    candidate_id: str,
    sequence: int,
    target_object_id: str,
    root_object_id: str,
    invalidated_at: str,
    reason: str,
) -> dict[str, Any]:
    return _event_spec(
        event_id=_proposed_event_id(candidate_id, sequence),
        event_type="object_updated",
        ts=invalidated_at,
        payload={
            "object_id": target_object_id,
            "patch": {
                "metadata": {
                    "invalidated_by": {
                        "decision_id": root_object_id,
                        "invalidated_at": invalidated_at,
                        "reason": reason,
                    }
                }
            },
        },
    )


def _event_spec(*, event_id: str, event_type: str, ts: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "ts": ts,
        "payload": payload,
    }


def _proposed_event_id(candidate_id: str, sequence: int) -> str:
    return f"E-{candidate_id[3:]}-{sequence:02d}"


def _materialization_reason(materialization_status: str, candidate_kind: str) -> str:
    if materialization_status == "materialized":
        return f"{candidate_kind} candidate can be represented as deterministic event specs."
    return f"{candidate_kind} candidate requires human-authored runtime changes before materialization."


def _can_invalidate_decision(root_node: dict[str, Any]) -> bool:
    return root_node["object_type"] == "decision" and root_node.get("status") in {"accepted", "resolved-by-evidence"}


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


def _require_candidate(report: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    for candidate in report["candidates"]:
        if candidate["candidate_id"] == candidate_id:
            return candidate
    raise ValueError(f"unknown or stale invalidation candidate: {candidate_id}")


def _validate_candidate_application(
    candidate: dict[str, Any],
    gate: dict[str, Any],
    *,
    reason: str | None,
    safety_approval_id: str | None,
) -> None:
    if candidate["materialization_status"] != "materialized" or not candidate["proposed_events"]:
        raise ValueError(
            f"invalidation candidate {candidate['candidate_id']} cannot be applied automatically; "
            f"materialization_status={candidate['materialization_status']}"
        )
    if candidate["severity"] == "critical":
        raise ValueError("critical severity candidate requires external review or must be blocked")
    if candidate["severity"] in _REASON_REQUIRED_SEVERITIES and reason is None:
        raise ValueError(f"reason is required to apply {candidate['severity']} severity candidate")
    if candidate["severity"] == "high":
        if not safety_approval_id:
            raise ValueError(
                f"safety approval artifact is required for high severity candidate {candidate['candidate_id']}"
            )
        if safety_approval_id not in gate["approval_artifact_ids"]:
            raise ValueError(
                f"safety approval artifact {safety_approval_id} does not satisfy current gate "
                f"{gate['gate_digest']}"
            )
    if gate["gate_status"] == "blocked":
        joined = ", ".join(gate["blocking_reasons"]) or "blocked"
        raise ValueError(f"safety gate blocks candidate target {candidate['target_object_id']}: {joined}")
    if gate["gate_status"] == "needs_approval":
        if not safety_approval_id:
            raise ValueError(
                f"safety approval artifact is required for candidate target {candidate['target_object_id']}"
            )
        if safety_approval_id not in gate["approval_artifact_ids"]:
            raise ValueError(
                f"safety approval artifact {safety_approval_id} does not satisfy current gate "
                f"{gate['gate_digest']}"
            )


def _candidate_event_specs(
    candidate: dict[str, Any],
    *,
    session_id: str,
    reason: str | None,
    actor: str | None,
) -> list[dict[str, Any]]:
    specs = []
    for proposed in candidate["proposed_events"]:
        spec = deepcopy(proposed)
        spec["session_id"] = session_id
        if reason is not None or actor is not None:
            _annotate_apply_reason(spec, candidate, reason=reason, actor=actor)
        specs.append(spec)
    return specs


def _annotate_apply_reason(
    spec: dict[str, Any],
    candidate: dict[str, Any],
    *,
    reason: str | None,
    actor: str | None,
) -> None:
    apply_reason = reason or candidate["reason"]
    actor_suffix = f" Approved by {actor}." if actor else ""
    payload = spec["payload"]
    if spec["event_type"] == "object_status_changed":
        payload["reason"] = apply_reason + actor_suffix
    elif spec["event_type"] == "object_updated":
        metadata = payload.get("patch", {}).get("metadata", {})
        invalidated_by = metadata.get("invalidated_by")
        if isinstance(invalidated_by, dict):
            invalidated_by["reason"] = apply_reason + actor_suffix
    elif spec["event_type"] == "object_linked":
        link = payload.get("link", {})
        if isinstance(link, dict):
            link["rationale"] = apply_reason + actor_suffix
    elif spec["event_type"] == "object_recorded":
        obj = payload.get("object", {})
        if isinstance(obj, dict):
            obj["body"] = obj.get("body") or apply_reason
            metadata = obj.setdefault("metadata", {})
            metadata["invalidation_candidate_id"] = candidate["candidate_id"]
            if actor:
                metadata["approved_by"] = actor
            if reason:
                metadata["approval_reason"] = reason


def _select_apply_session(bundle: dict[str, Any], session_id: str | None) -> str:
    if session_id is not None:
        session = bundle.get("sessions", {}).get(session_id)
        if session is None:
            raise ValueError(f"unknown session_id: {session_id}")
        if session["session"]["lifecycle"]["status"] == "closed":
            raise ValueError(f"cannot apply invalidation candidate in closed session: {session_id}")
        return session_id
    open_sessions = [
        item["session"]["id"]
        for item in bundle.get("sessions", {}).values()
        if item["session"]["lifecycle"]["status"] != "closed"
    ]
    if not open_sessions:
        raise ValueError("session_id is required because no open session exists")
    return sorted(open_sessions)[0]


def _apply_result(
    status: str,
    candidate: dict[str, Any],
    gate: dict[str, Any],
    *,
    approved: bool,
    event_ids: list[str],
    session_id: str | None,
    reason: str | None,
    actor: str | None,
    committed_events: list[dict[str, Any]] | None = None,
    gate_before: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "status": status,
        "approved": approved,
        "candidate_id": candidate["candidate_id"],
        "candidate_kind": candidate["candidate_kind"],
        "target_object_id": candidate["target_object_id"],
        "target_object_type": candidate["target_object_type"],
        "severity": candidate["severity"],
        "requires_human_approval": candidate["requires_human_approval"],
        "materialization_status": candidate["materialization_status"],
        "session_id": session_id,
        "actor": actor,
        "reason": reason,
        "event_ids": event_ids,
        "committed_events": committed_events or [],
        "proposed_events": candidate["proposed_events"],
        "safety_gate": {
            "gate_status": gate["gate_status"],
            "gate_digest": gate["gate_digest"],
            "risk_tier": gate["risk_tier"],
            "approval_required": gate["approval_required"],
            "approval_satisfied": gate["approval_satisfied"],
            "approval_artifact_ids": gate["approval_artifact_ids"],
            "blocking_reasons": gate["blocking_reasons"],
            "approval_reasons": gate["approval_reasons"],
        },
    }
    if gate_before is not None:
        result["safety_gate_before"] = {
            "gate_status": gate_before["gate_status"],
            "gate_digest": gate_before["gate_digest"],
            "risk_tier": gate_before["risk_tier"],
            "approval_required": gate_before["approval_required"],
            "approval_satisfied": gate_before["approval_satisfied"],
            "approval_artifact_ids": gate_before["approval_artifact_ids"],
            "blocking_reasons": gate_before["blocking_reasons"],
            "approval_reasons": gate_before["approval_reasons"],
        }
    return result


def _event_summaries(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "tx_id": event.get("tx_id"),
            "tx_index": event.get("tx_index"),
            "event_id": event["event_id"],
            "event_type": event["event_type"],
            "session_id": event.get("session_id"),
        }
        for event in events
    ]


def _require_text(value: str | None, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _optional_text(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string when provided")
    return value.strip()
