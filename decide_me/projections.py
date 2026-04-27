from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from decide_me.suppression import apply_semantic_suppression_to_session, merge_suppressed_contexts
from decide_me.taxonomy import default_taxonomy_state, stable_unique


OPEN_DECISION_STATUSES = {"unresolved", "proposed", "rejected", "blocked"}
IDLE_AFTER = timedelta(hours=12)
STALE_AFTER = timedelta(days=7)
PROJECT_STATE_SCHEMA_VERSION = 10
SESSION_STATE_SCHEMA_VERSION = 9
PROJECTION_SCHEMA_VERSION = PROJECT_STATE_SCHEMA_VERSION

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


def default_project_state() -> dict[str, Any]:
    return {
        "schema_version": PROJECT_STATE_SCHEMA_VERSION,
        "project": {
            "name": None,
            "objective": None,
            "current_milestone": None,
            "stop_rule": None,
        },
        "state": {"project_head": None, "event_count": 0, "updated_at": None, "last_event_id": None},
        "protocol": {
            "plain_ok_scope": "same-session-active-proposal-only",
            "proposal_expiry_rules": [
                "project-head-changed",
                "session-boundary",
                "superseded-proposal",
                "decision-invalidated",
                "session-closed",
            ],
            "close_policy": "generate-close-summary-on-close",
        },
        "sessions_index": {},
        "counts": {
            "object_total": 0,
            "link_total": 0,
            "by_type": {},
            "by_status": {},
            "by_relation": {},
        },
        "objects": [],
        "links": [],
        "graph": {
            "nodes": [],
            "edges": [],
            "resolved_conflicts": [],
            "inferred_candidates": [],
        },
    }


def default_close_summary() -> dict[str, Any]:
    return {
        "work_item_title": None,
        "work_item_statement": None,
        "goal": None,
        "readiness": "ready",
        "accepted_decisions": [],
        "deferred_decisions": [],
        "unresolved_blockers": [],
        "unresolved_risks": [],
        "candidate_workstreams": [],
        "candidate_action_slices": [],
        "evidence_refs": [],
        "generated_at": None,
    }


def default_session_state(
    session_id: str, started_at: str, bound_context_hint: str | None = None
) -> dict[str, Any]:
    return {
        "schema_version": SESSION_STATE_SCHEMA_VERSION,
        "session": {
            "id": session_id,
            "started_at": started_at,
            "last_seen_at": started_at,
            "bound_context_hint": bound_context_hint,
            "decision_ids": [],
            "lifecycle": {"status": "active", "closed_at": None},
        },
        "summary": {
            "latest_summary": None,
            "current_question_preview": None,
            "active_decision_id": None,
        },
        "classification": {
            "domain": None,
            "abstraction_level": None,
            "assigned_tags": [],
            "search_terms": [],
            "source_refs": [],
            "updated_at": None,
        },
        "close_summary": default_close_summary(),
        "working_state": {
            "current_question_id": None,
            "current_question": None,
            "active_proposal": empty_active_proposal(),
            "last_seen_project_head": None,
        },
    }


def empty_active_proposal() -> dict[str, Any]:
    return {
        "proposal_id": None,
        "origin_session_id": None,
        "target_type": None,
        "target_id": None,
        "recommendation_version": None,
        "based_on_project_head": None,
        "is_active": False,
        "activated_at": None,
        "inactive_reason": None,
        "question_id": None,
        "question": None,
        "recommendation": None,
        "why": None,
        "if_not": None,
    }


def effective_session_status(session_state: dict[str, Any], now: datetime | None = None) -> str:
    status = session_state.get("session", {}).get("lifecycle", {}).get("status")
    if status == "closed":
        return "closed"

    last_seen_at = session_state.get("session", {}).get("last_seen_at")
    if not last_seen_at:
        return status or "active"

    reference = now or datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(last_seen_at.replace("Z", "+00:00"))
    age = reference - parsed
    if age >= STALE_AFTER:
        return "stale"
    if age >= IDLE_AFTER:
        return "idle"
    return "active"


def decision_is_invalidated(decision: dict[str, Any]) -> bool:
    return decision.get("status") == "invalidated"


def visible_decision_ids(project_state: dict[str, Any]) -> set[str]:
    return {
        item["id"]
        for item in project_state.get("objects", [])
        if item.get("type") == "decision" and not decision_is_invalidated(item)
    }


def project_heads_by_event_id(events: list[dict[str, Any]]) -> dict[str, str]:
    heads: dict[str, str] = {}
    previous_head: str | None = None
    for event in events:
        previous_head = project_head_after_event(previous_head, event)
        heads[event["event_id"]] = previous_head
    return heads


def project_head_after_event(previous_head: str | None, event: dict[str, Any]) -> str:
    material = json.dumps(
        {
            "previous_project_head": previous_head,
            "event": _normalized_project_head_event(event),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _project_head_hash_material(event: dict[str, Any]) -> str:
    return json.dumps(
        _normalized_project_head_event(event),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _normalized_project_head_event(event: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(event)


def rebuild_projections(events: list[dict[str, Any]]) -> dict[str, Any]:
    initial_timestamp = events[0]["ts"] if events else None
    project_state = default_project_state()
    taxonomy_state = default_taxonomy_state(now=initial_timestamp)
    sessions: dict[str, dict[str, Any]] = {}
    heads = project_heads_by_event_id(events)

    for event_count, event in enumerate(events, start=1):
        apply_event(
            project_state,
            taxonomy_state,
            sessions,
            event,
            project_head_after=heads[event["event_id"]],
            event_count=event_count,
        )

    bundle = {
        "project_state": project_state,
        "taxonomy_state": taxonomy_state,
        "sessions": {session_id: sessions[session_id] for session_id in sorted(sessions)},
    }
    _finalize_project_state(bundle)
    return {
        "project_state": project_state,
        "taxonomy_state": taxonomy_state,
        "sessions": bundle["sessions"],
    }


def apply_events_to_bundle(bundle: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    project_state = bundle["project_state"]
    taxonomy_state = bundle["taxonomy_state"]
    sessions = bundle["sessions"]
    previous_head = project_state["state"].get("project_head")
    event_count = int(project_state["state"].get("event_count") or 0)

    for event in events:
        previous_head = project_head_after_event(previous_head, event)
        event_count += 1
        apply_event(
            project_state,
            taxonomy_state,
            sessions,
            event,
            project_head_after=previous_head,
            event_count=event_count,
        )

    normalized_sessions = {session_id: sessions[session_id] for session_id in sorted(sessions)}
    bundle["sessions"] = normalized_sessions
    _finalize_project_state(bundle)
    return bundle


def apply_event(
    project_state: dict[str, Any],
    taxonomy_state: dict[str, Any],
    sessions: dict[str, dict[str, Any]],
    event: dict[str, Any],
    *,
    project_head_after: str,
    event_count: int,
) -> None:
    event_type = event["event_type"]
    payload = event["payload"]
    session_id = event["session_id"]
    ts = event["ts"]

    if event_type == "project_initialized":
        project_state["project"] = deepcopy(payload["project"])
        if payload.get("protocol"):
            project_state["protocol"] = deepcopy(payload["protocol"])
        _ensure_object(
            project_state,
            object_id="O-project-objective",
            object_type="objective",
            title=payload["project"]["current_milestone"],
            body=payload["project"]["objective"],
            status="active",
            timestamp=ts,
            event_id=event["event_id"],
            metadata={
                "project_name": payload["project"]["name"],
                "stop_rule": payload["project"]["stop_rule"],
            },
        )
    elif event_type == "session_created":
        session_payload = payload["session"]
        sessions[session_payload["id"]] = default_session_state(
            session_payload["id"],
            session_payload["started_at"],
            session_payload.get("bound_context_hint"),
        )
        sessions[session_payload["id"]]["session"]["last_seen_at"] = session_payload["last_seen_at"]
    elif event_type == "session_resumed":
        session = sessions[session_id]
        active = session["working_state"]["active_proposal"]
        session["session"]["last_seen_at"] = payload["resumed_at"]
        session["session"]["lifecycle"]["status"] = "active"
        _deactivate_proposal(session, "session-boundary")
    elif event_type == "object_recorded":
        obj = _record_object(project_state, payload["object"], event["event_id"])
        _maybe_activate_proposal_from_object(sessions, session_id, obj, project_head_after, ts)
        _touch_session_for_object(sessions, session_id, project_state, obj["id"], ts, project_head_after)
    elif event_type == "object_updated":
        obj = _require_object(project_state, payload["object_id"])
        _deep_update_object(obj, payload["patch"])
        _touch_object(obj, ts, event["event_id"])
        _touch_session_for_object(sessions, session_id, project_state, obj["id"], ts, project_head_after)
    elif event_type == "object_status_changed":
        obj = _require_object(project_state, payload["object_id"])
        if obj["status"] != payload["from_status"]:
            raise ValueError(
                f"object_status_changed expected {obj['id']} status "
                f"{payload['from_status']}, found {obj['status']}"
            )
        status_ts = payload["changed_at"]
        obj["status"] = payload["to_status"]
        _touch_object(obj, status_ts, event["event_id"])
        if (
            obj.get("type") == "decision"
            and payload["to_status"] in {"accepted", "rejected", "deferred", "resolved-by-evidence", "invalidated"}
            and session_id in sessions
            and sessions[session_id]["summary"].get("active_decision_id") == obj["id"]
        ):
            _clear_question_state(sessions[session_id], None)
        _touch_session_for_object(sessions, session_id, project_state, obj["id"], status_ts, project_head_after)
    elif event_type == "object_linked":
        _record_link(project_state, payload["link"], event["event_id"])
        _touch_session(
            sessions,
            session_id,
            ts,
            None,
            project_head_after,
            add_decision=False,
        )
    elif event_type == "object_unlinked":
        _remove_link(project_state, payload["link_id"])
        _touch_session(
            sessions,
            session_id,
            ts,
            None,
            project_head_after,
            add_decision=False,
        )
    elif event_type == "session_question_asked":
        target = _require_object(project_state, payload["target_object_id"])
        session = sessions[session_id]
        session["working_state"]["current_question_id"] = payload["question_id"]
        session["working_state"]["current_question"] = payload["question"]
        session["summary"]["current_question_preview"] = payload["question"]
        session["summary"]["active_decision_id"] = payload["target_object_id"] if target.get("type") == "decision" else None
        target["metadata"]["question"] = payload["question"]
        _touch_object(target, ts, event["event_id"])
        _touch_session_for_object(sessions, session_id, project_state, target["id"], ts, project_head_after)
    elif event_type == "session_answer_recorded":
        target = _require_object(project_state, payload["target_object_id"])
        answers = target["metadata"].setdefault("answers", [])
        answers.append(deepcopy(payload["answer"]))
        _touch_object(target, ts, event["event_id"])
        _clear_question_state(sessions[session_id], payload["answer"]["summary"])
        _touch_session_for_object(sessions, session_id, project_state, target["id"], ts, project_head_after)
    elif event_type == "close_summary_generated":
        session = sessions[session_id]
        session["close_summary"] = deepcopy(payload["close_summary"])
        session["summary"]["latest_summary"] = payload["close_summary"]["work_item_title"]
        _project_close_summary_objects(project_state, session_id, payload["close_summary"], ts, event["event_id"])
        _touch_session(
            sessions,
            session_id,
            ts,
            session["summary"].get("active_decision_id"),
            project_head_after,
        )
    elif event_type == "session_closed":
        session = sessions[session_id]
        active = session["working_state"]["active_proposal"]
        session["session"]["lifecycle"]["status"] = "closed"
        session["session"]["lifecycle"]["closed_at"] = payload["closed_at"]
        _clear_question_state(session, "session-closed")
        _touch_session(
            sessions,
            session_id,
            ts,
            session["summary"].get("active_decision_id"),
            project_head_after,
        )
    elif event_type == "taxonomy_extended":
        for node in payload["nodes"]:
            _upsert_taxonomy_node(taxonomy_state, node)
    elif event_type == "plan_generated":
        pass
    project_state["state"] = {
        "project_head": project_head_after,
        "event_count": event_count,
        "updated_at": ts,
        "last_event_id": event["event_id"],
    }
    taxonomy_state["state"] = {"updated_at": ts, "last_event_id": event["event_id"]}


def _object_exists(project_state: dict[str, Any], object_id: str) -> bool:
    return _find_object(project_state, object_id) is not None


def _find_object(project_state: dict[str, Any], object_id: str) -> dict[str, Any] | None:
    for item in project_state["objects"]:
        if item["id"] == object_id:
            return item
    return None


def _require_object(project_state: dict[str, Any], object_id: str) -> dict[str, Any]:
    obj = _find_object(project_state, object_id)
    if obj is None:
        raise ValueError(f"unknown object: {object_id}")
    return obj


def _record_object(project_state: dict[str, Any], payload: dict[str, Any], event_id: str) -> dict[str, Any]:
    object_id = payload["id"]
    if _find_object(project_state, object_id) is not None:
        raise ValueError(f"duplicate object id: {object_id}")
    obj = deepcopy(payload)
    obj["source_event_ids"] = stable_unique([*obj.get("source_event_ids", []), event_id])
    project_state["objects"].append(obj)
    project_state["objects"].sort(key=lambda candidate: candidate["id"])
    return obj


def _deep_update_object(obj: dict[str, Any], patch: dict[str, Any]) -> None:
    for key in ("title", "body"):
        if key in patch:
            obj[key] = deepcopy(patch[key])
    if "metadata" in patch:
        _deep_update(obj["metadata"], patch["metadata"])


def _ensure_object(
    project_state: dict[str, Any],
    *,
    object_id: str,
    object_type: str,
    title: str | None,
    body: str | None,
    status: str,
    timestamp: str,
    event_id: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing = _find_object(project_state, object_id)
    if existing is not None:
        if title is not None:
            existing["title"] = title
        if body is not None:
            existing["body"] = body
        existing["status"] = status
        if metadata:
            _deep_update(existing["metadata"], metadata)
        _touch_object(existing, timestamp, event_id)
        return existing

    item = {
        "id": object_id,
        "type": object_type,
        "title": title,
        "body": body,
        "status": status,
        "created_at": timestamp,
        "updated_at": None,
        "source_event_ids": [event_id],
        "metadata": deepcopy(metadata or {}),
    }
    project_state["objects"].append(item)
    project_state["objects"].sort(key=lambda candidate: candidate["id"])
    return item


def _touch_object(item: dict[str, Any], timestamp: str, event_id: str) -> None:
    item["updated_at"] = timestamp
    item["source_event_ids"] = stable_unique([*item.get("source_event_ids", []), event_id])


def _ensure_link(
    project_state: dict[str, Any],
    *,
    link_id: str,
    source_object_id: str,
    relation: str,
    target_object_id: str,
    rationale: str | None,
    timestamp: str,
    event_id: str,
) -> dict[str, Any] | None:
    if not _object_exists(project_state, source_object_id) or not _object_exists(project_state, target_object_id):
        return None
    for link in project_state["links"]:
        if link["id"] == link_id:
            link["source_event_ids"] = stable_unique([*link.get("source_event_ids", []), event_id])
            return link
    link = {
        "id": link_id,
        "source_object_id": source_object_id,
        "relation": relation,
        "target_object_id": target_object_id,
        "rationale": rationale,
        "created_at": timestamp,
        "source_event_ids": [event_id],
    }
    project_state["links"].append(link)
    project_state["links"].sort(key=lambda candidate: candidate["id"])
    return link


def _record_link(project_state: dict[str, Any], payload: dict[str, Any], event_id: str) -> dict[str, Any]:
    link_id = payload["id"]
    if _find_link(project_state, link_id) is not None:
        raise ValueError(f"duplicate link id: {link_id}")
    if not _object_exists(project_state, payload["source_object_id"]):
        raise ValueError(f"link {link_id} source_object_id references missing object")
    if not _object_exists(project_state, payload["target_object_id"]):
        raise ValueError(f"link {link_id} target_object_id references missing object")
    link = deepcopy(payload)
    link["source_event_ids"] = stable_unique([*link.get("source_event_ids", []), event_id])
    project_state["links"].append(link)
    project_state["links"].sort(key=lambda candidate: candidate["id"])
    return link


def _find_link(project_state: dict[str, Any], link_id: str) -> dict[str, Any] | None:
    for link in project_state["links"]:
        if link["id"] == link_id:
            return link
    return None


def _remove_link(project_state: dict[str, Any], link_id: str) -> None:
    before = len(project_state["links"])
    project_state["links"] = [link for link in project_state["links"] if link["id"] != link_id]
    if len(project_state["links"]) == before:
        raise ValueError(f"unknown link: {link_id}")


def _touch_session_for_object(
    sessions: dict[str, dict[str, Any]],
    session_id: str,
    project_state: dict[str, Any],
    object_id: str,
    timestamp: str,
    project_head: str,
) -> None:
    obj = _find_object(project_state, object_id)
    _touch_session(
        sessions,
        session_id,
        timestamp,
        object_id if obj and obj.get("type") == "decision" else None,
        project_head,
        add_decision=bool(obj and obj.get("type") == "decision"),
    )


def _maybe_activate_proposal_from_object(
    sessions: dict[str, dict[str, Any]],
    session_id: str,
    obj: dict[str, Any],
    project_head: str,
    timestamp: str,
) -> None:
    if obj.get("type") != "proposal" or session_id not in sessions:
        return
    metadata = obj.get("metadata", {})
    target_id = metadata.get("target_id")
    question_id = metadata.get("question_id")
    question = metadata.get("question")
    recommendation = metadata.get("recommendation") or obj.get("title")
    if not all(isinstance(value, str) and value.strip() for value in (target_id, question_id, question, recommendation)):
        return
    proposal = {
        "proposal_id": obj["id"],
        "origin_session_id": metadata.get("origin_session_id") or session_id,
        "target_type": metadata.get("target_type") or "decision",
        "target_id": target_id,
        "recommendation_version": metadata.get("recommendation_version"),
        "based_on_project_head": metadata.get("based_on_project_head"),
        "is_active": bool(metadata.get("is_active", obj.get("status") == "active")),
        "activated_at": metadata.get("activated_at") or timestamp,
        "inactive_reason": metadata.get("inactive_reason"),
        "question_id": question_id,
        "question": question,
        "recommendation": recommendation,
        "why": metadata.get("why") or obj.get("body"),
        "if_not": metadata.get("if_not"),
    }
    session = sessions[session_id]
    session["working_state"]["active_proposal"] = proposal
    if proposal["is_active"]:
        session["working_state"]["current_question_id"] = question_id
        session["working_state"]["current_question"] = question
        session["summary"]["current_question_preview"] = question
        session["summary"]["active_decision_id"] = target_id
    session["summary"]["latest_summary"] = recommendation


def _project_close_summary_objects(
    project_state: dict[str, Any],
    session_id: str,
    close_summary: dict[str, Any],
    timestamp: str,
    event_id: str,
) -> None:
    for action_slice in close_summary.get("candidate_action_slices", []):
        decision_id = action_slice.get("decision_id")
        if not decision_id:
            continue
        action_id = f"O-action-{_short_hash(session_id, decision_id, action_slice.get('name'))}"
        _ensure_object(
            project_state,
            object_id=action_id,
            object_type="action",
            title=action_slice.get("name") or decision_id,
            body=action_slice.get("summary"),
            status=action_slice.get("status") or "active",
            timestamp=timestamp,
            event_id=event_id,
            metadata={
                key: deepcopy(value)
                for key, value in action_slice.items()
                if key not in {"decision_id", "name", "summary", "status"}
            },
        )
        _ensure_link(
            project_state,
            link_id=f"L-{action_id}-addresses-{decision_id}",
            source_object_id=action_id,
            relation="addresses",
            target_object_id=decision_id,
            rationale=action_slice.get("summary"),
            timestamp=timestamp,
            event_id=event_id,
        )
    for risk in close_summary.get("unresolved_risks", []):
        title = risk.get("title") or risk.get("summary") or risk.get("id") or "Unresolved risk"
        risk_id = f"O-risk-{_short_hash(session_id, title)}"
        _ensure_object(
            project_state,
            object_id=risk_id,
            object_type="risk",
            title=title,
            body=risk.get("summary"),
            status=risk.get("status") or "open",
            timestamp=timestamp,
            event_id=event_id,
            metadata={key: deepcopy(value) for key, value in risk.items() if key not in {"title", "summary", "status"}},
        )


def _finalize_project_state(bundle: dict[str, Any]) -> None:
    project_state = bundle["project_state"]
    sessions = bundle["sessions"]
    _recompute_counts(project_state)
    project_state["sessions_index"] = _sessions_index(sessions)
    from decide_me.session_graph import build_session_graph

    project_state["graph"] = build_session_graph(bundle)


def _sessions_index(sessions: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
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


def _short_hash(*parts: Any) -> str:
    material = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:12]


def _touch_session(
    sessions: dict[str, dict[str, Any]],
    session_id: str,
    timestamp: str,
    decision_id: str | None,
    project_head: str,
    *,
    add_decision: bool = True,
) -> None:
    if session_id not in sessions:
        return
    session = sessions[session_id]
    session["session"]["last_seen_at"] = timestamp
    if session["session"]["lifecycle"]["status"] != "closed":
        session["session"]["lifecycle"]["status"] = "active"
    session["working_state"]["last_seen_project_head"] = project_head
    if add_decision and decision_id:
        session["session"]["decision_ids"] = stable_unique([*session["session"]["decision_ids"], decision_id])


def _clear_question_state(session: dict[str, Any], latest_summary: str | None) -> None:
    proposal = session["working_state"]["active_proposal"]
    if proposal.get("proposal_id"):
        proposal["is_active"] = False
        proposal["inactive_reason"] = proposal.get("inactive_reason") or "resolved"
    session["working_state"]["current_question_id"] = None
    session["working_state"]["current_question"] = None
    session["summary"]["current_question_preview"] = None
    session["summary"]["active_decision_id"] = None
    if latest_summary:
        session["summary"]["latest_summary"] = latest_summary


def _deactivate_proposal(session: dict[str, Any], reason: str) -> None:
    proposal = session["working_state"]["active_proposal"]
    if not proposal.get("proposal_id"):
        return
    proposal["is_active"] = False
    proposal["inactive_reason"] = reason
    session["working_state"]["current_question_id"] = None
    session["working_state"]["current_question"] = None
    session["summary"]["current_question_preview"] = None
    session["summary"]["active_decision_id"] = None


def _invalidate_proposal(session: dict[str, Any], reason: str) -> None:
    proposal = session["working_state"]["active_proposal"]
    if not proposal.get("proposal_id"):
        return
    proposal["is_active"] = False
    proposal["inactive_reason"] = reason
    proposal["target_type"] = None
    proposal["target_id"] = None
    proposal["question_id"] = None
    proposal["question"] = None
    proposal["recommendation"] = None
    proposal["why"] = None
    proposal["if_not"] = None


def _deep_update(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = deepcopy(value)


def _upsert_taxonomy_node(taxonomy_state: dict[str, Any], node_patch: dict[str, Any]) -> None:
    for node in taxonomy_state["nodes"]:
        if node["id"] == node_patch["id"]:
            _deep_update(node, node_patch)
            return
    taxonomy_state["nodes"].append(deepcopy(node_patch))
    taxonomy_state["nodes"].sort(key=lambda item: item["id"])


def _decision_hidden_strings(decision: dict[str, Any]) -> set[str]:
    metadata = decision.get("metadata", {})
    values = {
        decision.get("title"),
        decision.get("body"),
        metadata.get("question"),
        metadata.get("context"),
        metadata.get("accepted_answer", {}).get("summary"),
        metadata.get("resolved_by_evidence", {}).get("summary"),
    }
    return {str(value).strip() for value in values if value and str(value).strip()}


def _sanitize_session_after_invalidation(
    session: dict[str, Any],
    *,
    decision_id: str,
    hidden_strings: set[str],
) -> bool:
    affected = False
    decision_ids = session["session"].get("decision_ids", [])
    if decision_id in decision_ids:
        session["session"]["decision_ids"] = [candidate for candidate in decision_ids if candidate != decision_id]
        affected = True

    if session["summary"].get("active_decision_id") == decision_id:
        session["summary"]["active_decision_id"] = None
        session["summary"]["current_question_preview"] = None
        session["working_state"]["current_question_id"] = None
        session["working_state"]["current_question"] = None
        affected = True

    proposal = session["working_state"]["active_proposal"]
    if proposal.get("target_id") == decision_id:
        _invalidate_proposal(session, "decision-invalidated")
        session["summary"]["active_decision_id"] = None
        session["summary"]["current_question_preview"] = None
        session["working_state"]["current_question_id"] = None
        session["working_state"]["current_question"] = None
        affected = True

    for section, key in (
        (session["summary"], "latest_summary"),
        (session["summary"], "current_question_preview"),
        (session["working_state"], "current_question"),
    ):
        if section.get(key) in hidden_strings:
            section[key] = None
            affected = True

    close_summary = session.get("close_summary")
    if close_summary:
        affected = _sanitize_close_summary(session, decision_id, hidden_strings) or affected
    return affected


def _sanitize_close_summary(
    session: dict[str, Any], decision_id: str, hidden_strings: set[str]
) -> bool:
    close_summary = session["close_summary"]
    changed = False
    for key in ("accepted_decisions", "deferred_decisions", "unresolved_blockers", "unresolved_risks"):
        before = close_summary[key]
        filtered = [item for item in before if item.get("id") != decision_id]
        if len(filtered) != len(before):
            close_summary[key] = filtered
            changed = True

    before_slices = close_summary["candidate_action_slices"]
    action_slices = [item for item in before_slices if item.get("decision_id") != decision_id]
    if len(action_slices) != len(before_slices):
        close_summary["candidate_action_slices"] = action_slices
        changed = True

    accepted_ids = {item["id"] for item in close_summary["accepted_decisions"]}
    workstreams: list[dict[str, Any]] = []
    for workstream in close_summary["candidate_workstreams"]:
        scope = [candidate for candidate in workstream.get("scope", []) if candidate != decision_id]
        if not scope:
            changed = True
            continue
        implementation_ready_scope = [
            candidate for candidate in workstream.get("implementation_ready_scope", []) if candidate != decision_id
        ]
        updated = deepcopy(workstream)
        updated["scope"] = scope
        updated["implementation_ready_scope"] = implementation_ready_scope
        updated["accepted_count"] = len([candidate for candidate in scope if candidate in accepted_ids])
        domain = updated["name"].removesuffix("-workstream")
        if implementation_ready_scope:
            updated["summary"] = (
                f"Advance {domain} decisions for the current milestone. "
                f"{len(implementation_ready_scope)} implementation-ready slice(s) are already grounded."
            )
        else:
            updated["summary"] = f"Advance {domain} decisions for the current milestone."
        if updated != workstream:
            changed = True
        workstreams.append(updated)
    close_summary["candidate_workstreams"] = workstreams

    visible_evidence_refs: list[str] = []
    for item in close_summary["accepted_decisions"]:
        visible_evidence_refs.extend(item.get("evidence_refs", []))
    for item in close_summary["candidate_action_slices"]:
        visible_evidence_refs.extend(item.get("evidence_refs", []))
    filtered_evidence_refs = stable_unique(visible_evidence_refs)
    if filtered_evidence_refs != close_summary.get("evidence_refs", []):
        close_summary["evidence_refs"] = filtered_evidence_refs
        changed = True

    fallback_title = session["session"].get("bound_context_hint") or session["session"]["id"]
    fallback_statement = session["session"].get("bound_context_hint") or close_summary.get("goal") or fallback_title
    if close_summary.get("work_item_title") in hidden_strings:
        close_summary["work_item_title"] = fallback_title
        changed = True
    if close_summary.get("work_item_statement") in hidden_strings:
        close_summary["work_item_statement"] = fallback_statement
        changed = True

    readiness = _close_summary_readiness(close_summary)
    if close_summary.get("readiness") != readiness:
        close_summary["readiness"] = readiness
        changed = True
    return changed


def _close_summary_readiness(close_summary: dict[str, Any]) -> str:
    if close_summary.get("unresolved_blockers"):
        return "blocked"
    if close_summary.get("unresolved_risks"):
        return "conditional"
    return "ready"


def _recompute_counts(project_state: dict[str, Any]) -> None:
    objects = project_state["objects"]
    links = project_state["links"]
    counts = {
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
    project_state["counts"] = counts
