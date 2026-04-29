from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from decide_me.domains import DomainRegistry, load_domain_registry
from decide_me.events import new_event_id, utc_now
from decide_me.safety_gate import SAFETY_APPROVAL_ARTIFACT_TYPE, evaluate_safety_gate
from decide_me.store import load_runtime, runtime_paths, transact


SAFETY_APPROVAL_SCHEMA_VERSION = 1


def approve_safety_gate(
    ai_dir: str,
    session_id: str,
    object_id: str,
    *,
    approved_by: str,
    reason: str,
    expires_at: str | None = None,
) -> dict[str, Any]:
    approved_by = _require_text(approved_by, "approved_by")
    reason = _require_text(reason, "reason")
    if expires_at is not None:
        _parse_timestamp(expires_at, "expires_at")

    outcome: dict[str, Any] = {}
    domain_registry = load_domain_registry(ai_dir)

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        _require_mutable_session(bundle, session_id)
        now = utc_now()
        result = evaluate_safety_gate(
            bundle["project_state"],
            object_id,
            now=now,
            domain_registry=domain_registry,
        )
        outcome["gate_before"] = result
        if result["gate_status"] == "blocked":
            raise ValueError(_blocked_message(result))
        if result["approval_satisfied"]:
            outcome["approval_artifact_ids"] = result["approval_artifact_ids"]
            return []
        if not result["approval_required"]:
            raise ValueError(f"safety gate for {object_id} does not require approval")

        outcome["approval_artifact_ids"] = [approval_artifact_id(object_id, result["gate_digest"])]
        specs = build_safety_approval_event_specs(
            bundle["project_state"],
            session_id,
            object_id,
            gate_result=result,
            approved_by=approved_by,
            reason=reason,
            approved_at=now,
            expires_at=expires_at,
            domain_registry=domain_registry,
        )
        return specs

    events, bundle = transact(ai_dir, builder)
    gate_after = evaluate_safety_gate(bundle["project_state"], object_id, domain_registry=domain_registry)
    return {
        "object_id": object_id,
        "status": "already_approved" if not events else "approved",
        "approval_artifact_ids": outcome.get("approval_artifact_ids") or gate_after["approval_artifact_ids"],
        "gate_before": outcome.get("gate_before"),
        "gate_after": gate_after,
        "event_ids": [event["event_id"] for event in events],
    }


def build_safety_approval_event_specs(
    project_state: dict[str, Any],
    session_id: str,
    object_id: str,
    *,
    gate_result: dict[str, Any] | None = None,
    approved_by: str,
    reason: str,
    approved_at: str,
    expires_at: str | None = None,
    domain_registry: DomainRegistry | None = None,
) -> list[dict[str, Any]]:
    result = gate_result or evaluate_safety_gate(
        project_state,
        object_id,
        now=approved_at,
        domain_registry=domain_registry,
    )
    if result["gate_status"] == "blocked":
        raise ValueError(_blocked_message(result))
    if result["approval_satisfied"] or not result["approval_required"]:
        return []
    _require_future_expiry(expires_at, approved_at)

    artifact_id = approval_artifact_id(object_id, result["gate_digest"])
    link_id = approval_link_id(artifact_id, object_id)
    existing_artifact = _object_by_id(project_state, artifact_id)
    existing_link = _link_by_id(project_state, link_id)
    _validate_existing_approval_artifact(existing_artifact, artifact_id, object_id, result["gate_digest"])
    _validate_existing_approval_link(existing_link, link_id, artifact_id, object_id)

    object_event_id = new_event_id()
    update_event_id = new_event_id()
    status_event_id = new_event_id()
    link_event_id = new_event_id()
    metadata = _approval_metadata(
        object_id,
        result,
        approved_by=approved_by,
        reason=reason,
        approved_at=approved_at,
        expires_at=expires_at,
    )
    specs = []
    if existing_artifact is None:
        specs.append(
            {
                "event_id": object_event_id,
                "session_id": session_id,
                "event_type": "object_recorded",
                "payload": {
                    "object": _approval_artifact(
                        artifact_id,
                        object_id,
                        reason=reason,
                        created_at=approved_at,
                        event_id=object_event_id,
                        metadata=metadata,
                    )
                },
            }
        )
    else:
        specs.append(
            {
                "event_id": update_event_id,
                "session_id": session_id,
                "event_type": "object_updated",
                "payload": {
                    "object_id": artifact_id,
                    "patch": {
                        "body": reason,
                        "metadata": metadata,
                    },
                },
            }
        )
        if existing_artifact.get("status") != "active":
            specs.append(
                {
                    "event_id": status_event_id,
                    "session_id": session_id,
                    "event_type": "object_status_changed",
                    "payload": {
                        "object_id": artifact_id,
                        "from_status": existing_artifact["status"],
                        "to_status": "active",
                        "reason": "Refreshing safety approval for the current gate digest.",
                        "changed_at": approved_at,
                    },
                }
            )
    if existing_link is None:
        specs.append(
            {
                "event_id": link_event_id,
                "session_id": session_id,
                "event_type": "object_linked",
                "payload": {
                    "link": _approval_link(
                        link_id,
                        artifact_id,
                        object_id,
                        gate_digest=result["gate_digest"],
                        created_at=approved_at,
                        event_id=link_event_id,
                    )
                },
            }
        )
    return specs


def show_safety_approvals(
    ai_dir: str,
    *,
    object_id: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    bundle = load_runtime(runtime_paths(ai_dir))
    return build_safety_approval_report(
        bundle["project_state"],
        object_id=object_id,
        now=now,
        domain_registry=load_domain_registry(ai_dir),
    )


def build_safety_approval_report(
    project_state: dict[str, Any],
    *,
    object_id: str | None = None,
    now: str | None = None,
    domain_registry: DomainRegistry | None = None,
) -> dict[str, Any]:
    as_of = now or project_state.get("state", {}).get("updated_at") or utc_now()
    reference = _parse_timestamp(as_of, "as_of")
    active_gate_digest = None
    active_approval_artifact_ids: list[str] = []
    if object_id is not None:
        gate = evaluate_safety_gate(
            project_state,
            object_id,
            now=as_of,
            domain_registry=domain_registry,
        )
        active_gate_digest = gate["gate_digest"]
        active_approval_artifact_ids = gate["approval_artifact_ids"]

    approvals = []
    address_links = _address_links(project_state)
    for obj in project_state.get("objects", []):
        if obj.get("type") != "artifact":
            continue
        metadata = obj.get("metadata", {})
        if metadata.get("artifact_type") != SAFETY_APPROVAL_ARTIFACT_TYPE:
            continue
        if object_id is not None and metadata.get("target_object_id") != object_id:
            continue
        expires_at = metadata.get("expires_at")
        expired = bool(expires_at and _parse_timestamp(expires_at, f"approval {obj['id']}.expires_at") < reference)
        approvals.append(
            {
                "artifact_id": obj["id"],
                "status": obj.get("status"),
                "target_object_id": metadata.get("target_object_id"),
                "gate_digest": metadata.get("gate_digest"),
                "approval_threshold": metadata.get("approval_threshold"),
                "approved_by": metadata.get("approved_by"),
                "approved_at": metadata.get("approved_at"),
                "reason": metadata.get("reason"),
                "expires_at": expires_at,
                "is_expired": expired,
                "is_current": obj["id"] in active_approval_artifact_ids,
                "addresses_link_ids": sorted(address_links.get(obj["id"], [])),
            }
        )

    state = project_state.get("state", {})
    return {
        "schema_version": SAFETY_APPROVAL_SCHEMA_VERSION,
        "project_head": state.get("project_head"),
        "generated_at": state.get("updated_at"),
        "as_of": as_of,
        "object_id": object_id,
        "active_gate_digest": active_gate_digest,
        "approvals": sorted(approvals, key=lambda item: item["artifact_id"]),
    }


def approval_artifact_id(object_id: str, gate_digest: str) -> str:
    return f"ART-approval-{_safe_id_part(object_id)}-{gate_digest.removeprefix('SG-')}"


def approval_link_id(artifact_id: str, object_id: str) -> str:
    return f"L-{artifact_id}-addresses-{_safe_id_part(object_id)}"


def _blocked_message(result: dict[str, Any]) -> str:
    return (
        f"safety gate for {result['object_id']} is blocked; "
        f"gate_status={result['gate_status']}; "
        f"blocking_reasons={result['blocking_reasons']}; "
        f"approval_reasons={result['approval_reasons']}; "
        f"gate_digest={result['gate_digest']}"
    )


def _require_mutable_session(bundle: dict[str, Any], session_id: str) -> dict[str, Any]:
    try:
        session = bundle["sessions"][session_id]
    except KeyError as exc:
        raise ValueError(f"unknown session: {session_id}") from exc
    if session["session"]["lifecycle"]["status"] == "closed":
        raise ValueError(f"session {session_id} is closed")
    return session


def _require_future_expiry(expires_at: str | None, approved_at: str) -> None:
    if expires_at is None:
        return
    expires = _parse_timestamp(expires_at, "expires_at")
    approved = _parse_timestamp(approved_at, "approved_at")
    try:
        expired_on_arrival = expires <= approved
    except TypeError as exc:
        raise ValueError("expires_at and approved_at must use comparable timezone information") from exc
    if expired_on_arrival:
        raise ValueError("expires_at must be after approved_at")


def _approval_metadata(
    object_id: str,
    result: dict[str, Any],
    *,
    approved_by: str,
    reason: str,
    approved_at: str,
    expires_at: str | None,
) -> dict[str, Any]:
    return {
        "artifact_type": SAFETY_APPROVAL_ARTIFACT_TYPE,
        "target_object_id": object_id,
        "gate_digest": result["gate_digest"],
        "approval_threshold": result["approval_threshold"],
        "approved_by": approved_by,
        "approved_at": approved_at,
        "reason": reason,
        "expires_at": expires_at,
    }


def _approval_artifact(
    artifact_id: str,
    object_id: str,
    *,
    reason: str,
    created_at: str,
    event_id: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": artifact_id,
        "type": "artifact",
        "title": f"Safety approval for {object_id}",
        "body": reason,
        "status": "active",
        "created_at": created_at,
        "updated_at": None,
        "source_event_ids": [event_id],
        "metadata": metadata,
    }


def _approval_link(
    link_id: str,
    artifact_id: str,
    object_id: str,
    *,
    gate_digest: str,
    created_at: str,
    event_id: str,
) -> dict[str, Any]:
    return {
        "id": link_id,
        "source_object_id": artifact_id,
        "relation": "addresses",
        "target_object_id": object_id,
        "rationale": f"Safety approval for gate digest {gate_digest}",
        "created_at": created_at,
        "source_event_ids": [event_id],
    }


def _validate_existing_approval_artifact(
    artifact: dict[str, Any] | None,
    artifact_id: str,
    object_id: str,
    gate_digest: str,
) -> None:
    if artifact is None:
        return
    metadata = artifact.get("metadata", {})
    if (
        artifact.get("type") != "artifact"
        or metadata.get("artifact_type") != SAFETY_APPROVAL_ARTIFACT_TYPE
        or metadata.get("target_object_id") != object_id
        or metadata.get("gate_digest") != gate_digest
    ):
        raise ValueError(f"approval artifact id collision: {artifact_id}")


def _validate_existing_approval_link(
    link: dict[str, Any] | None,
    link_id: str,
    artifact_id: str,
    object_id: str,
) -> None:
    if link is None:
        return
    if (
        link.get("source_object_id") != artifact_id
        or link.get("relation") != "addresses"
        or link.get("target_object_id") != object_id
    ):
        raise ValueError(f"approval link id collision: {link_id}")


def _object_by_id(project_state: dict[str, Any], object_id: str) -> dict[str, Any] | None:
    for obj in project_state.get("objects", []):
        if obj.get("id") == object_id:
            return obj
    return None


def _link_by_id(project_state: dict[str, Any], link_id: str) -> dict[str, Any] | None:
    for link in project_state.get("links", []):
        if link.get("id") == link_id:
            return link
    return None


def _address_links(project_state: dict[str, Any]) -> dict[str, list[str]]:
    links: dict[str, list[str]] = {}
    for link in project_state.get("links", []):
        if link.get("relation") == "addresses":
            links.setdefault(link["source_object_id"], []).append(link["id"])
    return links


def _safe_id_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9-]+", "-", value).strip("-") or "object"


def _require_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _parse_timestamp(value: str, label: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{label} must be ISO-8601/RFC3339-like") from exc
