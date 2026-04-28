from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from decide_me.constants import (
    ACCEPTED_VIA_VALUES,
    DECISION_STACK_LAYERS,
    DOMAIN_VALUES,
    EVIDENCE_SOURCES,
    LINK_RELATIONS,
    OBJECT_TYPES,
)
from decide_me.events import EVENT_TYPES, validate_event
from decide_me.object_views import active_proposal_view, proposal_decision_id, proposal_option, related_decision_ids
from decide_me.projections import (
    PROJECT_STATE_SCHEMA_VERSION,
    SESSION_STATE_SCHEMA_VERSION,
    build_decision_stack_graph,
)
from decide_me.requirement_ids import is_requirement_id
from decide_me.suppression import (
    has_remaining_suppressed_scope,
    has_suppressed_context_remainders,
    suppressed_decision_ids,
)
from decide_me.taxonomy import taxonomy_by_id


OPEN_DECISION_STATUSES = {"unresolved", "proposed", "blocked"}
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
CLOSE_SUMMARY_OBJECT_ID_KEYS = (
    "decisions",
    "blockers",
    "risks",
    "actions",
    "evidence",
    "verifications",
    "revisit_triggers",
)


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
        _validate_object_metadata_layer(obj, metadata)
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
    _validate_object_link_contracts(objects, links)
    _validate_graph(project_state["graph"], objects, links)
    _validate_schema_relation_enums()


def _validate_object_link_contracts(objects: list[dict[str, Any]], links: list[dict[str, Any]]) -> None:
    by_id = {obj["id"]: obj for obj in objects}
    for proposal in [obj for obj in objects if obj.get("type") == "proposal"]:
        addresses = [
            link
            for link in links
            if link["source_object_id"] == proposal["id"] and link["relation"] == "addresses"
        ]
        recommends = [
            link
            for link in links
            if link["source_object_id"] == proposal["id"] and link["relation"] == "recommends"
        ]
        if len(addresses) != 1:
            raise StateValidationError(f"proposal {proposal['id']} must have exactly one addresses link")
        if by_id[addresses[0]["target_object_id"]]["type"] != "decision":
            raise StateValidationError(f"proposal {proposal['id']} addresses non-decision object")
        if len(recommends) != 1:
            raise StateValidationError(f"proposal {proposal['id']} must have exactly one recommends link")
        if by_id[recommends[0]["target_object_id"]]["type"] != "option":
            raise StateValidationError(f"proposal {proposal['id']} recommends non-option object")
    for decision in [obj for obj in objects if obj.get("type") == "decision"]:
        if decision["status"] == "accepted":
            accepted_links = [
                link
                for link in links
                if link["source_object_id"] == decision["id"] and link["relation"] == "accepts"
            ]
            if not accepted_links:
                raise StateValidationError(f"accepted decision {decision['id']} must accept a proposal")
            for link in accepted_links:
                if by_id[link["target_object_id"]]["type"] != "proposal":
                    raise StateValidationError(f"decision {decision['id']} accepts non-proposal object")
        if decision["status"] == "resolved-by-evidence":
            support_links = [
                link
                for link in links
                if link["target_object_id"] == decision["id"] and link["relation"] == "supports"
            ]
            if not support_links:
                raise StateValidationError(f"evidence-resolved decision {decision['id']} must have support link")
            for link in support_links:
                if by_id[link["source_object_id"]]["type"] != "evidence":
                    raise StateValidationError(f"decision {decision['id']} is supported by non-evidence object")


def _validate_object_metadata_layer(obj: dict[str, Any], metadata: dict[str, Any]) -> None:
    if "layer" not in metadata:
        return
    _require_enum(metadata["layer"], DECISION_STACK_LAYERS, f"object {obj['id']}.metadata.layer")


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
            ("id", "status", "started_at", "last_seen_at", "closed_at", "bound_context_hint", "related_object_ids"),
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
        _require_list(
            session.get("related_object_ids"),
            f"project_state.sessions_index.{session_id}.related_object_ids",
        )
        for object_id in session["related_object_ids"]:
            _require_non_empty_string(
                object_id,
                f"project_state.sessions_index.{session_id}.related_object_ids[]",
            )


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
    status = decision["status"]
    if status not in ALL_DECISION_STATUSES:
        raise StateValidationError(f"unsupported decision status: {status}")


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
        ("id", "started_at", "last_seen_at", "bound_context_hint", "related_object_ids", "lifecycle"),
        "session_state.session",
    )
    _require_timestamp(session_state["session"].get("started_at"), "session_state.session.started_at")
    _require_timestamp(session_state["session"].get("last_seen_at"), "session_state.session.last_seen_at")
    _require_list(session_state["session"]["related_object_ids"], "session_state.session.related_object_ids")
    lifecycle = _require_dict(session_state["session"]["lifecycle"], "session_state.session.lifecycle")
    _require_keys(lifecycle, ("status", "closed_at"), "session_state.session.lifecycle")
    _require_enum(lifecycle["status"], SESSION_LIFECYCLE_STATUSES, "session_state.session.lifecycle.status")
    if lifecycle["status"] == "closed":
        _require_timestamp(lifecycle.get("closed_at"), "session_state.session.lifecycle.closed_at")
    elif lifecycle.get("closed_at") is not None:
        raise StateValidationError("active session lifecycle.closed_at must be null")
    _require_keys(
        session_state["summary"],
        ("latest_summary", "current_question_preview"),
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
    close_summary = session_state["close_summary"]
    _require_keys(
        close_summary,
        ("work_item", "readiness", "object_ids", "link_ids", "generated_at"),
        "session_state.close_summary",
    )
    unsupported_close_summary_keys = sorted(
        set(close_summary) - {"work_item", "readiness", "object_ids", "link_ids", "generated_at"}
    )
    if unsupported_close_summary_keys:
        raise StateValidationError(
            "session_state.close_summary contains unsupported fields: "
            + ", ".join(unsupported_close_summary_keys)
        )
    work_item = _require_dict(close_summary["work_item"], "session_state.close_summary.work_item")
    _require_keys(work_item, ("title", "statement", "objective_object_id"), "session_state.close_summary.work_item")
    unsupported_work_item_keys = sorted(set(work_item) - {"title", "statement", "objective_object_id"})
    if unsupported_work_item_keys:
        raise StateValidationError(
            "session_state.close_summary.work_item contains unsupported fields: "
            + ", ".join(unsupported_work_item_keys)
        )
    for key in ("title", "statement", "objective_object_id"):
        value = work_item.get(key)
        if value is not None and not isinstance(value, str):
            raise StateValidationError(f"session_state.close_summary.work_item.{key} must be a string or null")
    _require_enum(close_summary["readiness"], {"ready", "conditional", "blocked"}, "session_state.close_summary.readiness")
    object_ids = _require_dict(close_summary["object_ids"], "session_state.close_summary.object_ids")
    _require_keys(object_ids, CLOSE_SUMMARY_OBJECT_ID_KEYS, "session_state.close_summary.object_ids")
    unsupported_object_id_keys = sorted(set(object_ids) - set(CLOSE_SUMMARY_OBJECT_ID_KEYS))
    if unsupported_object_id_keys:
        raise StateValidationError(
            "session_state.close_summary.object_ids contains unsupported fields: "
            + ", ".join(unsupported_object_id_keys)
        )
    for key in CLOSE_SUMMARY_OBJECT_ID_KEYS:
        _require_list(object_ids[key], f"session_state.close_summary.object_ids.{key}")
        if len(object_ids[key]) != len(set(object_ids[key])):
            raise StateValidationError(f"session_state.close_summary.object_ids.{key} contains duplicate ids")
        for object_id in object_ids[key]:
            _require_non_empty_string(object_id, f"session_state.close_summary.object_ids.{key}[]")
    _require_list(close_summary["link_ids"], "session_state.close_summary.link_ids")
    if len(close_summary["link_ids"]) != len(set(close_summary["link_ids"])):
        raise StateValidationError("session_state.close_summary.link_ids contains duplicate ids")
    for link_id in close_summary["link_ids"]:
        _require_non_empty_string(link_id, "session_state.close_summary.link_ids[]")
    _require_keys(
        session_state["working_state"],
        ("active_question_id", "active_proposal_id", "last_seen_project_head"),
        "session_state.working_state",
    )
    for key in ("assigned_tags", "search_terms", "source_refs"):
        _require_list(session_state["classification"][key], f"session_state.classification.{key}")
    _require_optional_timestamp(
        session_state["classification"].get("updated_at"),
        "session_state.classification.updated_at",
    )
    _require_optional_timestamp(
        close_summary.get("generated_at"),
        "session_state.close_summary.generated_at",
    )


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

    for session_id, session in bundle["sessions"].items():
        _validate_session_integrity(
            session_id,
            session,
            bundle["project_state"],
            decisions_by_id,
            visible_ids,
            taxonomy_ids,
        )
    _validate_decision_references(bundle["project_state"], decisions_by_id)
    _validate_visible_decision_bindings(bundle["project_state"], bundle["sessions"], visible_ids)


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
            "related_object_ids": list(session.get("related_object_ids", [])),
        }
    return index


def _visible_decision_ids(decisions_by_id: dict[str, dict[str, Any]]) -> set[str]:
    return {
        decision_id
        for decision_id, decision in decisions_by_id.items()
        if decision.get("status") != "invalidated"
    }


def _validate_decision_references(
    project_state: dict[str, Any], decisions_by_id: dict[str, dict[str, Any]]
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
            active_proposals = [
                obj
                for obj in project_state["objects"]
                if obj.get("type") == "proposal"
                and obj.get("status") == "active"
                and proposal_decision_id(project_state, obj["id"]) == decision_id
            ]
            if len(active_proposals) != 1:
                raise StateValidationError(
                    f"decision {decision_id} is proposed but has {len(active_proposals)} active proposal objects"
                )


def _validate_visible_decision_bindings(
    project_state: dict[str, Any],
    sessions: dict[str, dict[str, Any]],
    visible_decision_ids: set[str],
) -> None:
    bound_decision_ids = {
        decision_id
        for session in sessions.values()
        for decision_id in related_decision_ids(project_state, session["session"]["related_object_ids"])
    }
    unbound = visible_decision_ids - bound_decision_ids - suppressed_decision_ids(project_state)
    if unbound:
        raise StateValidationError(
            f"visible decisions are not bound to any session: {sorted(unbound)}"
        )


def _validate_session_integrity(
    session_key: str,
    session: dict[str, Any],
    project_state: dict[str, Any],
    decisions_by_id: dict[str, dict[str, Any]],
    visible_ids: set[str],
    taxonomy_ids: set[str],
) -> None:
    session_id = session["session"]["id"]
    if session_id != session_key:
        raise StateValidationError(f"session map key {session_key} does not match session id {session_id}")

    related_object_ids = session["session"]["related_object_ids"]
    if len(related_object_ids) != len(set(related_object_ids)):
        raise StateValidationError(f"session {session_id} contains duplicate related_object_ids")
    object_ids = {obj["id"] for obj in project_state["objects"]}
    for object_id in related_object_ids:
        if object_id not in object_ids:
            raise StateValidationError(f"session {session_id} references unknown related object {object_id}")
    session_decision_ids = set(related_decision_ids(project_state, related_object_ids))
    for decision_id in session_decision_ids:
        if decision_id not in visible_ids:
            raise StateValidationError(f"session {session_id} references non-visible decision {decision_id}")

    _validate_classification_refs(session_id, session, taxonomy_ids)
    _validate_active_proposal(session_id, session, project_state, decisions_by_id, visible_ids, session_decision_ids)
    _validate_close_summary(
        session_id,
        session,
        project_state,
        decisions_by_id,
        visible_ids,
        session_decision_ids,
    )


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
    project_state: dict[str, Any],
    decisions_by_id: dict[str, dict[str, Any]],
    visible_ids: set[str],
    session_decision_ids: set[str],
) -> None:
    working_state = session["working_state"]
    lifecycle_status = session["session"]["lifecycle"]["status"]
    active_question_id = working_state.get("active_question_id")
    active_proposal_id = working_state.get("active_proposal_id")
    if lifecycle_status == "closed" and (active_question_id or active_proposal_id):
        raise StateValidationError(f"closed session {session_id} must not have current question state")
    if lifecycle_status == "closed":
        _require_timestamp(
            session["close_summary"].get("generated_at"),
            f"session {session_id}.close_summary.generated_at",
        )

    if not active_proposal_id:
        _validate_question_state(session_id, session)
        return
    active = active_proposal_view(project_state, session)
    if active is None:
        raise StateValidationError(f"session {session_id} active_proposal_id references missing proposal")
    if active.get("origin_session_id") and active.get("origin_session_id") != session_id:
        raise StateValidationError(f"session {session_id} active proposal has wrong origin_session_id")
    if not active.get("is_active"):
        raise StateValidationError(f"session {session_id} active proposal object is not active")
    if active.get("question_id") != active_question_id:
        raise StateValidationError(f"session {session_id} active_question_id does not match proposal")

    target_id = active.get("target_id")
    if not target_id:
        raise StateValidationError(f"session {session_id} active proposal does not address a decision")
    if target_id not in decisions_by_id:
        raise StateValidationError(f"session {session_id} active proposal references unknown decision {target_id}")
    if target_id not in visible_ids:
        raise StateValidationError(f"session {session_id} active proposal references non-visible decision {target_id}")
    if target_id not in session_decision_ids:
        raise StateValidationError(f"session {session_id} active proposal target is not bound to the session")
    decision = decisions_by_id[target_id]
    if decision["status"] != "proposed":
        raise StateValidationError(
            f"session {session_id} active proposal target {target_id} is not proposed"
        )
    if proposal_option(project_state, active_proposal_id) is None:
        raise StateValidationError(f"session {session_id} active proposal does not recommend an option")
    _validate_question_state(session_id, session)


def _validate_question_state(session_id: str, session: dict[str, Any]) -> None:
    working_state = session["working_state"]
    active_question_id = working_state.get("active_question_id")
    active_proposal_id = working_state.get("active_proposal_id")
    preview = session["summary"].get("current_question_preview")
    has_question = bool(active_question_id or active_proposal_id or preview)
    if has_question and not (active_question_id and active_proposal_id and preview):
        raise StateValidationError(f"session {session_id} has incomplete active question state")


def _validate_close_summary(
    session_id: str,
    session: dict[str, Any],
    project_state: dict[str, Any],
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
    object_ids = close_summary["object_ids"]
    objects_by_id = {obj["id"]: obj for obj in project_state["objects"]}
    links_by_id = {link["id"]: link for link in project_state["links"]}
    objective_id = close_summary["work_item"].get("objective_object_id")
    if objective_id is not None and objective_id not in objects_by_id:
        raise StateValidationError(f"session {session_id} close_summary.work_item references unknown objective")
    for section, expected_type in (
        ("decisions", "decision"),
        ("blockers", "decision"),
        ("actions", "action"),
        ("evidence", "evidence"),
        ("verifications", "verification"),
        ("revisit_triggers", "revisit_trigger"),
    ):
        for object_id in object_ids.get(section, []):
            obj = objects_by_id.get(object_id)
            if obj is None:
                raise StateValidationError(f"session {session_id} close_summary.object_ids.{section} references unknown object {object_id}")
            if obj.get("type") != expected_type:
                raise StateValidationError(f"session {session_id} close_summary.object_ids.{section} references non-{expected_type} object {object_id}")
    for object_id in object_ids.get("risks", []):
        obj = objects_by_id.get(object_id)
        if obj is None:
            raise StateValidationError(f"session {session_id} close_summary.object_ids.risks references unknown object {object_id}")
        if obj.get("type") != "risk" and not (obj.get("type") == "decision" and obj.get("metadata", {}).get("kind") == "risk"):
            raise StateValidationError(f"session {session_id} close_summary.object_ids.risks references non-risk object {object_id}")
    for decision_id in object_ids.get("decisions", []):
        if decision_id not in visible_session_ids:
            raise StateValidationError(f"session {session_id} close_summary.object_ids.decisions references non-visible decision {decision_id}")
    for decision_id in object_ids.get("blockers", []):
        if decision_id not in visible_session_ids:
            raise StateValidationError(f"session {session_id} close_summary.object_ids.blockers references non-visible decision {decision_id}")
        decision = decisions_by_id[decision_id]
        if decision.get("status") not in OPEN_DECISION_STATUSES:
            raise StateValidationError(f"session {session_id} close_summary.object_ids.blockers references non-open decision {decision_id}")
    accepted_ids = {
        decision_id
        for decision_id in object_ids.get("decisions", [])
        if decisions_by_id.get(decision_id, {}).get("status") in {"accepted", "resolved-by-evidence"}
    }
    for action_id in object_ids.get("actions", []):
        addresses = [
            link
            for link in project_state["links"]
            if link.get("source_object_id") == action_id
            and link.get("relation") == "addresses"
            and link.get("target_object_id") in accepted_ids
        ]
        if not addresses:
            raise StateValidationError(
                f"session {session_id} close_summary action {action_id} does not address an accepted decision"
            )
    for link_id in close_summary.get("link_ids", []):
        if link_id not in links_by_id:
            raise StateValidationError(f"session {session_id} close_summary.link_ids references unknown link {link_id}")


def _close_summary_readiness(close_summary: dict[str, Any]) -> str:
    object_ids = close_summary.get("object_ids", {})
    if object_ids.get("blockers"):
        return "blocked"
    if object_ids.get("risks"):
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
            if question_id is None:
                if payload["answer"].get("answered_via") != "defer":
                    raise StateValidationError("null session_answer_recorded question_id is only valid for defer")
            else:
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


def _validate_graph(
    decision_stack_graph: dict[str, Any],
    objects: list[dict[str, Any]],
    links: list[dict[str, Any]],
) -> None:
    graph = _require_dict(decision_stack_graph, "project_state.graph")
    _require_keys(
        graph,
        ("nodes", "edges", "inferred_candidates", "resolved_conflicts"),
        "project_state.graph",
    )
    unsupported = sorted(set(graph) - {"nodes", "edges", "inferred_candidates", "resolved_conflicts"})
    if unsupported:
        raise StateValidationError(
            "project_state.graph contains unsupported fields: " + ", ".join(unsupported)
        )
    for key in ("nodes", "edges", "inferred_candidates", "resolved_conflicts"):
        _require_list(graph[key], f"project_state.graph.{key}")
    _validate_decision_stack_graph_nodes(graph["nodes"], objects, links)
    _validate_decision_stack_graph_edges(graph["edges"], objects, links)
    for node in graph["nodes"]:
        _require_dict(node, "project_state.graph.nodes[]")
    for edge in graph["edges"]:
        _require_dict(edge, "project_state.graph.edges[]")
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


def _validate_decision_stack_graph_nodes(
    nodes: list[dict[str, Any]],
    objects: list[dict[str, Any]],
    links: list[dict[str, Any]],
) -> None:
    expected_nodes = {
        node["object_id"]: node
        for node in build_decision_stack_graph({"objects": objects, "links": links, "graph": {}})["nodes"]
    }
    object_ids = set(expected_nodes)
    node_ids: set[str] = set()
    for node in nodes:
        node_payload = _require_dict(node, "project_state.graph.nodes[]")
        _require_keys(
            node_payload,
            ("object_id", "object_type", "layer", "status", "title", "is_frontier", "is_invalidated"),
            "project_state.graph.nodes[]",
        )
        unsupported = sorted(
            set(node_payload)
            - {"object_id", "object_type", "layer", "status", "title", "is_frontier", "is_invalidated"}
        )
        if unsupported:
            raise StateValidationError(
                "project_state.graph.nodes[] contains unsupported fields: " + ", ".join(unsupported)
            )
        _require_non_empty_string(node_payload.get("object_id"), "project_state.graph.nodes[].object_id")
        _require_enum(node_payload.get("object_type"), OBJECT_TYPES, "project_state.graph.nodes[].object_type")
        _require_enum(node_payload.get("layer"), DECISION_STACK_LAYERS, "project_state.graph.nodes[].layer")
        _require_non_empty_string(node_payload.get("status"), "project_state.graph.nodes[].status")
        if node_payload.get("title") is not None:
            _require_non_empty_string(node_payload.get("title"), "project_state.graph.nodes[].title")
        if not isinstance(node_payload.get("is_frontier"), bool):
            raise StateValidationError("project_state.graph.nodes[].is_frontier must be a boolean")
        if not isinstance(node_payload.get("is_invalidated"), bool):
            raise StateValidationError("project_state.graph.nodes[].is_invalidated must be a boolean")
        object_id = node_payload["object_id"]
        if object_id in node_ids:
            raise StateValidationError(f"duplicate decision stack graph node: {object_id}")
        node_ids.add(object_id)
        if object_id not in object_ids:
            raise StateValidationError(f"graph node {object_id} references missing object")
        if node_payload != expected_nodes[object_id]:
            raise StateValidationError(f"graph node {object_id} does not match object projection")
    if node_ids != object_ids:
        missing = sorted(object_ids - node_ids)
        extra = sorted(node_ids - object_ids)
        detail = []
        if missing:
            detail.append("missing nodes for objects: " + ", ".join(missing))
        if extra:
            detail.append("extra nodes: " + ", ".join(extra))
        raise StateValidationError("project_state.graph.nodes do not match objects: " + "; ".join(detail))


def _validate_decision_stack_graph_edges(
    edges: list[dict[str, Any]],
    objects: list[dict[str, Any]],
    links: list[dict[str, Any]],
) -> None:
    objects_by_id = {obj["id"]: obj for obj in objects}
    expected_edges = {
        edge["link_id"]: edge
        for edge in build_decision_stack_graph({"objects": objects, "links": links, "graph": {}})["edges"]
    }
    link_ids = set(expected_edges)
    edge_ids: set[str] = set()
    for edge in edges:
        edge_payload = _require_dict(edge, "project_state.graph.edges[]")
        _require_keys(
            edge_payload,
            ("link_id", "source_object_id", "relation", "target_object_id", "source_layer", "target_layer"),
            "project_state.graph.edges[]",
        )
        unsupported = sorted(
            set(edge_payload)
            - {"link_id", "source_object_id", "relation", "target_object_id", "source_layer", "target_layer"}
        )
        if unsupported:
            raise StateValidationError(
                "project_state.graph.edges[] contains unsupported fields: " + ", ".join(unsupported)
            )
        _require_non_empty_string(edge_payload.get("link_id"), "project_state.graph.edges[].link_id")
        _require_non_empty_string(
            edge_payload.get("source_object_id"),
            "project_state.graph.edges[].source_object_id",
        )
        _require_enum(edge_payload.get("relation"), LINK_RELATIONS, "project_state.graph.edges[].relation")
        _require_non_empty_string(
            edge_payload.get("target_object_id"),
            "project_state.graph.edges[].target_object_id",
        )
        _require_enum(edge_payload.get("source_layer"), DECISION_STACK_LAYERS, "project_state.graph.edges[].source_layer")
        _require_enum(edge_payload.get("target_layer"), DECISION_STACK_LAYERS, "project_state.graph.edges[].target_layer")
        link_id = edge_payload["link_id"]
        if link_id in edge_ids:
            raise StateValidationError(f"duplicate decision stack graph edge: {link_id}")
        edge_ids.add(link_id)
        if link_id not in link_ids:
            raise StateValidationError(f"graph edge {link_id} references missing link")
        if edge_payload["source_object_id"] not in objects_by_id:
            raise StateValidationError(f"graph edge {link_id} source_object_id references missing object")
        if edge_payload["target_object_id"] not in objects_by_id:
            raise StateValidationError(f"graph edge {link_id} target_object_id references missing object")
        if edge_payload != expected_edges[link_id]:
            raise StateValidationError(f"graph edge {link_id} does not match link projection")
    if edge_ids != link_ids:
        missing = sorted(link_ids - edge_ids)
        extra = sorted(edge_ids - link_ids)
        detail = []
        if missing:
            detail.append("missing edges for links: " + ", ".join(missing))
        if extra:
            detail.append("extra edges: " + ", ".join(extra))
        raise StateValidationError("project_state.graph.edges do not match links: " + "; ".join(detail))


def _validate_schema_relation_enums() -> None:
    schema_root = Path(__file__).resolve().parents[1] / "schemas"
    link_schema = json.loads((schema_root / "link.schema.json").read_text(encoding="utf-8"))
    project_schema = json.loads((schema_root / "project-state.schema.json").read_text(encoding="utf-8"))
    link_schema_relations = set(link_schema["properties"]["relation"]["enum"])
    project_schema_relations = set(project_schema["$defs"]["link_relation"]["enum"])
    if link_schema_relations != project_schema_relations or link_schema_relations != LINK_RELATIONS:
        raise StateValidationError("link relation enum and project-state schema relation enum must match")


def _validate_suppressed_context(context: Any, label: str) -> None:
    context_payload = _require_dict(context, label)
    _require_keys(
        context_payload,
        ("session_ids", "related_object_ids", "link_ids", "hidden_strings"),
        label,
    )
    for key in ("session_ids", "related_object_ids", "link_ids", "hidden_strings"):
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
