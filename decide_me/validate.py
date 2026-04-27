from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from decide_me.constants import ACCEPTED_VIA_VALUES, DOMAIN_VALUES, EVIDENCE_SOURCES
from decide_me.events import EVENT_TYPES, validate_event
from decide_me.projections import (
    LINK_RELATIONS,
    OBJECT_TYPES,
    PROJECT_STATE_SCHEMA_VERSION,
    SESSION_STATE_SCHEMA_VERSION,
)
from decide_me.requirement_ids import is_requirement_id
from decide_me.suppression import (
    has_remaining_suppressed_scope,
    has_suppressed_context_remainders,
    suppressed_decision_ids,
)
from decide_me.taxonomy import taxonomy_by_id


OPEN_DECISION_STATUSES = {"unresolved", "proposed", "rejected", "blocked"}
FINAL_INVALIDATING_STATUSES = {"accepted", "resolved-by-evidence"}
ALL_DECISION_STATUSES = OPEN_DECISION_STATUSES | {
    "accepted",
    "deferred",
    "resolved-by-evidence",
    "invalidated",
}
PRIORITIES = {"P0", "P1", "P2"}
FRONTIERS = {"now", "later", "discovered-later", "deferred"}
KINDS = {"choice", "constraint", "risk", "dependency"}
RESOLVABLE_BY = {"human", "codebase", "docs", "tests", "external"}
REVERSIBILITY = {"reversible", "hard-to-reverse", "irreversible", "unknown"}
SESSION_LIFECYCLE_STATUSES = {"active", "closed"}
TAXONOMY_AXES = {"domain", "abstraction_level", "tag"}
TAXONOMY_STATUSES = {"active", "replaced"}
SYSTEM_SESSION_ID = "SYSTEM"
SESSION_RELATIONSHIPS = {"derived_from", "refines", "supersedes", "depends_on", "contradicts"}
SYSTEM_EVENT_TYPES = {
    "project_initialized",
    "plan_generated",
}
SESSION_SCOPED_EVENT_TYPES = {
    "session_created",
    "session_resumed",
    "object_recorded",
    "object_updated",
    "object_status_changed",
    "object_linked",
    "object_unlinked",
    "session_question_asked",
    "session_answer_recorded",
    "close_summary_generated",
    "session_closed",
    "taxonomy_extended",
    "transaction_rejected",
}
SESSION_MUTATION_EVENT_TYPES = {
    "session_resumed",
    "object_recorded",
    "object_updated",
    "object_status_changed",
    "object_linked",
    "object_unlinked",
    "session_question_asked",
    "session_answer_recorded",
    "taxonomy_extended",
    "close_summary_generated",
}


class StateValidationError(ValueError):
    """Raised when a projection is malformed."""


def _require_keys(payload: dict[str, Any], keys: tuple[str, ...], label: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise StateValidationError(f"{label} is missing required keys: {', '.join(missing)}")


def _require_timestamp(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise StateValidationError(f"{label} must be a non-empty timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StateValidationError(f"{label} must be ISO-8601/RFC3339-like") from exc


def _require_optional_timestamp(value: Any, label: str) -> None:
    if value is None:
        return
    _require_timestamp(value, label)


def validate_project_state(project_state: dict[str, Any]) -> None:
    if "decisions" in project_state:
        raise StateValidationError("project_state must not contain top-level decisions")
    _require_keys(
        project_state,
        (
            "schema_version",
            "project",
            "state",
            "protocol",
            "sessions_index",
            "counts",
            "objects",
            "links",
            "graph",
        ),
        "project_state",
    )
    allowed_top_level = {
        "schema_version",
        "project",
        "state",
        "protocol",
        "sessions_index",
        "counts",
        "objects",
        "links",
        "graph",
    }
    unknown_top_level = sorted(set(project_state) - allowed_top_level)
    if unknown_top_level:
        raise StateValidationError(
            f"project_state contains unsupported top-level keys: {', '.join(unknown_top_level)}"
        )
    if project_state.get("schema_version") != PROJECT_STATE_SCHEMA_VERSION:
        raise StateValidationError(f"project_state.schema_version must be {PROJECT_STATE_SCHEMA_VERSION}")
    project = _require_dict(project_state["project"], "project_state.project")
    state = _require_dict(project_state["state"], "project_state.state")
    _require_keys(
        project,
        ("name", "objective", "current_milestone", "stop_rule"),
        "project_state.project",
    )
    _require_keys(
        state,
        ("project_head", "event_count", "updated_at", "last_event_id"),
        "project_state.state",
    )
    event_count = state.get("event_count")
    if not isinstance(event_count, int) or event_count < 0:
        raise StateValidationError("project_state.state.event_count must be a non-negative integer")
    if event_count == 0:
        for key in ("name", "objective", "current_milestone", "stop_rule"):
            _require_optional_non_empty_string(project.get(key), f"project_state.project.{key}")
        _require_optional_non_empty_string(state.get("project_head"), "project_state.state.project_head")
        _require_optional_timestamp(state.get("updated_at"), "project_state.state.updated_at")
        _require_optional_non_empty_string(state.get("last_event_id"), "project_state.state.last_event_id")
    else:
        for key in ("name", "objective", "current_milestone", "stop_rule"):
            _require_non_empty_string(project.get(key), f"project_state.project.{key}")
        _require_non_empty_string(state.get("project_head"), "project_state.state.project_head")
        _require_timestamp(state.get("updated_at"), "project_state.state.updated_at")
        _require_non_empty_string(state.get("last_event_id"), "project_state.state.last_event_id")

    _validate_protocol(project_state["protocol"])
    _validate_sessions_index(project_state["sessions_index"])
    _validate_graph(project_state["graph"])
    objects = project_state["objects"]
    links = project_state["links"]
    _require_list(objects, "project_state.objects")
    _require_list(links, "project_state.links")

    object_ids: set[str] = set()
    for item in objects:
        obj = _require_dict(item, "project_state.objects[]")
        _require_keys(
            obj,
            (
                "id",
                "type",
                "title",
                "body",
                "status",
                "created_at",
                "updated_at",
                "source_event_ids",
                "metadata",
            ),
            f"object[{obj.get('id', '?')}]",
        )
        if set(obj) - {
            "id",
            "type",
            "title",
            "body",
            "status",
            "created_at",
            "updated_at",
            "source_event_ids",
            "metadata",
        }:
            raise StateValidationError(f"object {obj.get('id', '?')} contains unsupported keys")
        _require_non_empty_string(obj.get("id"), "project_state.objects[].id")
        _require_enum(obj.get("type"), OBJECT_TYPES, f"object {obj['id']}.type")
        if obj.get("title") is not None:
            _require_non_empty_string(obj.get("title"), f"object {obj['id']}.title")
        if obj.get("body") is not None and not isinstance(obj.get("body"), str):
            raise StateValidationError(f"object {obj['id']}.body must be a string or null")
        _require_non_empty_string(obj.get("status"), f"object {obj['id']}.status")
        _require_timestamp(obj.get("created_at"), f"object {obj['id']}.created_at")
        _require_optional_timestamp(obj.get("updated_at"), f"object {obj['id']}.updated_at")
        _require_source_event_ids(obj.get("source_event_ids"), f"object {obj['id']}.source_event_ids")
        metadata = _require_dict(obj.get("metadata"), f"object {obj['id']}.metadata")
        if obj["id"] in object_ids:
            raise StateValidationError(f"duplicate object id: {obj['id']}")
        object_ids.add(obj["id"])

    link_ids: set[str] = set()
    for item in links:
        link = _require_dict(item, "project_state.links[]")
        _require_keys(
            link,
            (
                "id",
                "source_object_id",
                "relation",
                "target_object_id",
                "rationale",
                "created_at",
                "source_event_ids",
            ),
            f"link[{link.get('id', '?')}]",
        )
        if set(link) - {
            "id",
            "source_object_id",
            "relation",
            "target_object_id",
            "rationale",
            "created_at",
            "source_event_ids",
        }:
            raise StateValidationError(f"link {link.get('id', '?')} contains unsupported keys")
        _require_non_empty_string(link.get("id"), "project_state.links[].id")
        _require_non_empty_string(link.get("source_object_id"), f"link {link['id']}.source_object_id")
        _require_enum(link.get("relation"), LINK_RELATIONS, f"link {link['id']}.relation")
        _require_non_empty_string(link.get("target_object_id"), f"link {link['id']}.target_object_id")
        if link.get("rationale") is not None and not isinstance(link.get("rationale"), str):
            raise StateValidationError(f"link {link['id']}.rationale must be a string or null")
        _require_timestamp(link.get("created_at"), f"link {link['id']}.created_at")
        _require_source_event_ids(link.get("source_event_ids"), f"link {link['id']}.source_event_ids")
        if link["id"] in link_ids:
            raise StateValidationError(f"duplicate link id: {link['id']}")
        link_ids.add(link["id"])
        if link["source_object_id"] not in object_ids:
            raise StateValidationError(f"link {link['id']} source_object_id references missing object")
        if link["target_object_id"] not in object_ids:
            raise StateValidationError(f"link {link['id']} target_object_id references missing object")

    expected_counts = _recomputed_counts(objects, links)
    if project_state["counts"] != expected_counts:
        raise StateValidationError("project_state.counts does not match object/link state")


def _validate_protocol(protocol: Any) -> None:
    protocol_payload = _require_dict(protocol, "project_state.protocol")
    _require_keys(
        protocol_payload,
        ("plain_ok_scope", "proposal_expiry_rules", "close_policy"),
        "project_state.protocol",
    )
    _require_non_empty_string(protocol_payload.get("plain_ok_scope"), "project_state.protocol.plain_ok_scope")
    _require_list(protocol_payload.get("proposal_expiry_rules"), "project_state.protocol.proposal_expiry_rules")
    for item in protocol_payload["proposal_expiry_rules"]:
        _require_non_empty_string(item, "project_state.protocol.proposal_expiry_rules[]")
    _require_non_empty_string(protocol_payload.get("close_policy"), "project_state.protocol.close_policy")


def _validate_sessions_index(sessions_index: Any) -> None:
    index = _require_dict(sessions_index, "project_state.sessions_index")
    for session_id, entry in index.items():
        _require_non_empty_string(session_id, "project_state.sessions_index key")
        session = _require_dict(entry, f"project_state.sessions_index.{session_id}")
        _require_keys(
            session,
            ("id", "status", "started_at", "last_seen_at", "closed_at", "bound_context_hint", "decision_ids"),
            f"project_state.sessions_index.{session_id}",
        )
        if session.get("id") != session_id:
            raise StateValidationError(f"project_state.sessions_index.{session_id}.id must match map key")
        _require_enum(session.get("status"), SESSION_LIFECYCLE_STATUSES, f"project_state.sessions_index.{session_id}.status")
        _require_timestamp(session.get("started_at"), f"project_state.sessions_index.{session_id}.started_at")
        _require_timestamp(session.get("last_seen_at"), f"project_state.sessions_index.{session_id}.last_seen_at")
        if session["status"] == "closed":
            _require_timestamp(session.get("closed_at"), f"project_state.sessions_index.{session_id}.closed_at")
        else:
            if session.get("closed_at") is not None:
                raise StateValidationError(f"project_state.sessions_index.{session_id}.closed_at must be null")
        if session.get("bound_context_hint") is not None:
            _require_non_empty_string(
                session.get("bound_context_hint"),
                f"project_state.sessions_index.{session_id}.bound_context_hint",
            )
        _require_list(session.get("decision_ids"), f"project_state.sessions_index.{session_id}.decision_ids")
        for decision_id in session["decision_ids"]:
            _require_non_empty_string(decision_id, f"project_state.sessions_index.{session_id}.decision_ids[]")


def _require_source_event_ids(value: Any, label: str) -> None:
    _require_list(value, label)
    if not value:
        raise StateValidationError(f"{label} must not be empty")
    seen: set[str] = set()
    for event_id in value:
        _require_non_empty_string(event_id, f"{label}[]")
        if event_id in seen:
            raise StateValidationError(f"{label} contains duplicate event ids")
        seen.add(event_id)


def _validate_decision_object_metadata(decision: dict[str, Any]) -> None:
    metadata = decision["metadata"]
    if decision["status"] not in ALL_DECISION_STATUSES:
        raise StateValidationError(f"unsupported decision status: {decision['status']}")
    for key, allowed in (
        ("priority", PRIORITIES),
        ("frontier", FRONTIERS),
        ("kind", KINDS),
        ("domain", DOMAIN_VALUES),
        ("resolvable_by", RESOLVABLE_BY),
        ("reversibility", REVERSIBILITY),
    ):
        if key in metadata:
            _require_enum(metadata[key], allowed, f"decision object {decision['id']}.metadata.{key}")
    if "agent_relevant" in metadata and metadata["agent_relevant"] is not None:
        if not isinstance(metadata["agent_relevant"], bool):
            raise StateValidationError(
                f"decision object {decision['id']}.metadata.agent_relevant must be a boolean or null"
            )
    if "notes" in metadata:
        _require_list(metadata["notes"], f"decision object {decision['id']}.metadata.notes")
    accepted_answer = metadata.get("accepted_answer")
    if accepted_answer is not None:
        _require_dict(accepted_answer, f"decision object {decision['id']}.metadata.accepted_answer")
        if accepted_answer.get("accepted_at") is not None:
            _require_timestamp(
                accepted_answer.get("accepted_at"),
                f"decision object {decision['id']}.metadata.accepted_answer.accepted_at",
            )
        if accepted_answer.get("accepted_via") is not None:
            _require_enum(
                accepted_answer.get("accepted_via"),
                ACCEPTED_VIA_VALUES,
                f"decision object {decision['id']}.metadata.accepted_answer.accepted_via",
            )
    resolved = metadata.get("resolved_by_evidence")
    if resolved is not None:
        _require_dict(resolved, f"decision object {decision['id']}.metadata.resolved_by_evidence")
        if resolved.get("resolved_at") is not None:
            _require_timestamp(
                resolved.get("resolved_at"),
                f"decision object {decision['id']}.metadata.resolved_by_evidence.resolved_at",
            )
        if resolved.get("source") is not None:
            _require_enum(
                resolved.get("source"),
                EVIDENCE_SOURCES,
                f"decision object {decision['id']}.metadata.resolved_by_evidence.source",
            )
        if resolved.get("evidence_refs") is not None:
            _require_list(
                resolved.get("evidence_refs"),
                f"decision object {decision['id']}.metadata.resolved_by_evidence.evidence_refs",
            )
    invalidated_by = metadata.get("invalidated_by")
    if decision["status"] == "invalidated":
        invalidated = _require_dict(invalidated_by, f"decision object {decision['id']}.metadata.invalidated_by")
        _require_non_empty_string(
            invalidated.get("decision_id"),
            f"decision object {decision['id']}.metadata.invalidated_by.decision_id",
        )
        _require_timestamp(
            invalidated.get("invalidated_at"),
            f"decision object {decision['id']}.metadata.invalidated_by.invalidated_at",
        )
    elif invalidated_by is not None:
        raise StateValidationError(f"non-invalidated decision object {decision['id']} must not carry invalidated_by")


def _validate_decision_status_payload(decision: dict[str, Any]) -> None:
    decision_id = decision["id"]
    status = decision["status"]
    accepted_summary = decision.get("accepted_answer", {}).get("summary")
    evidence_summary = decision.get("resolved_by_evidence", {}).get("summary")
    if status == "accepted":
        _require_non_empty_string(accepted_summary, f"decision {decision_id}.accepted_answer.summary")
        _require_non_empty_string(
            decision.get("accepted_answer", {}).get("accepted_at"),
            f"decision {decision_id}.accepted_answer.accepted_at",
        )
        _require_timestamp(
            decision.get("accepted_answer", {}).get("accepted_at"),
            f"decision {decision_id}.accepted_answer.accepted_at",
        )
        _require_non_empty_string(
            decision.get("accepted_answer", {}).get("proposal_id"),
            f"decision {decision_id}.accepted_answer.proposal_id",
        )
        _require_enum(
            decision.get("accepted_answer", {}).get("accepted_via"),
            ACCEPTED_VIA_VALUES - {"evidence"},
            f"decision {decision_id}.accepted_answer.accepted_via",
        )
        if decision["accepted_answer"]["proposal_id"] != decision["recommendation"].get("proposal_id"):
            raise StateValidationError(
                f"decision {decision_id}.accepted_answer.proposal_id must match recommendation.proposal_id"
            )
    elif status == "resolved-by-evidence":
        resolved = decision.get("resolved_by_evidence", {})
        _require_non_empty_string(resolved.get("summary"), f"decision {decision_id}.resolved_by_evidence.summary")
        _require_non_empty_string(resolved.get("source"), f"decision {decision_id}.resolved_by_evidence.source")
        _require_enum(
            resolved.get("source"),
            EVIDENCE_SOURCES,
            f"decision {decision_id}.resolved_by_evidence.source",
        )
        _require_non_empty_string(
            resolved.get("resolved_at"),
            f"decision {decision_id}.resolved_by_evidence.resolved_at",
        )
        _require_timestamp(
            resolved.get("resolved_at"),
            f"decision {decision_id}.resolved_by_evidence.resolved_at",
        )
        if decision.get("accepted_answer", {}).get("accepted_via") != "evidence":
            raise StateValidationError(
                f"decision {decision_id}.accepted_answer.accepted_via must be evidence"
            )
        if decision.get("accepted_answer", {}).get("summary") != resolved.get("summary"):
            raise StateValidationError(
                f"decision {decision_id}.accepted_answer.summary must match resolved_by_evidence.summary"
            )
    elif status in {"unresolved", "proposed", "rejected", "deferred", "blocked"}:
        if accepted_summary:
            raise StateValidationError(
                f"decision {decision_id} with status {status} must not have accepted_answer.summary"
            )
        if evidence_summary:
            raise StateValidationError(
                f"decision {decision_id} with status {status} must not have resolved_by_evidence.summary"
            )


def validate_session_state(session_state: dict[str, Any]) -> None:
    _require_keys(
        session_state,
        ("schema_version", "session", "summary", "classification", "close_summary", "working_state"),
        "session_state",
    )
    if session_state.get("schema_version") != SESSION_STATE_SCHEMA_VERSION:
        raise StateValidationError(f"session_state.schema_version must be {SESSION_STATE_SCHEMA_VERSION}")
    _require_keys(
        session_state["session"],
        ("id", "started_at", "last_seen_at", "bound_context_hint", "decision_ids", "lifecycle"),
        "session_state.session",
    )
    _require_timestamp(session_state["session"].get("started_at"), "session_state.session.started_at")
    _require_timestamp(session_state["session"].get("last_seen_at"), "session_state.session.last_seen_at")
    _require_list(session_state["session"]["decision_ids"], "session_state.session.decision_ids")
    lifecycle = _require_dict(session_state["session"]["lifecycle"], "session_state.session.lifecycle")
    _require_keys(lifecycle, ("status", "closed_at"), "session_state.session.lifecycle")
    _require_enum(lifecycle["status"], SESSION_LIFECYCLE_STATUSES, "session_state.session.lifecycle.status")
    if lifecycle["status"] == "closed":
        _require_timestamp(lifecycle.get("closed_at"), "session_state.session.lifecycle.closed_at")
    elif lifecycle.get("closed_at") is not None:
        raise StateValidationError("active session lifecycle.closed_at must be null")
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
            "search_terms",
            "source_refs",
            "updated_at",
        ),
        "session_state.classification",
    )
    unsupported_classification_keys = sorted(
        set(session_state["classification"])
        - {"domain", "abstraction_level", "assigned_tags", "search_terms", "source_refs", "updated_at"}
    )
    if unsupported_classification_keys:
        raise StateValidationError(
            "session_state.classification contains unsupported fields: "
            + ", ".join(unsupported_classification_keys)
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
        ("current_question_id", "current_question", "active_proposal", "last_seen_project_head"),
        "session_state.working_state",
    )
    for key in ("assigned_tags", "search_terms", "source_refs"):
        _require_list(session_state["classification"][key], f"session_state.classification.{key}")
    _require_optional_timestamp(
        session_state["classification"].get("updated_at"),
        "session_state.classification.updated_at",
    )
    _require_optional_timestamp(
        session_state["close_summary"].get("generated_at"),
        "session_state.close_summary.generated_at",
    )
    for key in (
        "accepted_decisions",
        "deferred_decisions",
        "unresolved_blockers",
        "unresolved_risks",
        "candidate_workstreams",
        "candidate_action_slices",
        "evidence_refs",
    ):
        _require_list(session_state["close_summary"][key], f"session_state.close_summary.{key}")


def validate_taxonomy_state(taxonomy_state: dict[str, Any]) -> None:
    _require_keys(taxonomy_state, ("schema_version", "state", "required_axes", "nodes"), "taxonomy_state")
    _require_keys(taxonomy_state["state"], ("updated_at", "last_event_id"), "taxonomy_state.state")
    _require_timestamp(taxonomy_state["state"].get("updated_at"), "taxonomy_state.state.updated_at")
    node_ids = taxonomy_by_id(taxonomy_state)
    if len(node_ids) != len(taxonomy_state["nodes"]):
        raise StateValidationError("taxonomy_state.nodes contains duplicate ids")
    for node in taxonomy_state["nodes"]:
        _require_keys(
            node,
            ("id", "axis", "label", "aliases", "parent_id", "replaced_by", "status", "created_at", "updated_at"),
            f"taxonomy node {node.get('id', '?')}",
        )
        _require_enum(node["axis"], TAXONOMY_AXES, f"taxonomy node {node['id']}.axis")
        _require_enum(node["status"], TAXONOMY_STATUSES, f"taxonomy node {node['id']}.status")
        _require_list(node["aliases"], f"taxonomy node {node['id']}.aliases")
        _require_list(node["replaced_by"], f"taxonomy node {node['id']}.replaced_by")
        _require_timestamp(node.get("created_at"), f"taxonomy node {node['id']}.created_at")
        _require_timestamp(node.get("updated_at"), f"taxonomy node {node['id']}.updated_at")


def validate_projection_bundle(bundle: dict[str, Any]) -> None:
    _require_keys(bundle, ("project_state", "taxonomy_state", "sessions"), "projection_bundle")
    validate_project_state(bundle["project_state"])
    validate_taxonomy_state(bundle["taxonomy_state"])
    if not isinstance(bundle["sessions"], dict):
        raise StateValidationError("projection_bundle.sessions must be a dictionary")
    decisions_by_id = _decision_index(bundle["project_state"])
    visible_ids = _visible_decision_ids(decisions_by_id)
    taxonomy_ids = set(taxonomy_by_id(bundle["taxonomy_state"]))
    for session_id, session in bundle["sessions"].items():
        validate_session_state(session)
    if bundle["project_state"]["sessions_index"] != _expected_sessions_index(bundle["sessions"]):
        raise StateValidationError("project_state.sessions_index does not match sessions")
    _validate_resolved_conflict_suppression(
        bundle["project_state"],
        bundle["sessions"],
        bundle["taxonomy_state"],
    )

    active_proposal_targets: dict[str, list[str]] = {}
    for session_id, session in bundle["sessions"].items():
        _validate_session_integrity(session_id, session, decisions_by_id, visible_ids, taxonomy_ids)
        proposal = session["working_state"]["active_proposal"]
        if proposal.get("is_active") and proposal.get("target_id"):
            active_proposal_targets.setdefault(proposal["target_id"], []).append(session_id)
    _validate_decision_references(decisions_by_id, active_proposal_targets)
    _validate_visible_decision_bindings(
        bundle["sessions"],
        visible_ids,
        # Semantic conflict suppression is session-scoped; rejected-only audit decisions may become unbound.
        allowed_unbound_decision_ids=suppressed_decision_ids(bundle["project_state"]),
    )


def _decision_index(project_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: item
        for item in project_state["objects"]
        if item.get("type") == "decision"
    }


def _expected_sessions_index(sessions: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for session_id in sorted(sessions):
        session = sessions[session_id]["session"]
        lifecycle = session["lifecycle"]
        index[session_id] = {
            "id": session["id"],
            "status": lifecycle["status"],
            "started_at": session["started_at"],
            "last_seen_at": session["last_seen_at"],
            "closed_at": lifecycle.get("closed_at"),
            "bound_context_hint": session.get("bound_context_hint"),
            "decision_ids": list(session.get("decision_ids", [])),
        }
    return index


def _visible_decision_ids(decisions_by_id: dict[str, dict[str, Any]]) -> set[str]:
    return {
        decision_id
        for decision_id, decision in decisions_by_id.items()
        if decision.get("status") != "invalidated"
    }


def _validate_decision_references(
    decisions_by_id: dict[str, dict[str, Any]], active_proposal_targets: dict[str, list[str]]
) -> None:
    for decision_id, decision in decisions_by_id.items():
        metadata = decision.get("metadata", {})
        invalidated_by = metadata.get("invalidated_by")
        if decision["status"] == "invalidated":
            invalidated_by = _require_dict(invalidated_by, f"decision {decision_id}.invalidated_by")
            invalidating_id = invalidated_by.get("decision_id")
            _require_timestamp(
                invalidated_by.get("invalidated_at"),
                f"decision {decision_id}.invalidated_by.invalidated_at",
            )
            if invalidating_id not in decisions_by_id:
                raise StateValidationError(f"decision {decision_id} has invalid invalidated_by reference")
            if not _has_final_invalidating_chain(invalidating_id, decisions_by_id, seen={decision_id}):
                raise StateValidationError(
                    f"decision {decision_id} is invalidated by non-final decision {invalidating_id}"
                )
        elif invalidated_by is not None:
            raise StateValidationError(f"non-invalidated decision {decision_id} must not carry invalidated_by")

        if decision["status"] == "proposed":
            owners = active_proposal_targets.get(decision_id, [])
            if len(owners) != 1:
                raise StateValidationError(
                    f"decision {decision_id} is proposed but has {len(owners)} active proposal targets"
                )


def _validate_visible_decision_bindings(
    sessions: dict[str, dict[str, Any]],
    visible_decision_ids: set[str],
    *,
    allowed_unbound_decision_ids: set[str] | None = None,
) -> None:
    allowed_unbound_decision_ids = allowed_unbound_decision_ids or set()
    bound_decision_ids = {
        decision_id
        for session in sessions.values()
        for decision_id in session["session"]["decision_ids"]
    }
    unbound = visible_decision_ids - bound_decision_ids - allowed_unbound_decision_ids
    if unbound:
        raise StateValidationError(
            f"visible decisions are not bound to any session: {sorted(unbound)}"
        )


def _validate_session_integrity(
    session_key: str,
    session: dict[str, Any],
    decisions_by_id: dict[str, dict[str, Any]],
    visible_ids: set[str],
    taxonomy_ids: set[str],
) -> None:
    session_id = session["session"]["id"]
    if session_id != session_key:
        raise StateValidationError(f"session map key {session_key} does not match session id {session_id}")

    decision_ids = session["session"]["decision_ids"]
    if len(decision_ids) != len(set(decision_ids)):
        raise StateValidationError(f"session {session_id} contains duplicate decision_ids")
    for decision_id in decision_ids:
        if decision_id not in decisions_by_id:
            raise StateValidationError(f"session {session_id} references unknown decision {decision_id}")
        if decision_id not in visible_ids:
            raise StateValidationError(f"session {session_id} references non-visible decision {decision_id}")

    active_decision_id = session["summary"].get("active_decision_id")
    if active_decision_id and active_decision_id not in set(decision_ids):
        raise StateValidationError(f"session {session_id} active_decision_id is not bound to the session")
    if active_decision_id and active_decision_id not in visible_ids:
        raise StateValidationError(f"session {session_id} active_decision_id references non-visible decision")

    _validate_classification_refs(session_id, session, taxonomy_ids)
    _validate_active_proposal(session_id, session, decisions_by_id, visible_ids, set(decision_ids))
    _validate_close_summary(session_id, session, decisions_by_id, visible_ids, set(decision_ids))


def _validate_classification_refs(
    session_id: str, session: dict[str, Any], taxonomy_ids: set[str]
) -> None:
    classification = session["classification"]
    domain = classification.get("domain")
    if domain is not None:
        _require_enum(domain, DOMAIN_VALUES, f"session {session_id} classification.domain")
    for tag_ref in classification.get("assigned_tags", []):
        if tag_ref not in taxonomy_ids:
            raise StateValidationError(
                f"session {session_id} assigned_tags references unknown taxonomy node {tag_ref}"
            )


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
            "based_on_project_head",
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
    if lifecycle_status == "closed":
        _require_timestamp(
            session["close_summary"].get("generated_at"),
            f"session {session_id}.close_summary.generated_at",
        )

    proposal_id = active.get("proposal_id")
    if active.get("is_active"):
        if active.get("inactive_reason") is not None:
            raise StateValidationError(
                f"session {session_id} active proposal must not have inactive_reason"
            )
    elif proposal_id and (
        not isinstance(active.get("inactive_reason"), str)
        or not active.get("inactive_reason", "").strip()
    ):
        raise StateValidationError(
            f"session {session_id} inactive proposal must have inactive_reason"
        )
    if not proposal_id:
        _validate_question_state(session_id, session)
        return
    _require_timestamp(
        active.get("activated_at"),
        f"session {session_id} active_proposal.activated_at",
    )
    if active.get("based_on_project_head") is not None:
        _require_non_empty_string(
            active.get("based_on_project_head"),
            f"session {session_id} active_proposal.based_on_project_head",
        )

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
        raise StateValidationError(f"session {session_id} active proposal references non-visible decision {target_id}")
    if target_id not in session_decision_ids:
        raise StateValidationError(f"session {session_id} active proposal target is not bound to the session")

    if active.get("is_active"):
        decision = decisions_by_id[target_id]
        if decision["status"] != "proposed":
            raise StateValidationError(
                f"session {session_id} active proposal target {target_id} is not proposed"
            )
        if session["summary"].get("active_decision_id") != target_id:
            raise StateValidationError(f"session {session_id} active proposal does not match active_decision_id")
        if decision.get("metadata", {}).get("last_proposal_id") != proposal_id:
            raise StateValidationError(f"session {session_id} active proposal is not the decision recommendation")
    _validate_question_state(session_id, session)


def _validate_question_state(session_id: str, session: dict[str, Any]) -> None:
    working_state = session["working_state"]
    active = working_state["active_proposal"]
    current_question_id = working_state.get("current_question_id")
    current_question = working_state.get("current_question")
    preview = session["summary"].get("current_question_preview")
    active_decision_id = session["summary"].get("active_decision_id")
    has_question = bool(current_question_id or current_question or preview or active_decision_id)

    if has_question:
        if not active.get("is_active"):
            raise StateValidationError(
                f"session {session_id} has current question state without active proposal"
            )
        if current_question_id != active.get("question_id"):
            raise StateValidationError(
                f"session {session_id} current_question_id does not match active proposal"
            )
        if current_question != active.get("question"):
            raise StateValidationError(
                f"session {session_id} current_question does not match active proposal"
            )
        if preview != active.get("question"):
            raise StateValidationError(
                f"session {session_id} current_question_preview does not match active proposal"
            )
        if active_decision_id != active.get("target_id"):
            raise StateValidationError(
                f"session {session_id} active_decision_id does not match active proposal"
            )

    if active.get("is_active") and not (
        current_question_id and current_question and preview and active_decision_id
    ):
        raise StateValidationError(
            f"session {session_id} active proposal requires current question state"
        )


def _validate_close_summary(
    session_id: str,
    session: dict[str, Any],
    decisions_by_id: dict[str, dict[str, Any]],
    visible_ids: set[str],
    session_decision_ids: set[str],
) -> None:
    close_summary = session["close_summary"]
    expected_readiness = _close_summary_readiness(close_summary)
    if close_summary.get("readiness") != expected_readiness:
        raise StateValidationError(
            f"session {session_id} close_summary.readiness must be {expected_readiness}"
        )
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


def _close_summary_readiness(close_summary: dict[str, Any]) -> str:
    if close_summary.get("unresolved_blockers"):
        return "blocked"
    if close_summary.get("unresolved_risks"):
        return "conditional"
    return "ready"


def validate_event_log(events: list[dict[str, Any]]) -> None:
    validate_event_log_structure(events)
    if not events:
        return
    first = events[0]
    if first.get("event_type") != "project_initialized":
        raise StateValidationError("event log must start with project_initialized")
    if first.get("session_id") != SYSTEM_SESSION_ID:
        raise StateValidationError("project_initialized event must use SYSTEM session_id")

    created_session_ids: set[str] = {SYSTEM_SESSION_ID}
    session_status: dict[str, str] = {SYSTEM_SESSION_ID: "active"}
    has_close_summary: dict[str, bool] = {}
    object_ids: set[str] = set()
    object_statuses: dict[str, str] = {}
    active_link_ids: set[str] = set()
    pending_questions_by_session: dict[str, dict[str, str]] = defaultdict(dict)
    pending_close_summary_session_id: str | None = None
    project_initialized_count = 0
    for event in events:
        _validate_event_log_session_scope(event, created_session_ids)
        event_type = event["event_type"]
        payload = event["payload"]
        if pending_close_summary_session_id is not None:
            if (
                event_type != "session_closed"
                or event["session_id"] != pending_close_summary_session_id
            ):
                raise StateValidationError(
                    "close_summary_generated must be followed by matching session_closed"
                )
            pending_close_summary_session_id = None
        if event_type == "project_initialized":
            if event["session_id"] != SYSTEM_SESSION_ID:
                raise StateValidationError("project_initialized event must use SYSTEM session_id")
            project_initialized_count += 1
            if project_initialized_count > 1:
                raise StateValidationError("event log must contain exactly one project_initialized event")
            project = payload["project"]
            for key in ("name", "objective", "current_milestone", "stop_rule"):
                _require_non_empty_string(project.get(key), f"project_initialized.payload.project.{key}")
            object_ids.add("O-project-objective")
            object_statuses["O-project-objective"] = "active"
        elif event_type == "session_created":
            created_session_id = payload["session"]["id"]
            if event["session_id"] != created_session_id:
                raise StateValidationError("session_created event.session_id must match payload.session.id")
            if created_session_id in created_session_ids:
                raise StateValidationError(f"duplicate session_created id: {created_session_id}")
            created_session_ids.add(created_session_id)
            session_status[created_session_id] = "active"
            has_close_summary[created_session_id] = False
        else:
            if (
                event_type in SESSION_MUTATION_EVENT_TYPES
                and session_status.get(event["session_id"]) == "closed"
            ):
                raise StateValidationError(
                    f"{event_type} mutates closed session {event['session_id']}"
                )
            if event_type == "session_closed":
                if session_status.get(event["session_id"]) == "closed":
                    raise StateValidationError(f"session {event['session_id']} is already closed")
                if not has_close_summary.get(event["session_id"]):
                    raise StateValidationError(
                        f"session_closed requires prior close_summary_generated for {event['session_id']}"
                    )
        if event_type == "object_recorded":
            object_id = payload["object"]["id"]
            if object_id in object_ids:
                raise StateValidationError(f"duplicate object_recorded id: {object_id}")
            object_ids.add(object_id)
            object_statuses[object_id] = payload["object"]["status"]
        elif event_type == "object_updated":
            object_id = payload["object_id"]
            if object_id not in object_ids:
                raise StateValidationError(f"object_updated references unknown object {object_id}")
        elif event_type == "object_status_changed":
            object_id = payload["object_id"]
            if object_id not in object_ids:
                raise StateValidationError(f"object_status_changed references unknown object {object_id}")
            actual_status = object_statuses[object_id]
            if actual_status != payload["from_status"]:
                raise StateValidationError(
                    f"object_status_changed from_status mismatch for {object_id}: "
                    f"expected {actual_status}, got {payload['from_status']}"
                )
            object_statuses[object_id] = payload["to_status"]
        elif event_type == "object_linked":
            link = payload["link"]
            link_id = link["id"]
            if link_id in active_link_ids:
                raise StateValidationError(f"duplicate active link id: {link_id}")
            source_id = link["source_object_id"]
            target_id = link["target_object_id"]
            if source_id not in object_ids:
                raise StateValidationError(f"object_linked link {link_id} source_object_id references unknown object")
            if target_id not in object_ids:
                raise StateValidationError(f"object_linked link {link_id} target_object_id references unknown object")
            active_link_ids.add(link_id)
        elif event_type == "object_unlinked":
            link_id = payload["link_id"]
            if link_id not in active_link_ids:
                raise StateValidationError(f"object_unlinked references unknown or inactive link {link_id}")
            active_link_ids.remove(link_id)
        elif event_type == "session_question_asked":
            target_object_id = payload["target_object_id"]
            if target_object_id not in object_ids:
                raise StateValidationError(
                    f"session_question_asked references unknown object {target_object_id}"
                )
            session_questions = pending_questions_by_session[event["session_id"]]
            question_id = payload["question_id"]
            if question_id in session_questions:
                raise StateValidationError(f"duplicate pending session question: {question_id}")
            session_questions[question_id] = target_object_id
        elif event_type == "session_answer_recorded":
            target_object_id = payload["target_object_id"]
            if target_object_id not in object_ids:
                raise StateValidationError(
                    f"session_answer_recorded references unknown object {target_object_id}"
                )
            session_questions = pending_questions_by_session[event["session_id"]]
            question_id = payload["question_id"]
            expected_target = session_questions.get(question_id)
            if expected_target is None:
                raise StateValidationError(f"session_answer_recorded references unknown pending question {question_id}")
            if expected_target != target_object_id:
                raise StateValidationError("session_answer_recorded target_object_id does not match pending question")
            del session_questions[question_id]
        if event_type == "close_summary_generated":
            has_close_summary[event["session_id"]] = True
            pending_close_summary_session_id = event["session_id"]
        if event_type == "plan_generated":
            for referenced_session_id in payload["session_ids"]:
                if referenced_session_id not in created_session_ids:
                    raise StateValidationError(
                        f"plan_generated references unknown session: {referenced_session_id}"
                    )
                if session_status.get(referenced_session_id) != "closed":
                    raise StateValidationError(
                        f"plan_generated references non-closed session: {referenced_session_id}"
                    )
        if event_type == "session_closed":
            session_status[event["session_id"]] = "closed"
    if pending_close_summary_session_id is not None:
        raise StateValidationError("close_summary_generated must be followed by matching session_closed")


def validate_event_log_structure(events: list[dict[str, Any]]) -> None:
    if not events:
        return
    first = events[0]
    if first.get("event_type") != "project_initialized":
        raise StateValidationError("event log must start with project_initialized")
    if first.get("session_id") != SYSTEM_SESSION_ID:
        raise StateValidationError("project_initialized event must use SYSTEM session_id")

    _validate_event_transactions(events)
    event_ids: set[str] = set()
    project_initialized_count = 0
    for event in events:
        validate_event(event)
        if event["event_type"] not in EVENT_TYPES:
            raise StateValidationError(f"unsupported event type in log: {event['event_type']}")
        if event["event_id"] in event_ids:
            raise StateValidationError(f"duplicate event id: {event['event_id']}")
        event_ids.add(event["event_id"])
        if event["event_type"] == "project_initialized":
            if event["session_id"] != SYSTEM_SESSION_ID:
                raise StateValidationError("project_initialized event must use SYSTEM session_id")
            project_initialized_count += 1
            if project_initialized_count > 1:
                raise StateValidationError("event log must contain exactly one project_initialized event")


def _validate_event_transactions(events: list[dict[str, Any]]) -> None:
    by_tx_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_tx_positions: set[tuple[str, int]] = set()
    for event in events:
        validate_event(event)
        tx_id = event["tx_id"]
        tx_index = event["tx_index"]
        tx_position = (tx_id, tx_index)
        if tx_position in seen_tx_positions:
            raise StateValidationError(f"duplicate tx_index {tx_index} in transaction {tx_id}")
        seen_tx_positions.add(tx_position)
        by_tx_id[tx_id].append(event)

    for tx_id, tx_events in by_tx_id.items():
        tx_sizes = {event["tx_size"] for event in tx_events}
        if len(tx_sizes) != 1:
            raise StateValidationError(f"transaction {tx_id} has inconsistent tx_size values")
        tx_size = tx_sizes.pop()
        if tx_size != len(tx_events):
            raise StateValidationError(f"transaction {tx_id} tx_size does not match event count")
        tx_indexes = sorted(event["tx_index"] for event in tx_events)
        if tx_indexes != list(range(1, tx_size + 1)):
            raise StateValidationError(f"transaction {tx_id} tx_index values must be contiguous")
        session_ids = {event["session_id"] for event in tx_events}
        if len(session_ids) != 1:
            raise StateValidationError(f"transaction {tx_id} contains multiple session_ids")


def _validate_graph(session_graph: dict[str, Any]) -> None:
    graph = _require_dict(session_graph, "project_state.graph")
    _require_keys(
        graph,
        ("nodes", "edges", "inferred_candidates", "resolved_conflicts"),
        "project_state.graph",
    )
    for key in ("nodes", "edges", "inferred_candidates", "resolved_conflicts"):
        _require_list(graph[key], f"project_state.graph.{key}")
    node_ids: set[str] = set()
    for node in graph["nodes"]:
        node_payload = _require_dict(node, "project_state.graph.nodes[]")
        _require_keys(
            node_payload,
            ("session_id", "status", "decision_ids", "close_summary_preview"),
            "project_state.graph.nodes[]",
        )
        _require_non_empty_string(node_payload.get("session_id"), "project_state.graph.nodes[].session_id")
        if node_payload["session_id"] in node_ids:
            raise StateValidationError(f"duplicate session graph node: {node_payload['session_id']}")
        node_ids.add(node_payload["session_id"])
        _require_list(node_payload["decision_ids"], "project_state.graph.nodes[].decision_ids")
        _require_dict(
            node_payload["close_summary_preview"],
            "project_state.graph.nodes[].close_summary_preview",
        )
    for edge in graph["edges"]:
        edge_payload = _require_dict(edge, "project_state.graph.edges[]")
        _require_keys(
            edge_payload,
            (
                "parent_session_id",
                "child_session_id",
                "relationship",
                "reason",
                "linked_at",
                "evidence_refs",
                "event_id",
            ),
            "project_state.graph.edges[]",
        )
        _require_non_empty_string(edge_payload["parent_session_id"], "project_state.graph.edges[].parent_session_id")
        _require_non_empty_string(edge_payload["child_session_id"], "project_state.graph.edges[].child_session_id")
        _require_enum(edge_payload["relationship"], SESSION_RELATIONSHIPS, "project_state.graph.edges[].relationship")
        _require_non_empty_string(edge_payload["reason"], "project_state.graph.edges[].reason")
        _require_timestamp(edge_payload["linked_at"], "project_state.graph.edges[].linked_at")
        _require_list(edge_payload["evidence_refs"], "project_state.graph.edges[].evidence_refs")
        _require_non_empty_string(edge_payload["event_id"], "project_state.graph.edges[].event_id")
    for resolved in graph["resolved_conflicts"]:
        resolved_payload = _require_dict(resolved, "project_state.graph.resolved_conflicts[]")
        _require_keys(
            resolved_payload,
            (
                "conflict_id",
                "winning_session_id",
                "rejected_session_ids",
                "scope",
                "suppressed_context",
                "reason",
                "resolved_at",
                "event_id",
            ),
            "project_state.graph.resolved_conflicts[]",
        )
        _require_non_empty_string(
            resolved_payload["conflict_id"],
            "project_state.graph.resolved_conflicts[].conflict_id",
        )
        _require_non_empty_string(
            resolved_payload["winning_session_id"],
            "project_state.graph.resolved_conflicts[].winning_session_id",
        )
        _require_list(
            resolved_payload["rejected_session_ids"],
            "project_state.graph.resolved_conflicts[].rejected_session_ids",
        )
        _require_dict(resolved_payload["scope"], "project_state.graph.resolved_conflicts[].scope")
        _validate_suppressed_context(
            resolved_payload["suppressed_context"],
            "project_state.graph.resolved_conflicts[].suppressed_context",
        )
        _require_non_empty_string(resolved_payload["reason"], "project_state.graph.resolved_conflicts[].reason")
        _require_timestamp(resolved_payload["resolved_at"], "project_state.graph.resolved_conflicts[].resolved_at")
        _require_non_empty_string(resolved_payload["event_id"], "project_state.graph.resolved_conflicts[].event_id")


def _validate_suppressed_context(context: Any, label: str) -> None:
    context_payload = _require_dict(context, label)
    _require_keys(
        context_payload,
        ("session_ids", "decision_ids", "action_slice_names", "workstream_names", "hidden_strings"),
        label,
    )
    for key in ("session_ids", "decision_ids", "action_slice_names", "workstream_names", "hidden_strings"):
        _require_list(context_payload[key], f"{label}.{key}")


def _validate_resolved_conflict_suppression(
    project_state: dict[str, Any],
    sessions: dict[str, dict[str, Any]],
    taxonomy_state: dict[str, Any],
) -> None:
    graph = project_state["graph"]
    for resolved in graph.get("resolved_conflicts", []):
        for rejected_session_id in resolved.get("rejected_session_ids", []):
            session = sessions.get(rejected_session_id)
            if not session:
                continue
            if has_remaining_suppressed_scope(session, resolved) or has_suppressed_context_remainders(
                session,
                resolved.get("suppressed_context", {}),
                taxonomy_state,
            ):
                raise StateValidationError(
                    f"resolved conflict {resolved['conflict_id']} leaves rejected scope in "
                    f"session {rejected_session_id} projection"
                )


def _validate_event_log_session_scope(event: dict[str, Any], created_session_ids: set[str]) -> None:
    event_type = event["event_type"]
    session_id = event["session_id"]
    if event_type in SYSTEM_EVENT_TYPES:
        if session_id != SYSTEM_SESSION_ID:
            raise StateValidationError(f"{event_type} must use SYSTEM session_id")
        return
    if event_type in SESSION_SCOPED_EVENT_TYPES:
        if session_id == SYSTEM_SESSION_ID:
            raise StateValidationError(f"{event_type} must not use SYSTEM session_id")
        if event_type != "session_created" and session_id not in created_session_ids:
            raise StateValidationError(f"event references unknown session: {session_id}")
        return
    raise StateValidationError(f"event type has no session scope: {event_type}")


def _has_final_invalidating_chain(
    decision_id: str,
    decisions_by_id: dict[str, dict[str, Any]],
    *,
    seen: set[str],
) -> bool:
    if decision_id in seen:
        return False
    seen.add(decision_id)
    decision = decisions_by_id.get(decision_id)
    if decision is None:
        return False
    if decision["status"] in FINAL_INVALIDATING_STATUSES:
        return True
    if decision["status"] != "invalidated":
        return False
    invalidated_by = decision.get("metadata", {}).get("invalidated_by")
    if not isinstance(invalidated_by, dict):
        return False
    invalidating_id = invalidated_by.get("decision_id")
    if not invalidating_id:
        return False
    return _has_final_invalidating_chain(invalidating_id, decisions_by_id, seen=seen)


def _require_non_empty_string(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise StateValidationError(f"{label} must be a non-empty string")


def _require_optional_non_empty_string(value: Any, label: str) -> None:
    if value is None:
        return
    _require_non_empty_string(value, label)


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StateValidationError(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> None:
    if not isinstance(value, list):
        raise StateValidationError(f"{label} must be a list")


def _require_enum(value: Any, allowed: set[str], label: str) -> None:
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise StateValidationError(f"{label} must be one of: {choices}")


def _recomputed_counts(objects: list[dict[str, Any]], links: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, Any] = {
        "object_total": len(objects),
        "link_total": len(links),
        "by_type": {},
        "by_status": {},
        "by_relation": {},
    }
    for item in objects:
        counts["by_type"][item["type"]] = counts["by_type"].get(item["type"], 0) + 1
        counts["by_status"][item["status"]] = counts["by_status"].get(item["status"], 0) + 1
    for link in links:
        counts["by_relation"][link["relation"]] = counts["by_relation"].get(link["relation"], 0) + 1
    return counts
