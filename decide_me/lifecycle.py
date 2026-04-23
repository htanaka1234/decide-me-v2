from __future__ import annotations

from copy import deepcopy
from typing import Any

from decide_me.classification import ensure_compatibility_backfill
from decide_me.events import new_entity_id, utc_now
from decide_me.projections import OPEN_DECISION_STATUSES, effective_session_status
from decide_me.search import search_sessions, session_list_entry
from decide_me.store import load_runtime, runtime_paths, transact
from decide_me.taxonomy import resolved_tag_nodes, stable_unique


def create_session(ai_dir: str, context: str | None = None) -> dict[str, Any]:
    session_id = new_entity_id("S")
    now = utc_now()

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        if bundle["project_state"]["state"]["project_version"] == 0:
            raise ValueError("runtime is not bootstrapped")
        return [
            {
                "session_id": session_id,
                "event_type": "session_created",
                "payload": {
                    "session": {
                        "id": session_id,
                        "started_at": now,
                        "last_seen_at": now,
                        "bound_context_hint": context,
                    }
                },
            }
        ]

    _, bundle = transact(ai_dir, builder)
    return bundle["sessions"][session_id]


def list_sessions(
    ai_dir: str,
    *,
    query: str | None = None,
    statuses: list[str] | None = None,
    domains: list[str] | None = None,
    abstraction_levels: list[str] | None = None,
    tag_terms: list[str] | None = None,
) -> dict[str, Any]:
    backfilled, bundle = ensure_compatibility_backfill(ai_dir)
    sessions = search_sessions(
        bundle["sessions"],
        bundle["taxonomy_state"],
        query=query,
        statuses=statuses,
        domains=domains,
        abstraction_levels=abstraction_levels,
        tag_terms=tag_terms,
    )
    return {
        "status": "ok",
        "filters": {
            "query": query,
            "status": statuses or [],
            "domain": domains or [],
            "abstraction_level": abstraction_levels or [],
            "tags": tag_terms or [],
        },
        "backfilled": backfilled,
        "count": len(sessions),
        "sessions": sessions,
    }


def show_session(ai_dir: str, session_id: str) -> dict[str, Any]:
    backfilled, bundle = ensure_compatibility_backfill(ai_dir, [session_id])
    session_state = deepcopy(_require_session(bundle, session_id))
    session_state["session"]["lifecycle"]["effective_status"] = effective_session_status(session_state)
    return {
        "status": "ok",
        "display": session_list_entry(session_state, bundle["taxonomy_state"]),
        "resolved_tags": resolved_tag_nodes(session_state, bundle["taxonomy_state"]),
        "compatibility_tag_refs_added": backfilled[0]["added_compatibility_tag_refs"] if backfilled else [],
        "session": session_state,
    }


def resume_session(ai_dir: str, session_id: str) -> dict[str, Any]:
    now = utc_now()

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_session(bundle, session_id)
        if session["session"]["lifecycle"]["status"] == "closed":
            raise ValueError(f"session {session_id} is closed")
        return [
            {
                "session_id": session_id,
                "event_type": "session_resumed",
                "payload": {"resumed_at": now},
            }
        ]

    _, bundle = transact(ai_dir, builder)
    return bundle["sessions"][session_id]


def close_session(ai_dir: str, session_id: str) -> dict[str, Any]:
    now = utc_now()

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_session(bundle, session_id)
        if session["session"]["lifecycle"]["status"] == "closed":
            raise ValueError(f"session {session_id} is already closed")
        close_summary = build_close_summary(bundle["project_state"], session)
        close_summary["generated_at"] = now
        return [
            {
                "session_id": session_id,
                "event_type": "close_summary_generated",
                "payload": {"close_summary": close_summary},
            },
            {
                "session_id": session_id,
                "event_type": "session_closed",
                "payload": {"closed_at": now},
            },
        ]

    _, bundle = transact(ai_dir, builder)
    return bundle["sessions"][session_id]


def build_close_summary(project_state: dict[str, Any], session_state: dict[str, Any]) -> dict[str, Any]:
    decision_index = {decision["id"]: decision for decision in project_state["decisions"]}
    decisions = [
        decision_index[decision_id]
        for decision_id in session_state["session"]["decision_ids"]
        if decision_id in decision_index
    ]
    accepted = [
        _decision_snapshot(decision)
        for decision in decisions
        if decision["status"] in {"accepted", "resolved-by-evidence"}
    ]
    deferred = [_decision_snapshot(decision) for decision in decisions if decision["status"] == "deferred"]
    blockers = [
        _decision_snapshot(decision)
        for decision in decisions
        if decision["priority"] == "P0"
        and decision["frontier"] == "now"
        and decision["status"] in OPEN_DECISION_STATUSES
    ]
    risks = [
        _decision_snapshot(decision)
        for decision in decisions
        if decision["kind"] == "risk" and decision["status"] in OPEN_DECISION_STATUSES
    ]

    readiness = "ready"
    if blockers:
        readiness = "blocked"
    elif risks:
        readiness = "conditional"

    workstreams = _candidate_workstreams(decisions)
    action_slices = _candidate_action_slices(decisions)

    bound_context = session_state["session"].get("bound_context_hint")
    latest_summary = session_state["summary"].get("latest_summary")
    current_question = session_state["working_state"].get("current_question")

    return {
        "work_item_title": bound_context or latest_summary or session_state["session"]["id"],
        "work_item_statement": current_question or latest_summary or bound_context,
        "goal": project_state["project"]["objective"],
        "readiness": readiness,
        "accepted_decisions": accepted,
        "deferred_decisions": deferred,
        "unresolved_blockers": blockers,
        "unresolved_risks": risks,
        "candidate_workstreams": workstreams,
        "candidate_action_slices": action_slices,
        "evidence_refs": stable_unique(
            ref
            for decision in decisions
            for ref in decision.get("evidence_refs", [])
        ),
        "generated_at": None,
    }


def load_runtime_from_ai_dir(ai_dir: str) -> dict[str, Any]:
    return load_runtime(runtime_paths(ai_dir))


def _require_session(bundle: dict[str, Any], session_id: str) -> dict[str, Any]:
    try:
        return bundle["sessions"][session_id]
    except KeyError as exc:
        raise ValueError(f"unknown session: {session_id}") from exc


def _decision_snapshot(decision: dict[str, Any]) -> dict[str, Any]:
    answer = decision["accepted_answer"]["summary"] or decision["resolved_by_evidence"]["summary"]
    return {
        "id": decision["id"],
        "title": decision["title"],
        "domain": decision["domain"],
        "priority": decision["priority"],
        "status": decision["status"],
        "accepted_answer": answer,
    }


def _candidate_workstreams(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for decision in decisions:
        by_domain.setdefault(decision["domain"], []).append(decision)
    workstreams = []
    for domain, items in sorted(by_domain.items()):
        workstreams.append(
            {
                "name": f"{domain}-workstream",
                "summary": f"Advance {domain} decisions for the current milestone.",
                "scope": [decision["id"] for decision in items],
            }
        )
    return workstreams


def _candidate_action_slices(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slices = []
    for decision in decisions:
        if decision["status"] not in {"accepted", "resolved-by-evidence"}:
            continue
        slices.append(
            {
                "name": decision["title"],
                "summary": decision["accepted_answer"]["summary"]
                or decision["resolved_by_evidence"]["summary"],
                "responsibility": decision["domain"],
            }
        )
    return slices
