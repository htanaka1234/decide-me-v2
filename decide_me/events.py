from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


AUTO_PROJECT_VERSION = "__AUTO_PROJECT_VERSION__"

EVENT_TYPES = {
    "project_initialized",
    "session_created",
    "session_resumed",
    "decision_discovered",
    "question_asked",
    "proposal_issued",
    "proposal_accepted",
    "proposal_rejected",
    "decision_deferred",
    "decision_resolved_by_evidence",
    "classification_updated",
    "close_summary_generated",
    "session_closed",
    "plan_generated",
    "taxonomy_extended",
    "compatibility_backfilled",
}

REQUIRED_PAYLOAD_KEYS: dict[str, tuple[str, ...]] = {
    "project_initialized": ("project",),
    "session_created": ("session",),
    "session_resumed": ("resumed_at",),
    "decision_discovered": ("decision",),
    "question_asked": ("decision_id", "question_id", "question"),
    "proposal_issued": ("proposal",),
    "proposal_accepted": ("proposal_id", "target_type", "target_id", "accepted_answer"),
    "proposal_rejected": ("proposal_id", "target_type", "target_id", "reason"),
    "decision_deferred": ("decision_id", "reason"),
    "decision_resolved_by_evidence": ("decision_id", "source", "summary", "evidence_refs"),
    "classification_updated": ("classification",),
    "close_summary_generated": ("close_summary",),
    "session_closed": ("closed_at",),
    "plan_generated": ("session_ids", "status"),
    "taxonomy_extended": ("nodes",),
    "compatibility_backfilled": ("additions",),
}


class EventValidationError(ValueError):
    """Raised when an event envelope or payload is malformed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_entity_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{stamp}-{uuid4().hex[:4]}"


def make_event_id(sequence: int, timestamp: str) -> str:
    date = timestamp[:10].replace("-", "")
    return f"E-{date}-{sequence:06d}"


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EventValidationError(f"{label} must be an object")
    return value


def _require_keys(payload: dict[str, Any], keys: tuple[str, ...], label: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        joined = ", ".join(missing)
        raise EventValidationError(f"{label} is missing required keys: {joined}")


def prepare_payload(
    event_type: str, payload: dict[str, Any], project_version_after: int
) -> dict[str, Any]:
    prepared = deepcopy(payload)
    if event_type == "proposal_issued":
        proposal = _require_dict(prepared.get("proposal"), "proposal_issued.payload.proposal")
        if proposal.get("based_on_project_version") in {None, AUTO_PROJECT_VERSION}:
            proposal["based_on_project_version"] = project_version_after
    return prepared


def validate_payload(event_type: str, payload: dict[str, Any]) -> None:
    _require_keys(payload, REQUIRED_PAYLOAD_KEYS.get(event_type, ()), f"{event_type}.payload")

    if event_type == "project_initialized":
        project = _require_dict(payload["project"], "project_initialized.payload.project")
        _require_keys(project, ("name", "objective", "current_milestone", "stop_rule"), "project")
    elif event_type == "session_created":
        session = _require_dict(payload["session"], "session_created.payload.session")
        _require_keys(session, ("id", "started_at", "last_seen_at", "bound_context_hint"), "session")
    elif event_type == "decision_discovered":
        decision = _require_dict(payload["decision"], "decision_discovered.payload.decision")
        _require_keys(decision, ("id", "title"), "decision")
    elif event_type == "proposal_issued":
        proposal = _require_dict(payload["proposal"], "proposal_issued.payload.proposal")
        _require_keys(
            proposal,
            (
                "proposal_id",
                "target_type",
                "target_id",
                "recommendation_version",
                "based_on_project_version",
                "question_id",
                "question",
                "recommendation",
                "why",
                "if_not",
                "is_active",
                "activated_at",
                "inactive_reason",
            ),
            "proposal",
        )
    elif event_type == "proposal_accepted":
        accepted_answer = _require_dict(
            payload["accepted_answer"], "proposal_accepted.payload.accepted_answer"
        )
        _require_keys(
            accepted_answer,
            ("summary", "accepted_at", "accepted_via", "proposal_id"),
            "accepted_answer",
        )
    elif event_type == "classification_updated":
        classification = _require_dict(
            payload["classification"], "classification_updated.payload.classification"
        )
        _require_keys(
            classification,
            (
                "domain",
                "abstraction_level",
                "assigned_tags",
                "compatibility_tags",
                "search_terms",
                "source_refs",
                "updated_at",
            ),
            "classification",
        )
    elif event_type == "close_summary_generated":
        close_summary = _require_dict(
            payload["close_summary"], "close_summary_generated.payload.close_summary"
        )
        _require_keys(
            close_summary,
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
            "close_summary",
        )
    elif event_type == "taxonomy_extended":
        nodes = payload["nodes"]
        if not isinstance(nodes, list):
            raise EventValidationError("taxonomy_extended.payload.nodes must be a list")


def validate_event(event: dict[str, Any]) -> None:
    _require_keys(
        event,
        ("event_id", "ts", "session_id", "event_type", "project_version_after", "payload"),
        "event",
    )
    if event["event_type"] not in EVENT_TYPES:
        raise EventValidationError(f"unsupported event_type: {event['event_type']}")
    if not isinstance(event["project_version_after"], int) or event["project_version_after"] < 1:
        raise EventValidationError("project_version_after must be a positive integer")
    payload = _require_dict(event["payload"], "event.payload")
    validate_payload(event["event_type"], payload)


def build_event(
    *,
    sequence: int,
    session_id: str,
    event_type: str,
    project_version_after: int,
    payload: dict[str, Any],
    timestamp: str | None = None,
) -> dict[str, Any]:
    ts = timestamp or utc_now()
    prepared = prepare_payload(event_type, payload, project_version_after)
    event = {
        "event_id": make_event_id(sequence, ts),
        "ts": ts,
        "session_id": session_id,
        "event_type": event_type,
        "project_version_after": project_version_after,
        "payload": prepared,
    }
    validate_event(event)
    return event
