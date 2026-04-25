from __future__ import annotations

from copy import deepcopy
from typing import Any

from decide_me.constants import (
    ACCEPTED_VIA_VALUES,
    DISCOVERABLE_DECISION_FIELDS,
    DISCOVERABLE_DECISION_STATUSES,
    DOMAIN_VALUES,
    EVIDENCE_SOURCES,
    FORBIDDEN_DISCOVERED_DECISION_FIELDS,
)
from decide_me.events import AUTO_PROJECT_VERSION, new_entity_id, utc_now
from decide_me.selector import proposal_is_stale
from decide_me.store import load_runtime, runtime_paths, transact


OPEN_MUTATION_STATUSES = {"unresolved", "proposed", "rejected", "blocked"}
PROPOSABLE_STATUSES = {"unresolved", "rejected", "blocked"}
PROPOSAL_RESPONSE_STATUSES = {"proposed"}


def discover_decision(ai_dir: str, session_id: str, decision: dict[str, Any]) -> dict[str, Any]:
    sanitized_decision = _sanitize_discovered_decision(decision)

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        _require_mutable_session(bundle, session_id)
        decision_id = sanitized_decision.get("id")
        if decision_id and _decision_exists(bundle, decision_id):
            raise ValueError(f"decision {decision_id} already exists")
        return [
            {
                "session_id": session_id,
                "event_type": "decision_discovered",
                "payload": {"decision": sanitized_decision},
            }
        ]

    _, bundle = transact(ai_dir, builder)
    return _lookup_decision(bundle, sanitized_decision["id"])


def enrich_decision(
    ai_dir: str,
    session_id: str,
    *,
    decision_id: str,
    notes_append: list[str] | None = None,
    revisit_triggers_append: list[str] | None = None,
    context_append: str | None = None,
) -> dict[str, Any]:
    notes_append = [note.strip() for note in (notes_append or []) if note and note.strip()]
    revisit_triggers_append = [
        trigger.strip() for trigger in (revisit_triggers_append or []) if trigger and trigger.strip()
    ]
    context_append = context_append.strip() if context_append and context_append.strip() else None
    if not notes_append and not revisit_triggers_append and not context_append:
        bundle = current_bundle(ai_dir)
        session = _require_mutable_session(bundle, session_id)
        _require_bound_decision(session, decision_id)
        return _lookup_decision(bundle, decision_id)

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_mutable_session(bundle, session_id)
        _require_bound_decision(session, decision_id)
        _lookup_decision(bundle, decision_id)
        payload: dict[str, Any] = {
            "decision_id": decision_id,
            "notes_append": notes_append,
            "revisit_triggers_append": revisit_triggers_append,
        }
        if context_append is not None:
            payload["context_append"] = context_append
        return [
            {
                "session_id": session_id,
                "event_type": "decision_enriched",
                "payload": payload,
            }
        ]

    _, bundle = transact(ai_dir, builder)
    return _lookup_decision(bundle, decision_id)


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
    question = _require_non_empty_text(question, "question")
    recommendation = _require_non_empty_text(recommendation, "recommendation")
    why = _require_non_empty_text(why, "why")
    if_not = _require_non_empty_text(if_not, "if_not")
    now = utc_now()
    question_id = new_entity_id("Q")
    proposal_id = new_entity_id("P")

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_mutable_session(bundle, session_id)
        _require_bound_decision(session, decision_id)
        _require_no_other_active_proposal(session, decision_id)
        decision = _lookup_decision(bundle, decision_id)
        _require_decision_status(decision_id, decision, PROPOSABLE_STATUSES, "issue proposal")
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
                        "origin_session_id": session_id,
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
    target_id: dict[str, str] = {}

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_open_session(bundle, session_id)
        target = _resolve_proposal_target(bundle, session, proposal_id=proposal_id)
        target_id["value"] = target["target_id"]
        decision = _lookup_decision(bundle, target["target_id"])
        _require_decision_status(
            target["target_id"], decision, PROPOSAL_RESPONSE_STATUSES, "accept proposal"
        )
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
        _require_acceptance_mode(mode)
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
                    "origin_session_id": target["origin_session_id"],
                    "target_type": target["target_type"],
                    "target_id": target["target_id"],
                    "accepted_answer": accepted_answer,
                    "reason": target["recommendation"],
                },
            }
        ]

    _, bundle = transact(ai_dir, builder)
    return _lookup_decision(bundle, target_id["value"])


def reject_proposal(
    ai_dir: str, session_id: str, *, reason: str, proposal_id: str | None = None
) -> dict[str, Any]:
    reason = _require_non_empty_text(reason, "reason")
    target_id: dict[str, str] = {}

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_open_session(bundle, session_id)
        target = _resolve_proposal_target(bundle, session, proposal_id=proposal_id)
        target_id["value"] = target["target_id"]
        decision = _lookup_decision(bundle, target["target_id"])
        _require_decision_status(
            target["target_id"], decision, PROPOSAL_RESPONSE_STATUSES, "reject proposal"
        )
        return [
            {
                "session_id": session_id,
                "event_type": "proposal_rejected",
                "payload": {
                    "proposal_id": target["proposal_id"],
                    "origin_session_id": target["origin_session_id"],
                    "target_type": target["target_type"],
                    "target_id": target["target_id"],
                    "reason": reason,
                },
            }
        ]

    _, bundle = transact(ai_dir, builder)
    return _lookup_decision(bundle, target_id["value"])


def answer_proposal(
    ai_dir: str,
    session_id: str,
    *,
    answer_summary: str,
    proposal_id: str | None = None,
    reason: str | None = None,
    acceptance_mode: str = "explicit",
) -> dict[str, Any]:
    now = utc_now()
    normalized_reason = reason.strip() if reason and reason.strip() else None
    target_id: dict[str, str] = {}

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_open_session(bundle, session_id)
        target = _resolve_proposal_target(bundle, session, proposal_id=proposal_id)
        target_id["value"] = target["target_id"]
        decision = _lookup_decision(bundle, target["target_id"])
        _require_decision_status(
            target["target_id"], decision, PROPOSAL_RESPONSE_STATUSES, "answer proposal"
        )
        recommendation = target["recommendation"] or ""
        answer = answer_summary.strip()
        if not answer:
            raise ValueError("answer_summary must not be empty")
        _require_acceptance_mode(acceptance_mode)

        events: list[dict[str, Any]] = []
        if _normalize(answer) != _normalize(recommendation):
            events.append(
                {
                    "session_id": session_id,
                    "event_type": "proposal_rejected",
                    "payload": {
                        "proposal_id": target["proposal_id"],
                        "origin_session_id": target["origin_session_id"],
                        "target_type": target["target_type"],
                        "target_id": target["target_id"],
                        "reason": normalized_reason or "User supplied an alternative answer.",
                    },
                }
            )

        accepted_answer = {
            "summary": answer,
            "accepted_at": now,
            "accepted_via": acceptance_mode,
            "proposal_id": target["proposal_id"],
        }
        events.append(
            {
                "session_id": session_id,
                "event_type": "proposal_accepted",
                "payload": {
                    "proposal_id": target["proposal_id"],
                    "origin_session_id": target["origin_session_id"],
                    "target_type": target["target_type"],
                    "target_id": target["target_id"],
                    "accepted_answer": accepted_answer,
                    "reason": answer,
                },
            }
        )
        return events

    _, bundle = transact(ai_dir, builder)
    return _lookup_decision(bundle, target_id["value"])


def defer_decision(ai_dir: str, session_id: str, *, decision_id: str, reason: str) -> dict[str, Any]:
    reason = _require_non_empty_text(reason, "reason")

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_mutable_session(bundle, session_id)
        _require_bound_decision(session, decision_id)
        _require_no_other_active_proposal(session, decision_id)
        decision = _lookup_decision(bundle, decision_id)
        _require_decision_status(decision_id, decision, OPEN_MUTATION_STATUSES, "defer")
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
    if source not in EVIDENCE_SOURCES:
        raise ValueError(f"invalid evidence source: {source}")
    summary = summary.strip()
    if not summary:
        raise ValueError("summary must not be empty")
    if not isinstance(evidence_refs, list):
        raise ValueError("evidence_refs must be a list")

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_mutable_session(bundle, session_id)
        _require_bound_decision(session, decision_id)
        _require_no_other_active_proposal(session, decision_id)
        decision = _lookup_decision(bundle, decision_id)
        _require_decision_status(
            decision_id, decision, OPEN_MUTATION_STATUSES, "resolve by evidence"
        )
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


def invalidate_decision(
    ai_dir: str,
    session_id: str,
    *,
    decision_id: str,
    invalidated_by_decision_id: str,
    reason: str,
) -> dict[str, Any]:
    reason = reason.strip()
    if not reason:
        raise ValueError("reason must not be empty")
    if decision_id == invalidated_by_decision_id:
        raise ValueError("decision cannot invalidate itself")

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_session(bundle, session_id)
        _require_bound_decision(session, invalidated_by_decision_id)
        target = _lookup_decision(bundle, decision_id)
        invalidating = _lookup_decision(bundle, invalidated_by_decision_id)
        _require_not_invalidated(decision_id, target)
        _require_not_invalidated(invalidated_by_decision_id, invalidating)
        if invalidating["status"] not in {"accepted", "resolved-by-evidence"}:
            raise ValueError(
                f"invalidating decision {invalidated_by_decision_id} must be accepted or resolved-by-evidence"
            )
        return [
            {
                "session_id": session_id,
                "event_type": "decision_invalidated",
                "payload": {
                    "decision_id": decision_id,
                    "invalidated_by_decision_id": invalidated_by_decision_id,
                    "reason": reason,
                },
            }
        ]

    events, _ = transact(ai_dir, builder)
    event = events[-1]
    return {
        "status": "ok",
        "decision_id": decision_id,
        "invalidated_by_decision_id": invalidated_by_decision_id,
        "reason": reason,
        "event_id": event["event_id"],
    }


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
        session = _require_mutable_session(bundle, session_id)
        if domain is not None and domain not in DOMAIN_VALUES:
            raise ValueError(f"invalid domain: {domain}")
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


def _require_mutable_session(bundle: dict[str, Any], session_id: str) -> dict[str, Any]:
    session = _require_session(bundle, session_id)
    if session["session"]["lifecycle"]["status"] == "closed":
        raise ValueError(f"session {session_id} is closed")
    return session


def _require_open_session(bundle: dict[str, Any], session_id: str) -> dict[str, Any]:
    return _require_mutable_session(bundle, session_id)


def _require_bound_decision(session: dict[str, Any], decision_id: str) -> None:
    session_id = session["session"]["id"]
    if decision_id not in session["session"].get("decision_ids", []):
        raise ValueError(f"decision {decision_id} is not bound to session {session_id}")


def _require_no_other_active_proposal(session: dict[str, Any], decision_id: str) -> None:
    active = session["working_state"]["active_proposal"]
    if active.get("is_active") and active.get("target_id") != decision_id:
        raise ValueError(
            f"session has active proposal {active['proposal_id']} for {active['target_id']}; "
            f"resolve it before mutating {decision_id}"
        )


def _lookup_decision(bundle: dict[str, Any], decision_id: str) -> dict[str, Any]:
    for decision in bundle["project_state"]["decisions"]:
        if decision["id"] == decision_id:
            return deepcopy(decision)
    raise ValueError(f"unknown decision: {decision_id}")


def _decision_exists(bundle: dict[str, Any], decision_id: str) -> bool:
    return any(decision["id"] == decision_id for decision in bundle["project_state"]["decisions"])


def _sanitize_discovered_decision(decision: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(decision, dict):
        raise ValueError("decision must be an object")
    for key in ("id", "title"):
        if not decision.get(key):
            raise ValueError(f"decision_discovered requires {key}")
    forbidden = sorted(set(decision) & FORBIDDEN_DISCOVERED_DECISION_FIELDS)
    if forbidden:
        raise ValueError(f"decision_discovered must not include {', '.join(forbidden)}")
    allowed = DISCOVERABLE_DECISION_FIELDS | {"status"}
    unknown = sorted(set(decision) - allowed)
    if unknown:
        raise ValueError(f"decision_discovered contains unsupported fields: {', '.join(unknown)}")
    status = decision.get("status") or "unresolved"
    if status not in DISCOVERABLE_DECISION_STATUSES:
        allowed_statuses = ", ".join(sorted(DISCOVERABLE_DECISION_STATUSES))
        raise ValueError(f"decision_discovered may only create statuses: {allowed_statuses}")
    sanitized = {key: deepcopy(value) for key, value in decision.items() if key in DISCOVERABLE_DECISION_FIELDS}
    sanitized["status"] = status
    return sanitized


def _resolve_proposal_target(
    bundle: dict[str, Any], session: dict[str, Any], proposal_id: str | None
) -> dict[str, Any]:
    session_id = session["session"]["id"]
    active = session["working_state"]["active_proposal"]
    if proposal_id is None:
        if not active.get("proposal_id"):
            raise ValueError("no active proposal for this session")
        if not active.get("is_active"):
            reason = active.get("inactive_reason") or "inactive"
            raise ValueError(f"active proposal for session {session_id} is inactive: {reason}")
        stale, reason = proposal_is_stale(bundle["project_state"], session)
        if stale:
            raise ValueError(f"active proposal for session {session_id} is stale: {reason}")
        if not active.get("target_id"):
            reason = active.get("inactive_reason") or "no-active-proposal"
            raise ValueError(f"active proposal for session {session_id} is stale: {reason}")
        return _session_scoped_proposal(active, session_id)

    if active.get("proposal_id") == proposal_id:
        if not active.get("is_active"):
            reason = active.get("inactive_reason") or "inactive"
            raise ValueError(f"proposal {proposal_id} is inactive: {reason}")
        if not active.get("target_id"):
            reason = active.get("inactive_reason") or "superseded"
            raise ValueError(f"proposal {proposal_id} is {reason}")
        return _session_scoped_proposal(active, session_id)

    owner_session_id = _proposal_owner_session_id(bundle, proposal_id)
    if owner_session_id and owner_session_id != session_id:
        raise ValueError(
            f"proposal {proposal_id} belongs to session {owner_session_id}, not session {session_id}"
        )
    invalidated_decision_id = _invalidated_decision_id_for_proposal(bundle, proposal_id)
    if invalidated_decision_id:
        raise ValueError(f"proposal {proposal_id} is decision-invalidated for {invalidated_decision_id}")
    raise ValueError(f"unknown or superseded proposal for this session: {proposal_id}")


def _session_scoped_proposal(proposal: dict[str, Any], session_id: str) -> dict[str, Any]:
    origin_session_id = proposal.get("origin_session_id")
    if origin_session_id != session_id:
        raise ValueError(
            f"proposal {proposal.get('proposal_id')} belongs to session {origin_session_id}, "
            f"not session {session_id}"
        )
    return deepcopy(proposal)


def _proposal_owner_session_id(bundle: dict[str, Any], proposal_id: str) -> str | None:
    for candidate_session_id, candidate_session in bundle["sessions"].items():
        candidate = candidate_session["working_state"]["active_proposal"]
        if candidate.get("proposal_id") == proposal_id:
            return candidate.get("origin_session_id") or candidate_session_id
    return None


def _invalidated_decision_id_for_proposal(bundle: dict[str, Any], proposal_id: str) -> str | None:
    for decision in bundle["project_state"]["decisions"]:
        if (
            decision.get("recommendation", {}).get("proposal_id") == proposal_id
            and decision.get("status") == "invalidated"
        ):
            return decision["id"]
    return None


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


def _normalize(value: str) -> str:
    return " ".join(str(value).strip().casefold().split())


def _require_not_invalidated(decision_id: str, decision: dict[str, Any]) -> None:
    if decision.get("status") == "invalidated":
        raise ValueError(f"decision {decision_id} is invalidated")


def _require_decision_status(
    decision_id: str, decision: dict[str, Any], allowed_statuses: set[str], operation: str
) -> None:
    status = decision.get("status")
    if status not in allowed_statuses:
        allowed = ", ".join(sorted(allowed_statuses))
        raise ValueError(
            f"decision {decision_id} is {status} and cannot be modified by {operation}; "
            f"allowed statuses: {allowed}"
        )


def _require_acceptance_mode(mode: str) -> None:
    if mode not in ACCEPTED_VIA_VALUES - {"evidence"}:
        allowed = ", ".join(sorted(ACCEPTED_VIA_VALUES - {"evidence"}))
        raise ValueError(f"accepted_via must be one of: {allowed}")


def _require_non_empty_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must not be empty")
    return value.strip()
