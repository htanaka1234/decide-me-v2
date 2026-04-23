from __future__ import annotations

from typing import Any

from decide_me.events import EVENT_TYPES, validate_event
from decide_me.taxonomy import taxonomy_by_id


OPEN_DECISION_STATUSES = {"unresolved", "proposed", "rejected", "blocked"}
ALL_DECISION_STATUSES = OPEN_DECISION_STATUSES | {
    "accepted",
    "deferred",
    "resolved-by-evidence",
    "invalidated",
}


class StateValidationError(ValueError):
    """Raised when a projection is malformed."""


def _require_keys(payload: dict[str, Any], keys: tuple[str, ...], label: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise StateValidationError(f"{label} is missing required keys: {', '.join(missing)}")


def validate_project_state(project_state: dict[str, Any]) -> None:
    _require_keys(
        project_state,
        ("schema_version", "project", "state", "protocol", "counts", "default_bundles", "decisions"),
        "project_state",
    )
    _require_keys(
        project_state["project"],
        ("name", "objective", "current_milestone", "stop_rule"),
        "project_state.project",
    )
    _require_keys(
        project_state["state"],
        ("project_version", "updated_at", "last_event_id"),
        "project_state.state",
    )
    if not isinstance(project_state["decisions"], list):
        raise StateValidationError("project_state.decisions must be a list")

    decision_ids: set[str] = set()
    for decision in project_state["decisions"]:
        _require_keys(
            decision,
            (
                "id",
                "title",
                "kind",
                "domain",
                "priority",
                "frontier",
                "status",
                "resolvable_by",
                "reversibility",
                "depends_on",
                "blocked_by",
                "question",
                "context",
                "options",
                "recommendation",
                "accepted_answer",
                "resolved_by_evidence",
                "evidence_refs",
                "revisit_triggers",
                "notes",
                "bundle_id",
                "invalidated_by",
            ),
            f"decision[{decision.get('id', '?')}]",
        )
        if decision["status"] not in ALL_DECISION_STATUSES:
            raise StateValidationError(f"unsupported decision status: {decision['status']}")
        if decision["id"] in decision_ids:
            raise StateValidationError(f"duplicate decision id: {decision['id']}")
        decision_ids.add(decision["id"])


def validate_session_state(session_state: dict[str, Any]) -> None:
    _require_keys(
        session_state,
        ("schema_version", "session", "summary", "classification", "close_summary", "working_state"),
        "session_state",
    )
    _require_keys(
        session_state["session"],
        ("id", "started_at", "last_seen_at", "bound_context_hint", "decision_ids", "lifecycle"),
        "session_state.session",
    )
    _require_keys(
        session_state["summary"],
        ("latest_summary", "current_question_preview", "active_decision_id"),
        "session_state.summary",
    )
    _require_keys(
        session_state["classification"],
        (
            "domain",
            "abstraction_level",
            "assigned_tags",
            "compatibility_tags",
            "search_terms",
            "source_refs",
            "updated_at",
        ),
        "session_state.classification",
    )
    _require_keys(
        session_state["close_summary"],
        (
            "work_item_title",
            "work_item_statement",
            "goal",
            "readiness",
            "accepted_decisions",
            "deferred_decisions",
            "unresolved_blockers",
            "unresolved_risks",
            "candidate_workstreams",
            "candidate_action_slices",
            "evidence_refs",
            "generated_at",
        ),
        "session_state.close_summary",
    )
    _require_keys(
        session_state["working_state"],
        ("current_question_id", "current_question", "active_proposal", "last_seen_project_version"),
        "session_state.working_state",
    )


def validate_taxonomy_state(taxonomy_state: dict[str, Any]) -> None:
    _require_keys(taxonomy_state, ("schema_version", "state", "required_axes", "nodes"), "taxonomy_state")
    _require_keys(taxonomy_state["state"], ("updated_at", "last_event_id"), "taxonomy_state.state")
    node_ids = taxonomy_by_id(taxonomy_state)
    if len(node_ids) != len(taxonomy_state["nodes"]):
        raise StateValidationError("taxonomy_state.nodes contains duplicate ids")
    for node in taxonomy_state["nodes"]:
        _require_keys(
            node,
            ("id", "axis", "label", "aliases", "parent_id", "replaced_by", "status", "created_at", "updated_at"),
            f"taxonomy node {node.get('id', '?')}",
        )


def validate_projection_bundle(bundle: dict[str, Any]) -> None:
    _require_keys(bundle, ("project_state", "taxonomy_state", "sessions"), "projection_bundle")
    validate_project_state(bundle["project_state"])
    validate_taxonomy_state(bundle["taxonomy_state"])
    if not isinstance(bundle["sessions"], dict):
        raise StateValidationError("projection_bundle.sessions must be a dictionary")
    decisions_by_id = _decision_index(bundle["project_state"])
    taxonomy_ids = set(taxonomy_by_id(bundle["taxonomy_state"]))
    for session_id, session in bundle["sessions"].items():
        validate_session_state(session)
        _validate_session_integrity(session_id, session, decisions_by_id, taxonomy_ids)
    _validate_decision_references(decisions_by_id)


def _decision_index(project_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {decision["id"]: decision for decision in project_state["decisions"]}


def _visible_decision_ids(decisions_by_id: dict[str, dict[str, Any]]) -> set[str]:
    return {
        decision_id
        for decision_id, decision in decisions_by_id.items()
        if decision.get("status") != "invalidated"
    }


def _validate_decision_references(decisions_by_id: dict[str, dict[str, Any]]) -> None:
    for decision_id, decision in decisions_by_id.items():
        for key in ("depends_on", "blocked_by"):
            for referenced_id in decision.get(key, []):
                if referenced_id not in decisions_by_id:
                    raise StateValidationError(
                        f"decision {decision_id}.{key} references unknown decision {referenced_id}"
                    )

        invalidated_by = decision.get("invalidated_by")
        if decision["status"] == "invalidated":
            if not invalidated_by or invalidated_by.get("decision_id") not in decisions_by_id:
                raise StateValidationError(f"decision {decision_id} has invalid invalidated_by reference")
        elif invalidated_by is not None:
            raise StateValidationError(f"non-invalidated decision {decision_id} must not carry invalidated_by")

        accepted_proposal_id = decision.get("accepted_answer", {}).get("proposal_id")
        recommended_proposal_id = decision.get("recommendation", {}).get("proposal_id")
        if accepted_proposal_id and accepted_proposal_id != recommended_proposal_id:
            raise StateValidationError(
                f"decision {decision_id} accepted_answer.proposal_id does not match recommendation.proposal_id"
            )


def _validate_session_integrity(
    session_key: str,
    session: dict[str, Any],
    decisions_by_id: dict[str, dict[str, Any]],
    taxonomy_ids: set[str],
) -> None:
    session_id = session["session"]["id"]
    if session_id != session_key:
        raise StateValidationError(f"session map key {session_key} does not match session id {session_id}")

    visible_ids = _visible_decision_ids(decisions_by_id)
    decision_ids = session["session"]["decision_ids"]
    if len(decision_ids) != len(set(decision_ids)):
        raise StateValidationError(f"session {session_id} contains duplicate decision_ids")
    for decision_id in decision_ids:
        if decision_id not in decisions_by_id:
            raise StateValidationError(f"session {session_id} references unknown decision {decision_id}")
        if decision_id not in visible_ids:
            raise StateValidationError(f"session {session_id} references invalidated decision {decision_id}")

    active_decision_id = session["summary"].get("active_decision_id")
    if active_decision_id and active_decision_id not in set(decision_ids):
        raise StateValidationError(f"session {session_id} active_decision_id is not bound to the session")
    if active_decision_id and active_decision_id not in visible_ids:
        raise StateValidationError(f"session {session_id} active_decision_id references invalidated decision")

    _validate_classification_refs(session_id, session, taxonomy_ids)
    _validate_active_proposal(session_id, session, decisions_by_id, visible_ids, set(decision_ids))
    _validate_close_summary(session_id, session, decisions_by_id, visible_ids, set(decision_ids))


def _validate_classification_refs(
    session_id: str, session: dict[str, Any], taxonomy_ids: set[str]
) -> None:
    classification = session["classification"]
    for key in ("assigned_tags", "compatibility_tags"):
        for tag_ref in classification.get(key, []):
            if tag_ref not in taxonomy_ids:
                raise StateValidationError(f"session {session_id} {key} references unknown taxonomy node {tag_ref}")


def _validate_active_proposal(
    session_id: str,
    session: dict[str, Any],
    decisions_by_id: dict[str, dict[str, Any]],
    visible_ids: set[str],
    session_decision_ids: set[str],
) -> None:
    working_state = session["working_state"]
    active = working_state["active_proposal"]
    _require_keys(
        active,
        (
            "proposal_id",
            "origin_session_id",
            "target_type",
            "target_id",
            "recommendation_version",
            "based_on_project_version",
            "is_active",
            "activated_at",
            "inactive_reason",
            "question_id",
            "question",
            "recommendation",
            "why",
            "if_not",
        ),
        f"session {session_id} active_proposal",
    )

    lifecycle_status = session["session"]["lifecycle"]["status"]
    if lifecycle_status == "closed" and active.get("is_active"):
        raise StateValidationError(f"closed session {session_id} must not have an active proposal")
    if lifecycle_status == "closed" and (
        working_state.get("current_question_id") or working_state.get("current_question")
    ):
        raise StateValidationError(f"closed session {session_id} must not have current question state")

    proposal_id = active.get("proposal_id")
    if not proposal_id:
        return

    if active.get("origin_session_id") != session_id:
        raise StateValidationError(f"session {session_id} active proposal has wrong origin_session_id")

    target_id = active.get("target_id")
    if not target_id:
        if active.get("is_active"):
            raise StateValidationError(f"session {session_id} active proposal is missing target_id")
        return
    if active.get("target_type") != "decision":
        raise StateValidationError(f"session {session_id} active proposal has unsupported target_type")
    if target_id not in decisions_by_id:
        raise StateValidationError(f"session {session_id} active proposal references unknown decision {target_id}")
    if target_id not in visible_ids:
        raise StateValidationError(f"session {session_id} active proposal references invalidated decision {target_id}")
    if target_id not in session_decision_ids:
        raise StateValidationError(f"session {session_id} active proposal target is not bound to the session")

    if active.get("is_active"):
        decision = decisions_by_id[target_id]
        if session["summary"].get("active_decision_id") != target_id:
            raise StateValidationError(f"session {session_id} active proposal does not match active_decision_id")
        if decision.get("recommendation", {}).get("proposal_id") != proposal_id:
            raise StateValidationError(f"session {session_id} active proposal is not the decision recommendation")


def _validate_close_summary(
    session_id: str,
    session: dict[str, Any],
    decisions_by_id: dict[str, dict[str, Any]],
    visible_ids: set[str],
    session_decision_ids: set[str],
) -> None:
    close_summary = session["close_summary"]
    visible_session_ids = session_decision_ids & visible_ids
    for key in (
        "accepted_decisions",
        "deferred_decisions",
        "unresolved_blockers",
        "unresolved_risks",
    ):
        for item in close_summary.get(key, []):
            decision_id = item.get("id")
            _require_visible_summary_decision(session_id, key, decision_id, visible_session_ids)

    action_decision_ids: set[str] = set()
    for action_slice in close_summary.get("candidate_action_slices", []):
        decision_id = action_slice.get("decision_id")
        _require_visible_summary_decision(
            session_id, "candidate_action_slices", decision_id, visible_session_ids
        )
        decision = decisions_by_id[decision_id]
        if decision["status"] not in {"accepted", "resolved-by-evidence"}:
            raise StateValidationError(
                f"session {session_id} candidate_action_slices references non-accepted decision {decision_id}"
            )
        action_decision_ids.add(decision_id)

    for workstream in close_summary.get("candidate_workstreams", []):
        for key in ("scope", "implementation_ready_scope"):
            for decision_id in workstream.get(key, []):
                _require_visible_summary_decision(
                    session_id,
                    f"candidate_workstreams.{key}",
                    decision_id,
                    visible_session_ids,
                )
        for decision_id in workstream.get("implementation_ready_scope", []):
            if decision_id not in action_decision_ids:
                raise StateValidationError(
                    f"session {session_id} workstream implementation_ready_scope is missing action slice {decision_id}"
                )


def _require_visible_summary_decision(
    session_id: str, section: str, decision_id: str | None, visible_session_ids: set[str]
) -> None:
    if not decision_id:
        raise StateValidationError(f"session {session_id} {section} item is missing a decision id")
    if decision_id not in visible_session_ids:
        raise StateValidationError(f"session {session_id} {section} references non-visible decision {decision_id}")


def validate_event_log(events: list[dict[str, Any]]) -> None:
    previous_version = 0
    for event in events:
        validate_event(event)
        if event["event_type"] not in EVENT_TYPES:
            raise StateValidationError(f"unsupported event type in log: {event['event_type']}")
        if event["project_version_after"] <= previous_version:
            raise StateValidationError("event log project_version_after must be strictly increasing")
        previous_version = event["project_version_after"]
