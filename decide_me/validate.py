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
    for session in bundle["sessions"].values():
        validate_session_state(session)


def validate_event_log(events: list[dict[str, Any]]) -> None:
    previous_version = 0
    for event in events:
        validate_event(event)
        if event["event_type"] not in EVENT_TYPES:
            raise StateValidationError(f"unsupported event type in log: {event['event_type']}")
        if event["project_version_after"] <= previous_version:
            raise StateValidationError("event log project_version_after must be strictly increasing")
        previous_version = event["project_version_after"]
