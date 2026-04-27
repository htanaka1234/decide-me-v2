from __future__ import annotations

from copy import deepcopy
from typing import Any

from decide_me.events import new_entity_id, utc_now
from decide_me.projections import OPEN_DECISION_STATUSES, decision_is_invalidated, effective_session_status
from decide_me.search import search_sessions, session_list_entry
from decide_me.store import load_runtime, runtime_paths, transact
from decide_me.taxonomy import resolved_tag_nodes, stable_unique


def create_session(ai_dir: str, context: str | None = None) -> dict[str, Any]:
    session_id = new_entity_id("S")
    now = utc_now()

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        if bundle["project_state"]["state"]["event_count"] == 0:
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
    bundle = load_runtime(runtime_paths(ai_dir))
    sessions = deepcopy(bundle["sessions"])
    sessions = search_sessions(
        sessions,
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
        "count": len(sessions),
        "sessions": sessions,
    }


def show_session(ai_dir: str, session_id: str) -> dict[str, Any]:
    bundle = load_runtime(runtime_paths(ai_dir))
    session_state = deepcopy(_require_session(bundle, session_id))
    session_state["session"]["lifecycle"]["effective_status"] = effective_session_status(session_state)
    return {
        "status": "ok",
        "display": session_list_entry(session_state, bundle["taxonomy_state"]),
        "resolved_tags": resolved_tag_nodes(session_state, bundle["taxonomy_state"]),
        "session": session_state,
    }


def resume_session(ai_dir: str, session_id: str) -> dict[str, Any]:
    now = utc_now()

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_session(bundle, session_id)
        if session["session"]["lifecycle"]["status"] == "closed":
            raise ValueError(f"session {session_id} is closed")
        return [
            *_proposal_boundary_status_events(
                bundle,
                session,
                now,
                "Session resumed; previous proposal became inactive.",
            ),
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
            *_proposal_boundary_status_events(
                bundle,
                session,
                now,
                "Session closed with unresolved active proposal.",
            ),
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
    decision_index = {decision["id"]: decision for decision in _decision_views(project_state)}
    active_target_id = session_state["working_state"]["active_proposal"].get("target_id")
    decisions = [
        _decision_for_close_summary(decision_index[decision_id], active_target_id)
        for decision_id in session_state["session"]["decision_ids"]
        if decision_id in decision_index
        and not decision_is_invalidated(decision_index[decision_id])
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

    action_slices = _candidate_action_slices(decisions)
    workstreams = _candidate_workstreams(decisions, action_slices)

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


def _proposal_boundary_status_events(
    bundle: dict[str, Any],
    session: dict[str, Any],
    changed_at: str,
    reason: str,
) -> list[dict[str, Any]]:
    active = session["working_state"]["active_proposal"]
    target_id = active.get("target_id")
    if not target_id:
        return []
    for obj in bundle["project_state"].get("objects", []):
        if obj.get("id") == target_id and obj.get("type") == "decision" and obj.get("status") == "proposed":
            return [
                {
                    "session_id": session["session"]["id"],
                    "event_type": "object_status_changed",
                    "payload": {
                        "object_id": target_id,
                        "from_status": "proposed",
                        "to_status": "unresolved",
                        "reason": reason,
                        "changed_at": changed_at,
                    },
                }
            ]
    return []


def _decision_snapshot(decision: dict[str, Any]) -> dict[str, Any]:
    answer = decision["accepted_answer"]["summary"] or decision["resolved_by_evidence"]["summary"]
    return {
        "id": decision["id"],
        "title": decision["title"],
        "kind": decision["kind"],
        "domain": decision["domain"],
        "priority": decision["priority"],
        "status": decision["status"],
        "resolvable_by": decision["resolvable_by"],
        "evidence_source": decision["resolved_by_evidence"]["source"],
        "evidence_refs": deepcopy(decision.get("evidence_refs", [])),
        "accepted_answer": answer,
    }


def _decision_views(project_state: dict[str, Any]) -> list[dict[str, Any]]:
    decisions = []
    for obj in project_state.get("objects", []):
        if obj.get("type") != "decision":
            continue
        metadata = deepcopy(obj.get("metadata", {}))
        accepted_answer = metadata.get("accepted_answer") or {"summary": None}
        resolved = metadata.get("resolved_by_evidence") or {
            "source": None,
            "summary": None,
            "evidence_refs": [],
        }
        decisions.append(
            {
                **metadata,
                "id": obj["id"],
                "title": obj.get("title"),
                "body": obj.get("body"),
                "status": obj.get("status"),
                "kind": metadata.get("kind", "choice"),
                "domain": metadata.get("domain", "other"),
                "priority": metadata.get("priority", "P1"),
                "frontier": metadata.get("frontier", "later"),
                "resolvable_by": metadata.get("resolvable_by", "human"),
                "reversibility": metadata.get("reversibility", "reversible"),
                "accepted_answer": accepted_answer,
                "resolved_by_evidence": resolved,
                "evidence_refs": metadata.get("evidence_refs") or resolved.get("evidence_refs", []),
                "recommendation": metadata.get("recommendation") or {"summary": None},
            }
        )
    return decisions


def _decision_for_close_summary(decision: dict[str, Any], active_target_id: str | None) -> dict[str, Any]:
    if decision["id"] != active_target_id or decision["status"] != "proposed":
        return decision
    demoted = deepcopy(decision)
    demoted["status"] = "unresolved"
    return demoted


def _candidate_workstreams(
    decisions: list[dict[str, Any]],
    action_slices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for decision in decisions:
        by_domain.setdefault(decision["domain"], []).append(decision)
    ready_by_domain: dict[str, list[str]] = {}
    for action_slice in action_slices:
        ready_by_domain.setdefault(action_slice["responsibility"], [])
        if action_slice.get("implementation_ready"):
            ready_by_domain[action_slice["responsibility"]].append(action_slice["decision_id"])
    workstreams = []
    for domain, items in sorted(by_domain.items()):
        implementation_ready_scope = stable_unique(ready_by_domain.get(domain, []))
        accepted_count = len(
            [decision for decision in items if decision["status"] in {"accepted", "resolved-by-evidence"}]
        )
        summary = f"Advance {domain} decisions for the current milestone."
        if implementation_ready_scope:
            summary = (
                f"Advance {domain} decisions for the current milestone. "
                f"{len(implementation_ready_scope)} implementation-ready slice(s) are already grounded."
            )
        workstreams.append(
            {
                "name": f"{domain}-workstream",
                "summary": summary,
                "scope": [decision["id"] for decision in items],
                "accepted_count": accepted_count,
                "implementation_ready_scope": implementation_ready_scope,
            }
        )
    return workstreams


def _candidate_action_slices(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slices = []
    for decision in decisions:
        if decision["status"] not in {"accepted", "resolved-by-evidence"}:
            continue
        summary = decision["accepted_answer"]["summary"] or decision["resolved_by_evidence"]["summary"]
        evidence_source = decision["resolved_by_evidence"]["source"]
        evidence_refs = deepcopy(decision.get("evidence_refs", []))
        slices.append(
            {
                "decision_id": decision["id"],
                "name": decision["title"],
                "summary": summary,
                "responsibility": decision["domain"],
                "priority": decision["priority"],
                "status": decision["status"],
                "kind": decision["kind"],
                "resolvable_by": decision["resolvable_by"],
                "reversibility": decision["reversibility"],
                "implementation_ready": _implementation_ready(decision),
                "evidence_backed": bool(evidence_source or evidence_refs),
                "evidence_source": evidence_source,
                "evidence_refs": evidence_refs,
                "next_step": _action_slice_next_step(decision),
            }
        )
    return sorted(slices, key=_action_slice_sort_key)


def _implementation_ready(decision: dict[str, Any]) -> bool:
    if decision["status"] == "resolved-by-evidence":
        return True
    if decision["resolvable_by"] in {"codebase", "docs", "tests"}:
        return bool(decision["accepted_answer"]["summary"] or decision["recommendation"]["summary"])
    return False


def _action_slice_next_step(decision: dict[str, Any]) -> str:
    subject = decision["title"] or decision["id"]
    resolvable_by = decision["resolvable_by"]
    if resolvable_by == "codebase":
        return f"Implement {subject}."
    if resolvable_by == "docs":
        return f"Document {subject}."
    if resolvable_by == "tests":
        return f"Add tests for {subject}."
    if resolvable_by == "external":
        return f"Coordinate the external dependency for {subject}."
    return f"Drive {subject} to completion."


def _action_slice_sort_key(action_slice: dict[str, Any]) -> tuple[int, int, int, str]:
    priority_rank = {"P0": 0, "P1": 1, "P2": 2}
    return (
        0 if action_slice.get("evidence_backed") else 1,
        0 if action_slice.get("implementation_ready") else 1,
        priority_rank.get(action_slice.get("priority"), 3),
        action_slice.get("name") or "",
    )
