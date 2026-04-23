from __future__ import annotations

from copy import deepcopy
from typing import Any

from decide_me.events import AUTO_PROJECT_VERSION, new_entity_id, utc_now
from decide_me.selector import proposal_is_stale
from decide_me.store import load_runtime, runtime_paths, transact


def discover_decision(ai_dir: str, session_id: str, decision: dict[str, Any]) -> dict[str, Any]:
    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        _require_session(bundle, session_id)
        return [
            {
                "session_id": session_id,
                "event_type": "decision_discovered",
                "payload": {"decision": decision},
            }
        ]

    _, bundle = transact(ai_dir, builder)
    return _lookup_decision(bundle, decision["id"])


def issue_proposal(
    ai_dir: str,
    session_id: str,
    *,
    decision_id: str,
    question: str,
    recommendation: str,
    why: str,
    if_not: str,
) -> dict[str, Any]:
    now = utc_now()
    question_id = new_entity_id("Q")
    proposal_id = new_entity_id("P")

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_session(bundle, session_id)
        if session["session"]["lifecycle"]["status"] == "closed":
            raise ValueError(f"session {session_id} is closed")
        decision = _lookup_decision(bundle, decision_id)
        next_version = int(decision["recommendation"]["version"]) + 1
        return [
            {
                "session_id": session_id,
                "ts": now,
                "event_type": "question_asked",
                "payload": {
                    "decision_id": decision_id,
                    "question_id": question_id,
                    "question": question,
                },
            },
            {
                "session_id": session_id,
                "ts": now,
                "event_type": "proposal_issued",
                "payload": {
                    "proposal": {
                        "proposal_id": proposal_id,
                        "target_type": "decision",
                        "target_id": decision_id,
                        "recommendation_version": next_version,
                        "based_on_project_version": AUTO_PROJECT_VERSION,
                        "question_id": question_id,
                        "question": question,
                        "recommendation": recommendation,
                        "why": why,
                        "if_not": if_not,
                        "is_active": True,
                        "activated_at": now,
                        "inactive_reason": None,
                    }
                },
            },
        ]

    _, bundle = transact(ai_dir, builder)
    session = bundle["sessions"][session_id]
    return deepcopy(session["working_state"]["active_proposal"])


def accept_proposal(
    ai_dir: str,
    session_id: str,
    *,
    proposal_id: str | None = None,
    acceptance_mode: str | None = None,
) -> dict[str, Any]:
    now = utc_now()

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_session(bundle, session_id)
        target = _resolve_proposal_target(bundle, session, proposal_id=proposal_id)
        if proposal_id is None:
            stale, reason = proposal_is_stale(bundle["project_state"], session)
            if stale:
                raise ValueError(
                    f"active proposal for session {session_id} is stale: {reason}. "
                    f"Use Accept {target['proposal_id']} for explicit acceptance."
                )
            mode = acceptance_mode or "ok"
        else:
            mode = acceptance_mode or "explicit"
        accepted_answer = {
            "summary": target["recommendation"],
            "accepted_at": now,
            "accepted_via": mode,
            "proposal_id": target["proposal_id"],
        }
        return [
            {
                "session_id": session_id,
                "event_type": "proposal_accepted",
                "payload": {
                    "proposal_id": target["proposal_id"],
                    "target_type": target["target_type"],
                    "target_id": target["target_id"],
                    "accepted_answer": accepted_answer,
                    "reason": target["recommendation"],
                },
            }
        ]

    _, bundle = transact(ai_dir, builder)
    return _lookup_decision(bundle, _resolve_decision_id(bundle, session_id, proposal_id))


def reject_proposal(ai_dir: str, session_id: str, *, reason: str, proposal_id: str | None = None) -> dict[str, Any]:
    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_session(bundle, session_id)
        target = _resolve_proposal_target(bundle, session, proposal_id=proposal_id)
        return [
            {
                "session_id": session_id,
                "event_type": "proposal_rejected",
                "payload": {
                    "proposal_id": target["proposal_id"],
                    "target_type": target["target_type"],
                    "target_id": target["target_id"],
                    "reason": reason,
                },
            }
        ]

    _, bundle = transact(ai_dir, builder)
    return _lookup_decision(bundle, _resolve_decision_id(bundle, session_id, proposal_id))


def defer_decision(ai_dir: str, session_id: str, *, decision_id: str, reason: str) -> dict[str, Any]:
    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        _require_session(bundle, session_id)
        _lookup_decision(bundle, decision_id)
        return [
            {
                "session_id": session_id,
                "event_type": "decision_deferred",
                "payload": {"decision_id": decision_id, "reason": reason},
            }
        ]

    _, bundle = transact(ai_dir, builder)
    return _lookup_decision(bundle, decision_id)


def resolve_by_evidence(
    ai_dir: str,
    session_id: str,
    *,
    decision_id: str,
    source: str,
    summary: str,
    evidence_refs: list[str],
) -> dict[str, Any]:
    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        _require_session(bundle, session_id)
        _lookup_decision(bundle, decision_id)
        return [
            {
                "session_id": session_id,
                "event_type": "decision_resolved_by_evidence",
                "payload": {
                    "decision_id": decision_id,
                    "source": source,
                    "summary": summary,
                    "evidence_refs": evidence_refs,
                },
            }
        ]

    _, bundle = transact(ai_dir, builder)
    return _lookup_decision(bundle, decision_id)


def update_classification(
    ai_dir: str,
    session_id: str,
    *,
    domain: str | None,
    abstraction_level: str | None,
    assigned_tags: list[str] | None = None,
    compatibility_tags: list[str] | None = None,
    search_terms: list[str] | None = None,
    source_refs: list[str] | None = None,
) -> dict[str, Any]:
    now = utc_now()

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_session(bundle, session_id)
        classification = deepcopy(session["classification"])
        classification.update(
            {
                "domain": domain,
                "abstraction_level": abstraction_level,
                "assigned_tags": assigned_tags or [],
                "compatibility_tags": compatibility_tags or [],
                "search_terms": search_terms or [],
                "source_refs": source_refs or [],
                "updated_at": now,
            }
        )
        return [
            {
                "session_id": session_id,
                "event_type": "classification_updated",
                "payload": {"classification": classification},
            }
        ]

    _, bundle = transact(ai_dir, builder)
    return bundle["sessions"][session_id]["classification"]


def render_question_block(decision: dict[str, Any], proposal: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Decision: {decision['id']}",
            f"Proposal: {proposal['proposal_id']}",
            f"Question: {proposal['question']}",
            f"Recommendation: {proposal['recommendation']}",
            f"Why: {proposal['why']}",
            f"If not: {proposal['if_not']}",
        ]
    )


def current_bundle(ai_dir: str) -> dict[str, Any]:
    return load_runtime(runtime_paths(ai_dir))


def _require_session(bundle: dict[str, Any], session_id: str) -> dict[str, Any]:
    try:
        return bundle["sessions"][session_id]
    except KeyError as exc:
        raise ValueError(f"unknown session: {session_id}") from exc


def _lookup_decision(bundle: dict[str, Any], decision_id: str) -> dict[str, Any]:
    for decision in bundle["project_state"]["decisions"]:
        if decision["id"] == decision_id:
            return deepcopy(decision)
    raise ValueError(f"unknown decision: {decision_id}")


def _resolve_proposal_target(
    bundle: dict[str, Any], session: dict[str, Any], proposal_id: str | None
) -> dict[str, Any]:
    active = session["working_state"]["active_proposal"]
    if proposal_id is None:
        if not active.get("proposal_id"):
            raise ValueError("no active proposal for this session")
        return deepcopy(active)

    if active.get("proposal_id") == proposal_id:
        return deepcopy(active)

    for decision in bundle["project_state"]["decisions"]:
        recommendation = decision["recommendation"]
        if recommendation.get("proposal_id") == proposal_id:
            return {
                "proposal_id": proposal_id,
                "target_type": "decision",
                "target_id": decision["id"],
                "recommendation_version": recommendation["version"],
                "based_on_project_version": recommendation["based_on_project_version"],
                "question_id": None,
                "question": decision.get("question"),
                "recommendation": recommendation["summary"],
                "why": recommendation["rationale_short"],
                "if_not": decision.get("context"),
                "is_active": False,
                "activated_at": recommendation["proposed_at"],
                "inactive_reason": "explicit-accept",
            }
    raise ValueError(f"unknown or superseded proposal: {proposal_id}")


def _resolve_decision_id(bundle: dict[str, Any], session_id: str, proposal_id: str | None) -> str:
    session = bundle["sessions"][session_id]
    if proposal_id is None:
        target_id = session["summary"].get("active_decision_id")
        if target_id:
            return target_id
    for decision in bundle["project_state"]["decisions"]:
        if decision["accepted_answer"]["proposal_id"] == proposal_id:
            return decision["id"]
    active = session["working_state"]["active_proposal"]
    return active["target_id"]
