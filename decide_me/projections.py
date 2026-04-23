from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from decide_me.taxonomy import default_taxonomy_state, stable_unique


OPEN_DECISION_STATUSES = {"unresolved", "proposed", "rejected", "blocked"}
IDLE_AFTER = timedelta(hours=12)
STALE_AFTER = timedelta(days=7)


def default_project_state() -> dict[str, Any]:
    return {
        "schema_version": 3,
        "project": {
            "name": None,
            "objective": None,
            "current_milestone": None,
            "stop_rule": None,
        },
        "state": {"project_version": 0, "updated_at": None, "last_event_id": None},
        "protocol": {
            "plain_ok_scope": "same-session-active-proposal-only",
            "proposal_expiry_rules": [
                "project-version-changed",
                "session-boundary",
                "superseded-proposal",
                "session-closed",
            ],
            "close_policy": "generate-close-summary-on-close",
        },
        "counts": {"p0_now_open": 0, "p1_now_open": 0, "p2_open": 0, "blocked": 0, "deferred": 0},
        "default_bundles": [],
        "decisions": [],
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
        "schema_version": 3,
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
            "compatibility_tags": [],
            "search_terms": [],
            "source_refs": [],
            "updated_at": None,
        },
        "close_summary": default_close_summary(),
        "working_state": {
            "current_question_id": None,
            "current_question": None,
            "active_proposal": empty_active_proposal(),
            "last_seen_project_version": 0,
        },
    }


def empty_active_proposal() -> dict[str, Any]:
    return {
        "proposal_id": None,
        "target_type": None,
        "target_id": None,
        "recommendation_version": None,
        "based_on_project_version": None,
        "is_active": False,
        "activated_at": None,
        "inactive_reason": None,
        "question_id": None,
        "question": None,
        "recommendation": None,
        "why": None,
        "if_not": None,
    }


def default_decision(decision_id: str, title: str | None = None) -> dict[str, Any]:
    return {
        "id": decision_id,
        "title": title,
        "kind": "choice",
        "domain": "other",
        "priority": "P1",
        "frontier": "later",
        "status": "unresolved",
        "resolvable_by": "human",
        "reversibility": "reversible",
        "depends_on": [],
        "blocked_by": [],
        "question": None,
        "context": None,
        "options": [],
        "recommendation": {
            "proposal_id": None,
            "version": 0,
            "summary": None,
            "rationale_short": None,
            "confidence": "medium",
            "proposed_at": None,
            "based_on_project_version": None,
        },
        "accepted_answer": {
            "summary": None,
            "accepted_at": None,
            "accepted_via": None,
            "proposal_id": None,
        },
        "resolved_by_evidence": {
            "source": None,
            "summary": None,
            "resolved_at": None,
            "evidence_refs": [],
        },
        "evidence_refs": [],
        "revisit_triggers": [],
        "notes": [],
        "bundle_id": None,
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


def rebuild_projections(events: list[dict[str, Any]]) -> dict[str, Any]:
    initial_timestamp = events[0]["ts"] if events else None
    project_state = default_project_state()
    taxonomy_state = default_taxonomy_state(now=initial_timestamp)
    sessions: dict[str, dict[str, Any]] = {}

    for event in events:
        apply_event(project_state, taxonomy_state, sessions, event)

    _recompute_counts(project_state)
    return {
        "project_state": project_state,
        "taxonomy_state": taxonomy_state,
        "sessions": {session_id: sessions[session_id] for session_id in sorted(sessions)},
    }


def apply_event(
    project_state: dict[str, Any],
    taxonomy_state: dict[str, Any],
    sessions: dict[str, dict[str, Any]],
    event: dict[str, Any],
) -> None:
    event_type = event["event_type"]
    payload = event["payload"]
    session_id = event["session_id"]
    ts = event["ts"]

    if event_type == "project_initialized":
        project_state["project"] = deepcopy(payload["project"])
        if payload.get("protocol"):
            project_state["protocol"] = deepcopy(payload["protocol"])
        if payload.get("default_bundles") is not None:
            project_state["default_bundles"] = deepcopy(payload["default_bundles"])
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
        session["session"]["last_seen_at"] = payload["resumed_at"]
        session["session"]["lifecycle"]["status"] = "active"
        _deactivate_proposal(session, "session-boundary")
    elif event_type == "decision_discovered":
        decision = _ensure_decision(project_state, payload["decision"]["id"], payload["decision"].get("title"))
        _deep_update(decision, payload["decision"])
        _touch_session(sessions, session_id, ts, payload["decision"]["id"], event["project_version_after"])
    elif event_type == "decision_enriched":
        decision = _ensure_decision(project_state, payload["decision_id"])
        if payload.get("notes_append"):
            decision["notes"] = stable_unique([*decision["notes"], *payload["notes_append"]])
        if payload.get("revisit_triggers_append"):
            decision["revisit_triggers"] = stable_unique(
                [*decision["revisit_triggers"], *payload["revisit_triggers_append"]]
            )
        context_append = payload.get("context_append")
        if context_append:
            existing_context = decision.get("context")
            if existing_context:
                fragments = [fragment for fragment in [existing_context, context_append] if fragment]
                decision["context"] = "\n".join(
                    stable_unique(fragment.strip() for fragment in fragments if fragment.strip())
                )
            else:
                decision["context"] = context_append
        _touch_session(sessions, session_id, ts, payload["decision_id"], event["project_version_after"])
    elif event_type == "question_asked":
        session = sessions[session_id]
        session["working_state"]["current_question_id"] = payload["question_id"]
        session["working_state"]["current_question"] = payload["question"]
        session["summary"]["current_question_preview"] = payload["question"]
        session["summary"]["active_decision_id"] = payload["decision_id"]
        _touch_session(sessions, session_id, ts, payload["decision_id"], event["project_version_after"])
    elif event_type == "proposal_issued":
        proposal = deepcopy(payload["proposal"])
        decision = _ensure_decision(project_state, proposal["target_id"])
        decision["status"] = "proposed"
        decision["question"] = proposal["question"]
        decision["recommendation"] = {
            "proposal_id": proposal["proposal_id"],
            "version": proposal["recommendation_version"],
            "summary": proposal["recommendation"],
            "rationale_short": proposal["why"],
            "confidence": "medium",
            "proposed_at": proposal["activated_at"],
            "based_on_project_version": proposal["based_on_project_version"],
        }
        session = sessions[session_id]
        session["working_state"]["active_proposal"] = proposal
        session["working_state"]["current_question_id"] = proposal["question_id"]
        session["working_state"]["current_question"] = proposal["question"]
        session["summary"]["current_question_preview"] = proposal["question"]
        session["summary"]["active_decision_id"] = proposal["target_id"]
        session["summary"]["latest_summary"] = proposal["recommendation"]
        _touch_session(sessions, session_id, ts, proposal["target_id"], event["project_version_after"])
    elif event_type == "proposal_accepted":
        decision = _ensure_decision(project_state, payload["target_id"])
        decision["status"] = "accepted"
        decision["accepted_answer"] = deepcopy(payload["accepted_answer"])
        if (
            decision["recommendation"].get("summary")
            and decision["accepted_answer"]["summary"] != decision["recommendation"]["summary"]
        ):
            decision["notes"] = stable_unique(
                [*decision["notes"], "Accepted answer overrides the last recommendation."]
            )
        _clear_question_state(sessions[session_id], payload["reason"] if payload.get("reason") else None)
        _touch_session(sessions, session_id, ts, payload["target_id"], event["project_version_after"])
    elif event_type == "proposal_rejected":
        decision = _ensure_decision(project_state, payload["target_id"])
        decision["status"] = "rejected"
        _clear_question_state(sessions[session_id], payload["reason"])
        _touch_session(sessions, session_id, ts, payload["target_id"], event["project_version_after"])
    elif event_type == "decision_deferred":
        decision = _ensure_decision(project_state, payload["decision_id"])
        decision["status"] = "deferred"
        decision["frontier"] = "deferred"
        decision["notes"] = stable_unique([*decision["notes"], payload["reason"]])
        _clear_question_state(sessions[session_id], payload["reason"])
        _touch_session(sessions, session_id, ts, payload["decision_id"], event["project_version_after"])
    elif event_type == "decision_resolved_by_evidence":
        decision = _ensure_decision(project_state, payload["decision_id"])
        decision["status"] = "resolved-by-evidence"
        decision["resolved_by_evidence"] = {
            "source": payload["source"],
            "summary": payload["summary"],
            "resolved_at": ts,
            "evidence_refs": deepcopy(payload["evidence_refs"]),
        }
        decision["accepted_answer"] = {
            "summary": payload["summary"],
            "accepted_at": ts,
            "accepted_via": "evidence",
            "proposal_id": None,
        }
        decision["evidence_refs"] = stable_unique([*decision["evidence_refs"], *payload["evidence_refs"]])
        _clear_question_state(sessions[session_id], payload["summary"])
        _touch_session(sessions, session_id, ts, payload["decision_id"], event["project_version_after"])
    elif event_type == "classification_updated":
        session = sessions[session_id]
        session["classification"] = deepcopy(payload["classification"])
        _touch_session(
            sessions,
            session_id,
            ts,
            session["summary"].get("active_decision_id"),
            event["project_version_after"],
        )
    elif event_type == "close_summary_generated":
        session = sessions[session_id]
        session["close_summary"] = deepcopy(payload["close_summary"])
        session["summary"]["latest_summary"] = payload["close_summary"]["work_item_title"]
        _touch_session(
            sessions,
            session_id,
            ts,
            session["summary"].get("active_decision_id"),
            event["project_version_after"],
        )
    elif event_type == "session_closed":
        session = sessions[session_id]
        session["session"]["lifecycle"]["status"] = "closed"
        session["session"]["lifecycle"]["closed_at"] = payload["closed_at"]
        _clear_question_state(session, "session-closed")
        _touch_session(
            sessions,
            session_id,
            ts,
            session["summary"].get("active_decision_id"),
            event["project_version_after"],
        )
    elif event_type == "taxonomy_extended":
        for node in payload["nodes"]:
            _upsert_taxonomy_node(taxonomy_state, node)
    elif event_type == "compatibility_backfilled":
        session = sessions[session_id]
        compatibility = session["classification"].get("compatibility_tags", [])
        session["classification"]["compatibility_tags"] = stable_unique(
            [*compatibility, *payload["additions"]]
        )
        _touch_session(
            sessions,
            session_id,
            ts,
            session["summary"].get("active_decision_id"),
            event["project_version_after"],
        )
    elif event_type == "plan_generated":
        pass

    project_state["state"] = {
        "project_version": event["project_version_after"],
        "updated_at": ts,
        "last_event_id": event["event_id"],
    }
    taxonomy_state["state"] = {"updated_at": ts, "last_event_id": event["event_id"]}


def _ensure_decision(
    project_state: dict[str, Any], decision_id: str, title: str | None = None
) -> dict[str, Any]:
    for decision in project_state["decisions"]:
        if decision["id"] == decision_id:
            if title and not decision.get("title"):
                decision["title"] = title
            return decision
    decision = default_decision(decision_id, title)
    project_state["decisions"].append(decision)
    project_state["decisions"].sort(key=lambda item: item["id"])
    return decision


def _touch_session(
    sessions: dict[str, dict[str, Any]],
    session_id: str,
    timestamp: str,
    decision_id: str | None,
    project_version: int,
) -> None:
    if session_id not in sessions:
        return
    session = sessions[session_id]
    session["session"]["last_seen_at"] = timestamp
    if session["session"]["lifecycle"]["status"] != "closed":
        session["session"]["lifecycle"]["status"] = "active"
    session["working_state"]["last_seen_project_version"] = project_version
    if decision_id:
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


def _recompute_counts(project_state: dict[str, Any]) -> None:
    decisions = project_state["decisions"]
    counts = {
        "p0_now_open": 0,
        "p1_now_open": 0,
        "p2_open": 0,
        "blocked": 0,
        "deferred": 0,
    }
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
    project_state["counts"] = counts
