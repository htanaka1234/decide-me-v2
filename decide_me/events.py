from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


PLAN_STATUSES = {"action-plan", "conflicts"}
OBJECT_TYPES = {
    "objective",
    "constraint",
    "criterion",
    "option",
    "proposal",
    "decision",
    "assumption",
    "evidence",
    "risk",
    "action",
    "verification",
    "revisit_trigger",
    "artifact",
}
LINK_RELATIONS = {
    "depends_on",
    "supports",
    "challenges",
    "recommends",
    "accepts",
    "addresses",
    "verifies",
    "revisits",
    "supersedes",
    "blocked_by",
}
OBJECT_KEYS = {
    "id",
    "type",
    "title",
    "body",
    "status",
    "created_at",
    "updated_at",
    "source_event_ids",
    "metadata",
}
LINK_KEYS = {
    "id",
    "source_object_id",
    "relation",
    "target_object_id",
    "rationale",
    "created_at",
    "source_event_ids",
}
OBJECT_PATCH_KEYS = {"title", "body", "metadata"}

EVENT_TYPES = {
    "project_initialized",
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
    "plan_generated",
    "taxonomy_extended",
    "transaction_rejected",
}

REQUIRED_PAYLOAD_KEYS: dict[str, tuple[str, ...]] = {
    "project_initialized": ("project",),
    "session_created": ("session",),
    "session_resumed": ("resumed_at",),
    "object_recorded": ("object",),
    "object_updated": ("object_id", "patch"),
    "object_status_changed": ("object_id", "from_status", "to_status", "reason", "changed_at"),
    "object_linked": ("link",),
    "object_unlinked": ("link_id",),
    "session_question_asked": ("question_id", "target_object_id", "question"),
    "session_answer_recorded": ("question_id", "target_object_id", "answer"),
    "close_summary_generated": ("close_summary",),
    "session_closed": ("closed_at",),
    "plan_generated": ("session_ids", "status"),
    "taxonomy_extended": ("nodes",),
    "transaction_rejected": (
        "kept_tx_id",
        "rejected_tx_ids",
        "reason",
        "resolved_at",
        "conflict_kind",
        "conflict_summary",
    ),
}


class EventValidationError(ValueError):
    """Raised when an event envelope or payload is malformed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def new_entity_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{stamp}-{uuid4().hex[:4]}"


def new_event_id() -> str:
    return f"E-{_id_timestamp()}-{uuid4().hex[:8]}"


def new_tx_id() -> str:
    return f"T-{_id_timestamp()}-{uuid4().hex[:8]}"


def _id_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


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


def _require_timestamp(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise EventValidationError(f"{label} must be a non-empty timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EventValidationError(f"{label} must be ISO-8601/RFC3339-like") from exc


def _require_bool_or_null(value: Any, label: str) -> None:
    if value is not None and not isinstance(value, bool):
        raise EventValidationError(f"{label} must be a boolean or null")


def _require_string_or_null(value: Any, label: str, *, non_empty: bool = False) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise EventValidationError(f"{label} must be a string or null")
    if non_empty and not value.strip():
        raise EventValidationError(f"{label} must be a non-empty string or null")


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise EventValidationError(f"{label} must be a list")
    return value


def _require_id_list(value: Any, label: str) -> None:
    seen: set[str] = set()
    for item in _require_list(value, label):
        _require_non_empty_string(item, f"{label}[]")
        if item in seen:
            raise EventValidationError(f"{label} contains duplicate ids")
        seen.add(item)


def _require_source_event_ids(value: Any, label: str) -> None:
    if not isinstance(value, list) or not value:
        raise EventValidationError(f"{label} must be a non-empty list")
    seen: set[str] = set()
    for event_id in value:
        _require_non_empty_string(event_id, f"{label}[]")
        if event_id in seen:
            raise EventValidationError(f"{label} contains duplicate event ids")
        seen.add(event_id)


def _validate_object_payload(obj: dict[str, Any], label: str) -> None:
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
        label,
    )
    unsupported = sorted(set(obj) - OBJECT_KEYS)
    if unsupported:
        raise EventValidationError(f"{label} contains unsupported fields: {', '.join(unsupported)}")
    _require_non_empty_string(obj.get("id"), f"{label}.id")
    if obj.get("type") not in OBJECT_TYPES:
        allowed = ", ".join(sorted(OBJECT_TYPES))
        raise EventValidationError(f"{label}.type must be one of: {allowed}")
    _require_string_or_null(obj.get("title"), f"{label}.title", non_empty=True)
    _require_string_or_null(obj.get("body"), f"{label}.body")
    _require_non_empty_string(obj.get("status"), f"{label}.status")
    _require_timestamp(obj.get("created_at"), f"{label}.created_at")
    if obj.get("updated_at") is not None:
        _require_timestamp(obj.get("updated_at"), f"{label}.updated_at")
    _require_source_event_ids(obj.get("source_event_ids"), f"{label}.source_event_ids")
    _require_dict(obj.get("metadata"), f"{label}.metadata")


def _validate_object_patch(patch: dict[str, Any]) -> None:
    if "title" in patch:
        _require_string_or_null(patch["title"], "object_updated.payload.patch.title", non_empty=True)
    if "body" in patch:
        _require_string_or_null(patch["body"], "object_updated.payload.patch.body")
    if "metadata" in patch:
        _require_dict(patch["metadata"], "object_updated.payload.patch.metadata")


def _validate_link_payload(link: dict[str, Any], label: str) -> None:
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
        label,
    )
    unsupported = sorted(set(link) - LINK_KEYS)
    if unsupported:
        raise EventValidationError(f"{label} contains unsupported fields: {', '.join(unsupported)}")
    _require_non_empty_string(link.get("id"), f"{label}.id")
    _require_non_empty_string(link.get("source_object_id"), f"{label}.source_object_id")
    if link.get("relation") not in LINK_RELATIONS:
        allowed = ", ".join(sorted(LINK_RELATIONS))
        raise EventValidationError(f"{label}.relation must be one of: {allowed}")
    _require_non_empty_string(link.get("target_object_id"), f"{label}.target_object_id")
    _require_string_or_null(link.get("rationale"), f"{label}.rationale")
    _require_timestamp(link.get("created_at"), f"{label}.created_at")
    _require_source_event_ids(link.get("source_event_ids"), f"{label}.source_event_ids")


def prepare_payload(event_type: str, payload: dict[str, Any], project_head: str | None) -> dict[str, Any]:
    return deepcopy(payload)


def validate_payload(event_type: str, payload: dict[str, Any]) -> None:
    _require_keys(payload, REQUIRED_PAYLOAD_KEYS.get(event_type, ()), f"{event_type}.payload")

    if event_type == "project_initialized":
        project = _require_dict(payload["project"], "project_initialized.payload.project")
        _require_keys(project, ("name", "objective", "current_milestone", "stop_rule"), "project")
    elif event_type == "session_created":
        session = _require_dict(payload["session"], "session_created.payload.session")
        _require_keys(session, ("id", "started_at", "last_seen_at", "bound_context_hint"), "session")
        _require_non_empty_string(session.get("id"), "session_created.payload.session.id")
        _require_timestamp(session.get("started_at"), "session_created.payload.session.started_at")
        _require_timestamp(session.get("last_seen_at"), "session_created.payload.session.last_seen_at")
    elif event_type == "session_resumed":
        _require_timestamp(payload.get("resumed_at"), "session_resumed.payload.resumed_at")
    elif event_type == "object_recorded":
        _validate_object_payload(
            _require_dict(payload["object"], "object_recorded.payload.object"),
            "object_recorded.payload.object",
        )
    elif event_type == "object_updated":
        _require_non_empty_string(payload.get("object_id"), "object_updated.payload.object_id")
        patch = _require_dict(payload["patch"], "object_updated.payload.patch")
        unknown = sorted(set(patch) - OBJECT_PATCH_KEYS)
        if unknown:
            raise EventValidationError(
                f"object_updated.payload.patch contains unsupported fields: {', '.join(unknown)}"
            )
        if not patch:
            raise EventValidationError("object_updated.payload.patch must not be empty")
        _validate_object_patch(patch)
    elif event_type == "object_status_changed":
        _require_non_empty_string(payload.get("object_id"), "object_status_changed.payload.object_id")
        _require_non_empty_string(payload.get("from_status"), "object_status_changed.payload.from_status")
        _require_non_empty_string(payload.get("to_status"), "object_status_changed.payload.to_status")
        _require_non_empty_string(payload.get("reason"), "object_status_changed.payload.reason")
        _require_timestamp(payload.get("changed_at"), "object_status_changed.payload.changed_at")
    elif event_type == "object_linked":
        _validate_link_payload(
            _require_dict(payload["link"], "object_linked.payload.link"),
            "object_linked.payload.link",
        )
    elif event_type == "object_unlinked":
        _require_non_empty_string(payload.get("link_id"), "object_unlinked.payload.link_id")
    elif event_type == "session_question_asked":
        _require_non_empty_string(payload.get("question_id"), "session_question_asked.payload.question_id")
        _require_non_empty_string(payload.get("target_object_id"), "session_question_asked.payload.target_object_id")
        _require_non_empty_string(payload.get("question"), "session_question_asked.payload.question")
    elif event_type == "session_answer_recorded":
        _require_non_empty_string(payload.get("target_object_id"), "session_answer_recorded.payload.target_object_id")
        answer = _require_dict(payload["answer"], "session_answer_recorded.payload.answer")
        _require_keys(answer, ("summary", "answered_at", "answered_via"), "session_answer_recorded.payload.answer")
        _require_non_empty_string(answer.get("summary"), "session_answer_recorded.payload.answer.summary")
        _require_timestamp(answer.get("answered_at"), "session_answer_recorded.payload.answer.answered_at")
        _require_non_empty_string(answer.get("answered_via"), "session_answer_recorded.payload.answer.answered_via")
        question_id = payload.get("question_id")
        if question_id is None:
            if answer.get("answered_via") != "defer":
                raise EventValidationError(
                    "session_answer_recorded.payload.question_id may be null only when answered_via is defer"
                )
        else:
            _require_non_empty_string(question_id, "session_answer_recorded.payload.question_id")
    elif event_type == "session_closed":
        _require_timestamp(payload.get("closed_at"), "session_closed.payload.closed_at")
    elif event_type == "close_summary_generated":
        close_summary = _require_dict(
            payload["close_summary"], "close_summary_generated.payload.close_summary"
        )
        _require_keys(
            close_summary,
            (
                "work_item",
                "readiness",
                "object_ids",
                "link_ids",
                "generated_at",
            ),
            "close_summary",
        )
        unsupported = sorted(
            set(close_summary)
            - {"work_item", "readiness", "object_ids", "link_ids", "generated_at"}
        )
        if unsupported:
            raise EventValidationError(
                "close_summary contains unsupported fields: " + ", ".join(unsupported)
            )
        work_item = _require_dict(
            close_summary["work_item"],
            "close_summary_generated.payload.close_summary.work_item",
        )
        _require_keys(work_item, ("title", "statement", "objective_object_id"), "close_summary.work_item")
        unsupported_work_item = sorted(set(work_item) - {"title", "statement", "objective_object_id"})
        if unsupported_work_item:
            raise EventValidationError(
                "close_summary.work_item contains unsupported fields: "
                + ", ".join(unsupported_work_item)
            )
        _require_string_or_null(work_item.get("title"), "close_summary.work_item.title")
        _require_string_or_null(work_item.get("statement"), "close_summary.work_item.statement")
        _require_string_or_null(
            work_item.get("objective_object_id"),
            "close_summary.work_item.objective_object_id",
            non_empty=True,
        )
        if close_summary.get("readiness") not in {"ready", "conditional", "blocked"}:
            raise EventValidationError("close_summary.readiness must be ready, conditional, or blocked")
        object_ids = _require_dict(
            close_summary["object_ids"],
            "close_summary_generated.payload.close_summary.object_ids",
        )
        object_id_keys = (
            "decisions",
            "accepted_decisions",
            "deferred_decisions",
            "blockers",
            "risks",
            "actions",
            "evidence",
            "verifications",
            "revisit_triggers",
        )
        _require_keys(object_ids, object_id_keys, "close_summary.object_ids")
        unsupported_object_id_keys = sorted(set(object_ids) - set(object_id_keys))
        if unsupported_object_id_keys:
            raise EventValidationError(
                "close_summary.object_ids contains unsupported fields: "
                + ", ".join(unsupported_object_id_keys)
            )
        for key in object_id_keys:
            _require_id_list(object_ids[key], f"close_summary.object_ids.{key}")
        _require_id_list(close_summary["link_ids"], "close_summary.link_ids")
        _require_timestamp(
            close_summary.get("generated_at"),
            "close_summary_generated.payload.close_summary.generated_at",
        )
    elif event_type == "taxonomy_extended":
        nodes = payload["nodes"]
        if not isinstance(nodes, list):
            raise EventValidationError("taxonomy_extended.payload.nodes must be a list")
        for node in nodes:
            node_payload = _require_dict(node, "taxonomy_extended.payload.nodes[]")
            if "created_at" in node_payload:
                _require_timestamp(
                    node_payload.get("created_at"),
                    "taxonomy_extended.payload.nodes[].created_at",
                )
            if "updated_at" in node_payload:
                _require_timestamp(
                    node_payload.get("updated_at"),
                    "taxonomy_extended.payload.nodes[].updated_at",
                )
    elif event_type == "plan_generated":
        session_ids = payload["session_ids"]
        if not isinstance(session_ids, list) or not session_ids:
            raise EventValidationError("plan_generated.payload.session_ids must be a non-empty list")
        for session_id in session_ids:
            _require_non_empty_string(session_id, "plan_generated.payload.session_ids[]")
        if payload["status"] not in PLAN_STATUSES:
            raise EventValidationError("plan_generated.payload.status must be action-plan or conflicts")
    elif event_type == "transaction_rejected":
        for key in ("kept_tx_id", "reason", "conflict_kind", "conflict_summary"):
            _require_non_empty_string(payload.get(key), f"transaction_rejected.payload.{key}")
        _require_timestamp(payload.get("resolved_at"), "transaction_rejected.payload.resolved_at")
        rejected_tx_ids = payload["rejected_tx_ids"]
        if not isinstance(rejected_tx_ids, list) or not rejected_tx_ids:
            raise EventValidationError("transaction_rejected.payload.rejected_tx_ids must be a non-empty list")
        seen: set[str] = set()
        for rejected_tx_id in rejected_tx_ids:
            _require_non_empty_string(rejected_tx_id, "transaction_rejected.payload.rejected_tx_ids[]")
            if rejected_tx_id in seen:
                raise EventValidationError(
                    f"transaction_rejected.payload.rejected_tx_ids contains duplicate tx_id: {rejected_tx_id}"
                )
            seen.add(rejected_tx_id)
        if payload["kept_tx_id"] in seen:
            raise EventValidationError("transaction_rejected kept_tx_id must not be rejected")


def validate_event(event: dict[str, Any]) -> None:
    envelope_keys = ("event_id", "tx_id", "tx_index", "tx_size", "ts", "session_id", "event_type", "payload")
    _require_keys(event, envelope_keys, "event")
    unsupported = sorted(set(event) - set(envelope_keys))
    if unsupported:
        raise EventValidationError(f"event contains unsupported fields: {', '.join(unsupported)}")
    _require_non_empty_string(event["event_id"], "event.event_id")
    _require_non_empty_string(event["tx_id"], "event.tx_id")
    if not isinstance(event["tx_index"], int) or event["tx_index"] < 1:
        raise EventValidationError("event.tx_index must be a positive integer")
    if not isinstance(event["tx_size"], int) or event["tx_size"] < 1:
        raise EventValidationError("event.tx_size must be a positive integer")
    if event["tx_index"] > event["tx_size"]:
        raise EventValidationError("event.tx_index must not exceed event.tx_size")
    _require_timestamp(event["ts"], "event.ts")
    _require_non_empty_string(event["session_id"], "event.session_id")
    if event["event_type"] not in EVENT_TYPES:
        raise EventValidationError(f"unsupported event_type: {event['event_type']}")
    payload = _require_dict(event["payload"], "event.payload")
    validate_payload(event["event_type"], payload)


def build_event(
    *,
    tx_id: str,
    tx_index: int,
    tx_size: int,
    session_id: str,
    event_type: str,
    payload: dict[str, Any],
    timestamp: str | None = None,
    event_id: str | None = None,
    project_head: str | None = None,
) -> dict[str, Any]:
    ts = timestamp or utc_now()
    prepared = prepare_payload(event_type, payload, project_head)
    event = {
        "event_id": event_id or new_event_id(),
        "tx_id": tx_id,
        "tx_index": tx_index,
        "tx_size": tx_size,
        "ts": ts,
        "session_id": session_id,
        "event_type": event_type,
        "payload": prepared,
    }
    validate_event(event)
    return event
