from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from decide_me.constants import (
    ACCEPTED_VIA_VALUES,
    DISCOVERABLE_DECISION_FIELDS,
    DISCOVERABLE_DECISION_STATUSES,
    EVIDENCE_SOURCES,
    FORBIDDEN_DISCOVERED_DECISION_FIELDS,
)


AUTO_PROJECT_VERSION = "__AUTO_PROJECT_VERSION__"

EVENT_TYPES = {
    "project_initialized",
    "session_created",
    "session_resumed",
    "decision_discovered",
    "decision_enriched",
    "question_asked",
    "proposal_issued",
    "proposal_accepted",
    "proposal_rejected",
    "decision_deferred",
    "decision_resolved_by_evidence",
    "decision_invalidated",
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
    "decision_enriched": ("decision_id",),
    "question_asked": ("decision_id", "question_id", "question"),
    "proposal_issued": ("proposal",),
    "proposal_accepted": (
        "proposal_id",
        "origin_session_id",
        "target_type",
        "target_id",
        "accepted_answer",
    ),
    "proposal_rejected": ("proposal_id", "origin_session_id", "target_type", "target_id", "reason"),
    "decision_deferred": ("decision_id", "reason"),
    "decision_resolved_by_evidence": ("decision_id", "source", "summary", "evidence_refs"),
    "decision_invalidated": ("decision_id", "invalidated_by_decision_id", "reason"),
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


def _require_non_empty_string(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise EventValidationError(f"{label} must be a non-empty string")


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
        _require_non_empty_string(session.get("id"), "session_created.payload.session.id")
        _require_non_empty_string(session.get("started_at"), "session_created.payload.session.started_at")
        _require_non_empty_string(session.get("last_seen_at"), "session_created.payload.session.last_seen_at")
    elif event_type == "decision_discovered":
        decision = _require_dict(payload["decision"], "decision_discovered.payload.decision")
        _require_keys(decision, ("id", "title"), "decision")
        _require_non_empty_string(decision.get("id"), "decision_discovered.payload.decision.id")
        _require_non_empty_string(decision.get("title"), "decision_discovered.payload.decision.title")
        forbidden = sorted(set(decision) & FORBIDDEN_DISCOVERED_DECISION_FIELDS)
        if forbidden:
            raise EventValidationError(
                f"decision_discovered.payload.decision must not include {', '.join(forbidden)}"
            )
        unknown = sorted(set(decision) - (DISCOVERABLE_DECISION_FIELDS | {"status"}))
        if unknown:
            raise EventValidationError(
                f"decision_discovered.payload.decision contains unsupported fields: {', '.join(unknown)}"
            )
        status = decision.get("status")
        if status is not None and status not in DISCOVERABLE_DECISION_STATUSES:
            allowed = ", ".join(sorted(DISCOVERABLE_DECISION_STATUSES))
            raise EventValidationError(f"decision_discovered.payload.decision.status must be one of: {allowed}")
    elif event_type == "decision_enriched":
        if "notes_append" in payload and not isinstance(payload["notes_append"], list):
            raise EventValidationError("decision_enriched.payload.notes_append must be a list")
        if "revisit_triggers_append" in payload and not isinstance(payload["revisit_triggers_append"], list):
            raise EventValidationError(
                "decision_enriched.payload.revisit_triggers_append must be a list"
            )
        if "context_append" in payload and not isinstance(payload["context_append"], str):
            raise EventValidationError("decision_enriched.payload.context_append must be a string")
    elif event_type == "question_asked":
        _require_non_empty_string(payload.get("question_id"), "question_asked.payload.question_id")
        _require_non_empty_string(payload.get("question"), "question_asked.payload.question")
    elif event_type == "decision_deferred":
        _require_non_empty_string(payload.get("reason"), "decision_deferred.payload.reason")
    elif event_type == "decision_invalidated":
        _require_non_empty_string(payload.get("decision_id"), "decision_invalidated.payload.decision_id")
        _require_non_empty_string(
            payload.get("invalidated_by_decision_id"),
            "decision_invalidated.payload.invalidated_by_decision_id",
        )
        _require_non_empty_string(payload.get("reason"), "decision_invalidated.payload.reason")
        if payload["decision_id"] == payload["invalidated_by_decision_id"]:
            raise EventValidationError("decision_invalidated must not self-reference")
    elif event_type == "session_closed":
        _require_non_empty_string(payload.get("closed_at"), "session_closed.payload.closed_at")
    elif event_type == "decision_resolved_by_evidence":
        if payload["source"] not in EVIDENCE_SOURCES:
            raise EventValidationError(f"invalid evidence source: {payload['source']}")
        if not isinstance(payload["summary"], str) or not payload["summary"].strip():
            raise EventValidationError("decision_resolved_by_evidence.payload.summary must be a non-empty string")
        if not isinstance(payload["evidence_refs"], list):
            raise EventValidationError("decision_resolved_by_evidence.payload.evidence_refs must be a list")
    elif event_type == "proposal_issued":
        proposal = _require_dict(payload["proposal"], "proposal_issued.payload.proposal")
        _require_keys(
            proposal,
            (
                "proposal_id",
                "origin_session_id",
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
        for key in (
            "proposal_id",
            "origin_session_id",
            "target_type",
            "target_id",
            "question_id",
            "question",
            "recommendation",
            "why",
            "if_not",
            "activated_at",
        ):
            _require_non_empty_string(proposal.get(key), f"proposal_issued.payload.proposal.{key}")
    elif event_type == "proposal_accepted":
        for key in ("proposal_id", "origin_session_id", "target_type", "target_id"):
            _require_non_empty_string(payload.get(key), f"proposal_accepted.payload.{key}")
        accepted_answer = _require_dict(
            payload["accepted_answer"], "proposal_accepted.payload.accepted_answer"
        )
        _require_keys(
            accepted_answer,
            ("summary", "accepted_at", "accepted_via", "proposal_id"),
            "accepted_answer",
        )
        for key in ("summary", "accepted_at", "proposal_id"):
            _require_non_empty_string(
                accepted_answer.get(key),
                f"proposal_accepted.payload.accepted_answer.{key}",
            )
        if accepted_answer["accepted_via"] not in ACCEPTED_VIA_VALUES:
            allowed = ", ".join(sorted(ACCEPTED_VIA_VALUES))
            raise EventValidationError(
                f"proposal_accepted.payload.accepted_answer.accepted_via must be one of: {allowed}"
            )
    elif event_type == "proposal_rejected":
        for key in ("proposal_id", "origin_session_id", "target_type", "target_id", "reason"):
            _require_non_empty_string(payload.get(key), f"proposal_rejected.payload.{key}")
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
    _require_non_empty_string(event["session_id"], "event.session_id")
    if event["event_type"] not in EVENT_TYPES:
        raise EventValidationError(f"unsupported event_type: {event['event_type']}")
    if not isinstance(event["project_version_after"], int) or event["project_version_after"] < 1:
        raise EventValidationError("project_version_after must be a positive integer")
    payload = _require_dict(event["payload"], "event.payload")
    validate_payload(event["event_type"], payload)
    if event["event_type"] == "proposal_issued":
        proposal = payload["proposal"]
        if proposal["origin_session_id"] != event["session_id"]:
            raise EventValidationError("proposal_issued origin_session_id must match event.session_id")
    elif event["event_type"] in {"proposal_accepted", "proposal_rejected"}:
        if payload["origin_session_id"] != event["session_id"]:
            raise EventValidationError(f"{event['event_type']} origin_session_id must match event.session_id")


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
