from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from decide_me.constants import ACCEPTED_VIA_VALUES, DOMAIN_VALUES, EVIDENCE_SOURCES
from decide_me.events import EVENT_TYPES, SESSION_RELATIONSHIPS, validate_event
from decide_me.projections import PROJECTION_SCHEMA_VERSION
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
SYSTEM_EVENT_TYPES = {
    "project_initialized",
    "plan_generated",
}
SESSION_SCOPED_EVENT_TYPES = {
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
    "taxonomy_extended",
    "compatibility_backfilled",
    "transaction_rejected",
    "session_linked",
    "semantic_conflict_resolved",
}
SESSION_MUTATION_EVENT_TYPES = {
    "session_resumed",
    "decision_discovered",
    "decision_enriched",
    "question_asked",
    "proposal_issued",
    "proposal_accepted",
    "proposal_rejected",
    "decision_deferred",
    "decision_resolved_by_evidence",
    "classification_updated",
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
    _require_keys(
        project_state,
        (
            "schema_version",
            "project",
            "state",
            "protocol",
            "counts",
            "default_bundles",
            "session_graph",
            "decisions",
        ),
        "project_state",
    )
    if project_state.get("schema_version") != PROJECTION_SCHEMA_VERSION:
        raise StateValidationError(f"project_state.schema_version must be {PROJECTION_SCHEMA_VERSION}")
    _require_keys(
        project_state["project"],
        ("name", "objective", "current_milestone", "stop_rule"),
        "project_state.project",
    )
    for key in ("name", "objective", "current_milestone", "stop_rule"):
        _require_non_empty_string(project_state["project"].get(key), f"project_state.project.{key}")
    _require_keys(
        project_state["state"],
        ("project_head", "event_count", "updated_at", "last_event_id"),
        "project_state.state",
    )
    _require_non_empty_string(project_state["state"].get("project_head"), "project_state.state.project_head")
    if not isinstance(project_state["state"].get("event_count"), int) or project_state["state"]["event_count"] < 1:
        raise StateValidationError("project_state.state.event_count must be a positive integer")
    _require_timestamp(project_state["state"].get("updated_at"), "project_state.state.updated_at")
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
        _require_enum(decision["priority"], PRIORITIES, f"decision {decision['id']}.priority")
        _require_enum(decision["frontier"], FRONTIERS, f"decision {decision['id']}.frontier")
        _require_enum(decision["kind"], KINDS, f"decision {decision['id']}.kind")
        _require_enum(decision["domain"], DOMAIN_VALUES, f"decision {decision['id']}.domain")
        _require_enum(
            decision["resolvable_by"], RESOLVABLE_BY, f"decision {decision['id']}.resolvable_by"
        )
        _require_enum(
            decision["reversibility"], REVERSIBILITY, f"decision {decision['id']}.reversibility"
        )
        _require_list(decision["depends_on"], f"decision {decision['id']}.depends_on")
        _require_list(decision["blocked_by"], f"decision {decision['id']}.blocked_by")
        _require_list(decision["options"], f"decision {decision['id']}.options")
        _require_list(decision["evidence_refs"], f"decision {decision['id']}.evidence_refs")
        _require_list(decision["revisit_triggers"], f"decision {decision['id']}.revisit_triggers")
        _require_list(decision["notes"], f"decision {decision['id']}.notes")
        if "agent_relevant" in decision and decision["agent_relevant"] is not None:
            if not isinstance(decision["agent_relevant"], bool):
                raise StateValidationError(
                    f"decision {decision['id']}.agent_relevant must be a boolean or null"
                )
        _require_dict(decision["recommendation"], f"decision {decision['id']}.recommendation")
        _require_dict(decision["accepted_answer"], f"decision {decision['id']}.accepted_answer")
        resolved_by_evidence = _require_dict(
            decision["resolved_by_evidence"], f"decision {decision['id']}.resolved_by_evidence"
        )
        _require_list(
            resolved_by_evidence.get("evidence_refs"),
            f"decision {decision['id']}.resolved_by_evidence.evidence_refs",
        )
        _validate_decision_status_payload(decision)
        if decision["id"] in decision_ids:
            raise StateValidationError(f"duplicate decision id: {decision['id']}")
        decision_ids.add(decision["id"])
    expected_counts = _recomputed_counts(project_state["decisions"])
    if project_state["counts"] != expected_counts:
        raise StateValidationError("project_state.counts does not match decision state")
    _validate_session_graph(project_state["session_graph"])


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
    if session_state.get("schema_version") != PROJECTION_SCHEMA_VERSION:
        raise StateValidationError(f"session_state.schema_version must be {PROJECTION_SCHEMA_VERSION}")
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
        ("current_question_id", "current_question", "active_proposal", "last_seen_project_head"),
        "session_state.working_state",
    )
    for key in ("assigned_tags", "compatibility_tags", "search_terms", "source_refs"):
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
    return {decision["id"]: decision for decision in project_state["decisions"]}


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
        for key in ("depends_on", "blocked_by"):
            for referenced_id in decision.get(key, []):
                if referenced_id not in decisions_by_id:
                    raise StateValidationError(
                        f"decision {decision_id}.{key} references unknown decision {referenced_id}"
                    )

        invalidated_by = decision.get("invalidated_by")
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

        accepted_proposal_id = decision.get("accepted_answer", {}).get("proposal_id")
        recommended_proposal_id = decision.get("recommendation", {}).get("proposal_id")
        if accepted_proposal_id and accepted_proposal_id != recommended_proposal_id:
            raise StateValidationError(
                f"decision {decision_id} accepted_answer.proposal_id does not match recommendation.proposal_id"
            )
        if decision["status"] == "proposed":
            _require_non_empty_string(
                decision.get("recommendation", {}).get("proposal_id"),
                f"decision {decision_id}.recommendation.proposal_id",
            )
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
        if decision.get("recommendation", {}).get("proposal_id") != proposal_id:
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
    session_decision_ids: dict[str, set[str]] = defaultdict(set)
    decision_status: dict[str, str] = {}
    has_close_summary: dict[str, bool] = {}
    discovered_decision_ids: set[str] = set()
    issued_proposals: dict[str, dict[str, str]] = {}
    active_proposal_by_session: dict[str, str | None] = {}
    disabled_proposals: set[str] = set()
    accepted_proposals: set[str] = set()
    rejected_proposals: set[str] = set()
    pending_rejected_proposal_id: str | None = None
    pending_question: dict[str, str] | None = None
    pending_close_summary_session_id: str | None = None
    project_initialized_count = 0
    linked_edges: list[tuple[str, str, str]] = []
    seen_link_keys: set[tuple[str, str, str]] = set()
    resolved_conflict_ids: set[str] = set()
    for event in events:
        _validate_event_log_session_scope(event, created_session_ids)
        if pending_close_summary_session_id is not None:
            if (
                event["event_type"] != "session_closed"
                or event["session_id"] != pending_close_summary_session_id
            ):
                raise StateValidationError(
                    "close_summary_generated must be followed by matching session_closed"
                )
            pending_close_summary_session_id = None
        if event["event_type"] == "project_initialized":
            if event["session_id"] != SYSTEM_SESSION_ID:
                raise StateValidationError("project_initialized event must use SYSTEM session_id")
            project_initialized_count += 1
            if project_initialized_count > 1:
                raise StateValidationError("event log must contain exactly one project_initialized event")
            project = event["payload"]["project"]
            for key in ("name", "objective", "current_milestone", "stop_rule"):
                _require_non_empty_string(project.get(key), f"project_initialized.payload.project.{key}")
        elif event["event_type"] == "session_created":
            created_session_id = event["payload"]["session"]["id"]
            if event["session_id"] != created_session_id:
                raise StateValidationError("session_created event.session_id must match payload.session.id")
            if created_session_id in created_session_ids:
                raise StateValidationError(f"duplicate session_created id: {created_session_id}")
            created_session_ids.add(created_session_id)
            session_status[created_session_id] = "active"
            session_decision_ids[created_session_id] = set()
            has_close_summary[created_session_id] = False
            active_proposal_by_session[created_session_id] = None
        else:
            if (
                event["event_type"] in SESSION_MUTATION_EVENT_TYPES
                and session_status.get(event["session_id"]) == "closed"
            ):
                raise StateValidationError(
                    f"{event['event_type']} mutates closed session {event['session_id']}"
                )
            if event["event_type"] == "session_closed":
                if session_status.get(event["session_id"]) == "closed":
                    raise StateValidationError(f"session {event['session_id']} is already closed")
                if not has_close_summary.get(event["session_id"]):
                    raise StateValidationError(
                        f"session_closed requires prior close_summary_generated for {event['session_id']}"
                    )
        if event["event_type"] == "decision_discovered":
            decision_id = event["payload"]["decision"]["id"]
            if decision_id in discovered_decision_ids:
                raise StateValidationError(f"duplicate decision_discovered id: {decision_id}")
            discovered_decision_ids.add(decision_id)
            session_decision_ids[event["session_id"]].add(decision_id)
            decision_status[decision_id] = event["payload"]["decision"].get("status") or "unresolved"
        else:
            for decision_id in _decision_refs_in_event(event):
                if decision_id not in discovered_decision_ids:
                    raise StateValidationError(
                        f"{event['event_type']} references undiscovered decision {decision_id}"
                    )
        if event["event_type"] == "session_linked":
            _validate_session_linked_event(
                event,
                created_session_ids,
                linked_edges,
                seen_link_keys,
            )
        elif event["event_type"] == "semantic_conflict_resolved":
            _validate_semantic_conflict_resolved_event(
                event,
                created_session_ids,
                resolved_conflict_ids,
            )
        pending_rejected_proposal_id = _expire_pending_rejected_proposal(
            event,
            pending_rejected_proposal_id,
            issued_proposals,
            active_proposal_by_session,
            disabled_proposals,
        )
        _validate_event_log_session_decision_binding(event, session_decision_ids)
        pending_question = _validate_event_log_question_pairing(event, pending_question)
        _validate_event_log_proposal_lifecycle(
            event,
            issued_proposals,
            active_proposal_by_session,
            disabled_proposals,
            accepted_proposals,
            rejected_proposals,
        )
        _deactivate_active_proposal_for_decision_event(
            event,
            issued_proposals,
            active_proposal_by_session,
            disabled_proposals,
        )
        accepts_immediate_rejected_proposal = (
            event["event_type"] == "proposal_accepted"
            and event["payload"]["proposal_id"] == pending_rejected_proposal_id
        )
        _validate_event_log_decision_transition(
            event,
            decision_status,
            accepts_immediate_rejected_proposal=accepts_immediate_rejected_proposal,
        )
        if event["event_type"] == "proposal_rejected":
            pending_rejected_proposal_id = event["payload"]["proposal_id"]
        else:
            pending_rejected_proposal_id = None
        if event["event_type"] == "close_summary_generated":
            has_close_summary[event["session_id"]] = True
            pending_close_summary_session_id = event["session_id"]
        if event["event_type"] == "plan_generated":
            for referenced_session_id in event["payload"]["session_ids"]:
                if referenced_session_id not in created_session_ids:
                    raise StateValidationError(
                        f"plan_generated references unknown session: {referenced_session_id}"
                    )
                if session_status.get(referenced_session_id) != "closed":
                    raise StateValidationError(
                        f"plan_generated references non-closed session: {referenced_session_id}"
                    )
        if event["event_type"] == "session_closed":
            session_status[event["session_id"]] = "closed"
        if event["event_type"] in {"session_resumed", "session_closed"}:
            proposal_id = active_proposal_by_session.get(event["session_id"])
            if proposal_id:
                disabled_proposals.add(proposal_id)
                target_id = issued_proposals[proposal_id]["target_id"]
                if decision_status.get(target_id) == "proposed":
                    decision_status[target_id] = "unresolved"
                active_proposal_by_session[event["session_id"]] = None
        elif event["event_type"] == "decision_invalidated":
            invalidated_id = event["payload"]["decision_id"]
            for candidate_session_id, proposal_id in list(active_proposal_by_session.items()):
                if proposal_id and issued_proposals.get(proposal_id, {}).get("target_id") == invalidated_id:
                    disabled_proposals.add(proposal_id)
                    active_proposal_by_session[candidate_session_id] = None
    if pending_question is not None:
        raise StateValidationError("question_asked must be followed by matching proposal_issued")
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


def _validate_session_linked_event(
    event: dict[str, Any],
    created_session_ids: set[str],
    linked_edges: list[tuple[str, str, str]],
    seen_link_keys: set[tuple[str, str, str]],
) -> None:
    payload = event["payload"]
    parent_session_id = payload["parent_session_id"]
    child_session_id = payload["child_session_id"]
    relationship = payload["relationship"]
    if parent_session_id not in created_session_ids:
        raise StateValidationError(f"session_linked references unknown parent session: {parent_session_id}")
    if child_session_id not in created_session_ids:
        raise StateValidationError(f"session_linked references unknown child session: {child_session_id}")
    if event["session_id"] != child_session_id:
        raise StateValidationError("session_linked event.session_id must match child_session_id")
    link_key = (parent_session_id, child_session_id, relationship)
    if link_key in seen_link_keys:
        raise StateValidationError("duplicate session_linked relationship")
    seen_link_keys.add(link_key)
    if relationship != "contradicts" and _would_create_session_graph_cycle(
        linked_edges,
        parent_session_id,
        child_session_id,
    ):
        raise StateValidationError("session_linked would create a session graph cycle")
    linked_edges.append(link_key)


def _would_create_session_graph_cycle(
    linked_edges: list[tuple[str, str, str]],
    parent_session_id: str,
    child_session_id: str,
) -> bool:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for parent, child, relationship in linked_edges:
        if relationship == "contradicts":
            continue
        adjacency[parent].add(child)
    stack = [child_session_id]
    visited: set[str] = set()
    while stack:
        current = stack.pop()
        if current == parent_session_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        stack.extend(sorted(adjacency.get(current, set()), reverse=True))
    return False


def _validate_semantic_conflict_resolved_event(
    event: dict[str, Any],
    created_session_ids: set[str],
    resolved_conflict_ids: set[str],
) -> None:
    payload = event["payload"]
    conflict_id = payload["conflict_id"]
    if conflict_id in resolved_conflict_ids:
        raise StateValidationError(f"duplicate semantic_conflict_resolved conflict_id: {conflict_id}")
    resolved_conflict_ids.add(conflict_id)
    winning_session_id = payload["winning_session_id"]
    rejected_session_ids = payload["rejected_session_ids"]
    scope_session_ids = set(payload["scope"]["session_ids"])
    if winning_session_id not in created_session_ids:
        raise StateValidationError(f"semantic_conflict_resolved references unknown winning session: {winning_session_id}")
    if event["session_id"] != winning_session_id:
        raise StateValidationError("semantic_conflict_resolved event.session_id must match winning_session_id")
    if winning_session_id not in scope_session_ids:
        raise StateValidationError("semantic_conflict_resolved winning_session_id must be in scope")
    for rejected_session_id in rejected_session_ids:
        if rejected_session_id not in created_session_ids:
            raise StateValidationError(
                f"semantic_conflict_resolved references unknown rejected session: {rejected_session_id}"
            )
        if rejected_session_id not in scope_session_ids:
            raise StateValidationError("semantic_conflict_resolved rejected_session_ids must be in scope")


def _validate_session_graph(session_graph: dict[str, Any]) -> None:
    graph = _require_dict(session_graph, "project_state.session_graph")
    _require_keys(
        graph,
        ("nodes", "edges", "inferred_candidates", "resolved_conflicts"),
        "project_state.session_graph",
    )
    for key in ("nodes", "edges", "inferred_candidates", "resolved_conflicts"):
        _require_list(graph[key], f"project_state.session_graph.{key}")
    node_ids: set[str] = set()
    for node in graph["nodes"]:
        node_payload = _require_dict(node, "project_state.session_graph.nodes[]")
        _require_keys(
            node_payload,
            ("session_id", "status", "decision_ids", "close_summary_preview"),
            "project_state.session_graph.nodes[]",
        )
        _require_non_empty_string(node_payload.get("session_id"), "project_state.session_graph.nodes[].session_id")
        if node_payload["session_id"] in node_ids:
            raise StateValidationError(f"duplicate session graph node: {node_payload['session_id']}")
        node_ids.add(node_payload["session_id"])
        _require_list(node_payload["decision_ids"], "project_state.session_graph.nodes[].decision_ids")
        _require_dict(
            node_payload["close_summary_preview"],
            "project_state.session_graph.nodes[].close_summary_preview",
        )
    for edge in graph["edges"]:
        edge_payload = _require_dict(edge, "project_state.session_graph.edges[]")
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
            "project_state.session_graph.edges[]",
        )
        _require_non_empty_string(edge_payload["parent_session_id"], "project_state.session_graph.edges[].parent_session_id")
        _require_non_empty_string(edge_payload["child_session_id"], "project_state.session_graph.edges[].child_session_id")
        _require_enum(edge_payload["relationship"], SESSION_RELATIONSHIPS, "project_state.session_graph.edges[].relationship")
        _require_non_empty_string(edge_payload["reason"], "project_state.session_graph.edges[].reason")
        _require_timestamp(edge_payload["linked_at"], "project_state.session_graph.edges[].linked_at")
        _require_list(edge_payload["evidence_refs"], "project_state.session_graph.edges[].evidence_refs")
        _require_non_empty_string(edge_payload["event_id"], "project_state.session_graph.edges[].event_id")
    for resolved in graph["resolved_conflicts"]:
        resolved_payload = _require_dict(resolved, "project_state.session_graph.resolved_conflicts[]")
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
            "project_state.session_graph.resolved_conflicts[]",
        )
        _require_non_empty_string(
            resolved_payload["conflict_id"],
            "project_state.session_graph.resolved_conflicts[].conflict_id",
        )
        _require_non_empty_string(
            resolved_payload["winning_session_id"],
            "project_state.session_graph.resolved_conflicts[].winning_session_id",
        )
        _require_list(
            resolved_payload["rejected_session_ids"],
            "project_state.session_graph.resolved_conflicts[].rejected_session_ids",
        )
        _require_dict(resolved_payload["scope"], "project_state.session_graph.resolved_conflicts[].scope")
        _validate_suppressed_context(
            resolved_payload["suppressed_context"],
            "project_state.session_graph.resolved_conflicts[].suppressed_context",
        )
        _require_non_empty_string(resolved_payload["reason"], "project_state.session_graph.resolved_conflicts[].reason")
        _require_timestamp(resolved_payload["resolved_at"], "project_state.session_graph.resolved_conflicts[].resolved_at")
        _require_non_empty_string(resolved_payload["event_id"], "project_state.session_graph.resolved_conflicts[].event_id")


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
    for resolved in project_state.get("session_graph", {}).get("resolved_conflicts", []):
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


def _validate_event_log_proposal_lifecycle(
    event: dict[str, Any],
    issued_proposals: dict[str, dict[str, str]],
    active_proposal_by_session: dict[str, str | None],
    disabled_proposals: set[str],
    accepted_proposals: set[str],
    rejected_proposals: set[str],
) -> None:
    event_type = event["event_type"]
    payload = event["payload"]
    if event_type == "proposal_issued":
        proposal = payload["proposal"]
        proposal_id = proposal["proposal_id"]
        if proposal_id in issued_proposals:
            raise StateValidationError(f"duplicate proposal_id: {proposal_id}")
        issued_proposals[proposal_id] = {
            "origin_session_id": proposal["origin_session_id"],
            "target_id": proposal["target_id"],
            "target_type": proposal["target_type"],
        }
        previous = active_proposal_by_session.get(event["session_id"])
        if previous:
            raise StateValidationError(f"proposal_issued while proposal {previous} is still active")
        active_proposal_by_session[event["session_id"]] = proposal_id
    elif event_type in {"proposal_accepted", "proposal_rejected"}:
        proposal_id = payload["proposal_id"]
        issued = issued_proposals.get(proposal_id)
        if issued is None:
            raise StateValidationError(f"{event_type} references unknown proposal {proposal_id}")
        if event_type == "proposal_accepted" and proposal_id in accepted_proposals:
            raise StateValidationError(f"duplicate proposal_accepted for {proposal_id}")
        if event_type == "proposal_rejected" and proposal_id in rejected_proposals:
            raise StateValidationError(f"duplicate proposal_rejected for {proposal_id}")
        if proposal_id in disabled_proposals:
            raise StateValidationError(f"{event_type} references inactive proposal {proposal_id}")
        if payload["origin_session_id"] != issued["origin_session_id"]:
            raise StateValidationError("proposal response origin_session_id does not match issued proposal")
        if payload["target_id"] != issued["target_id"]:
            raise StateValidationError("proposal response target_id does not match issued proposal")
        if payload["target_type"] != issued["target_type"]:
            raise StateValidationError("proposal response target_type does not match issued proposal")
        if event_type == "proposal_accepted":
            accepted_proposal_id = payload["accepted_answer"].get("proposal_id")
            if accepted_proposal_id != proposal_id:
                raise StateValidationError("accepted_answer.proposal_id must match payload.proposal_id")
            accepted_proposals.add(proposal_id)
            disabled_proposals.add(proposal_id)
            active_proposal_by_session[payload["origin_session_id"]] = None
        else:
            rejected_proposals.add(proposal_id)


def _expire_pending_rejected_proposal(
    event: dict[str, Any],
    pending_rejected_proposal_id: str | None,
    issued_proposals: dict[str, dict[str, str]],
    active_proposal_by_session: dict[str, str | None],
    disabled_proposals: set[str],
) -> str | None:
    if pending_rejected_proposal_id is None:
        return None
    if (
        event["event_type"] == "proposal_accepted"
        and event["payload"]["proposal_id"] == pending_rejected_proposal_id
    ):
        return pending_rejected_proposal_id

    disabled_proposals.add(pending_rejected_proposal_id)
    origin_session_id = issued_proposals[pending_rejected_proposal_id]["origin_session_id"]
    if active_proposal_by_session.get(origin_session_id) == pending_rejected_proposal_id:
        active_proposal_by_session[origin_session_id] = None
    return None


def _deactivate_active_proposal_for_decision_event(
    event: dict[str, Any],
    issued_proposals: dict[str, dict[str, str]],
    active_proposal_by_session: dict[str, str | None],
    disabled_proposals: set[str],
) -> None:
    event_type = event["event_type"]
    if event_type not in {"decision_deferred", "decision_resolved_by_evidence"}:
        return

    session_id = event["session_id"]
    decision_id = event["payload"]["decision_id"]
    active_proposal_id = active_proposal_by_session.get(session_id)
    if not active_proposal_id:
        return

    active_target_id = issued_proposals[active_proposal_id]["target_id"]
    if active_target_id != decision_id:
        raise StateValidationError(
            f"{event_type} targets {decision_id} while proposal "
            f"{active_proposal_id} is active for {active_target_id}"
        )

    disabled_proposals.add(active_proposal_id)
    active_proposal_by_session[session_id] = None


def _validate_event_log_question_pairing(
    event: dict[str, Any], pending_question: dict[str, str] | None
) -> dict[str, str] | None:
    event_type = event["event_type"]
    if pending_question is not None:
        if event_type != "proposal_issued":
            raise StateValidationError("question_asked must be followed by matching proposal_issued")
        proposal = event["payload"]["proposal"]
        if event["session_id"] != pending_question["session_id"]:
            raise StateValidationError("proposal_issued does not match pending question session")
        if proposal["target_id"] != pending_question["decision_id"]:
            raise StateValidationError("proposal_issued does not match pending question decision")
        if proposal["question_id"] != pending_question["question_id"]:
            raise StateValidationError("proposal_issued does not match pending question_id")
        if proposal["question"] != pending_question["question"]:
            raise StateValidationError("proposal_issued does not match pending question text")
        return None

    if event_type == "question_asked":
        return {
            "session_id": event["session_id"],
            "decision_id": event["payload"]["decision_id"],
            "question_id": event["payload"]["question_id"],
            "question": event["payload"]["question"],
        }
    return None


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


def _validate_event_log_decision_transition(
    event: dict[str, Any],
    decision_status: dict[str, str],
    *,
    accepts_immediate_rejected_proposal: bool = False,
) -> None:
    event_type = event["event_type"]
    payload = event["payload"]
    if event_type == "proposal_issued":
        decision_id = payload["proposal"]["target_id"]
        _require_event_decision_status(decision_id, decision_status, {"unresolved", "rejected", "blocked"}, event_type)
        decision_status[decision_id] = "proposed"
    elif event_type == "proposal_rejected":
        decision_id = payload["target_id"]
        _require_event_decision_status(decision_id, decision_status, {"proposed"}, event_type)
        decision_status[decision_id] = "rejected"
    elif event_type == "proposal_accepted":
        decision_id = payload["target_id"]
        allowed = {"proposed"}
        if accepts_immediate_rejected_proposal:
            allowed.add("rejected")
        _require_event_decision_status(decision_id, decision_status, allowed, event_type)
        decision_status[decision_id] = "accepted"
    elif event_type == "decision_deferred":
        decision_id = payload["decision_id"]
        _require_event_decision_status(
            decision_id, decision_status, {"unresolved", "proposed", "rejected", "blocked"}, event_type
        )
        decision_status[decision_id] = "deferred"
    elif event_type == "decision_resolved_by_evidence":
        decision_id = payload["decision_id"]
        _require_event_decision_status(
            decision_id, decision_status, {"unresolved", "proposed", "rejected", "blocked"}, event_type
        )
        decision_status[decision_id] = "resolved-by-evidence"
    elif event_type == "decision_invalidated":
        target_id = payload["decision_id"]
        invalidating_id = payload["invalidated_by_decision_id"]
        _require_event_decision_status(
            invalidating_id,
            decision_status,
            FINAL_INVALIDATING_STATUSES,
            event_type,
        )
        if decision_status[target_id] == "invalidated":
            raise StateValidationError(f"decision {target_id} is already invalidated")
        decision_status[target_id] = "invalidated"


def _require_event_decision_status(
    decision_id: str, decision_status: dict[str, str], allowed: set[str], event_type: str
) -> None:
    status = decision_status[decision_id]
    if status not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise StateValidationError(
            f"{event_type} cannot target decision {decision_id} with status {status}; "
            f"allowed statuses: {allowed_values}"
        )


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
    invalidated_by = decision.get("invalidated_by")
    if not isinstance(invalidated_by, dict):
        return False
    invalidating_id = invalidated_by.get("decision_id")
    if not invalidating_id:
        return False
    return _has_final_invalidating_chain(invalidating_id, decisions_by_id, seen=seen)


def _validate_event_log_session_decision_binding(
    event: dict[str, Any], session_decision_ids: dict[str, set[str]]
) -> None:
    event_type = event["event_type"]
    session_id = event["session_id"]
    if event_type in {
        "decision_enriched",
        "question_asked",
        "proposal_issued",
        "proposal_accepted",
        "proposal_rejected",
        "decision_deferred",
        "decision_resolved_by_evidence",
    }:
        for decision_id in _decision_refs_in_event(event):
            if decision_id not in session_decision_ids[session_id]:
                raise StateValidationError(
                    f"{event_type} references decision {decision_id} not bound to session {session_id}"
                )
    elif event_type == "decision_invalidated":
        invalidating_id = event["payload"]["invalidated_by_decision_id"]
        if invalidating_id not in session_decision_ids[session_id]:
            raise StateValidationError(
                f"decision_invalidated references invalidating decision {invalidating_id} "
                f"not bound to session {session_id}"
            )


def _decision_refs_in_event(event: dict[str, Any]) -> list[str]:
    event_type = event["event_type"]
    payload = event["payload"]
    if event_type in {"decision_enriched", "question_asked", "decision_deferred", "decision_resolved_by_evidence"}:
        return [payload["decision_id"]]
    if event_type == "proposal_issued":
        return [payload["proposal"]["target_id"]]
    if event_type in {"proposal_accepted", "proposal_rejected"}:
        return [payload["target_id"]]
    if event_type == "decision_invalidated":
        return [payload["decision_id"], payload["invalidated_by_decision_id"]]
    return []


def _require_non_empty_string(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise StateValidationError(f"{label} must be a non-empty string")


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


def _recomputed_counts(decisions: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"p0_now_open": 0, "p1_now_open": 0, "p2_open": 0, "blocked": 0, "deferred": 0}
    for decision in decisions:
        status = decision["status"]
        if decision["priority"] == "P0" and decision["frontier"] == "now" and status in OPEN_DECISION_STATUSES:
            counts["p0_now_open"] += 1
        if decision["priority"] == "P1" and decision["frontier"] == "now" and status in OPEN_DECISION_STATUSES:
            counts["p1_now_open"] += 1
        if decision["priority"] == "P2" and status in OPEN_DECISION_STATUSES:
            counts["p2_open"] += 1
        if status == "blocked":
            counts["blocked"] += 1
        if status == "deferred":
            counts["deferred"] += 1
    return counts
