from __future__ import annotations

import hashlib
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
from decide_me.events import new_entity_id, new_event_id, utc_now
from decide_me.requirement_ids import next_requirement_id
from decide_me.selector import proposal_is_stale
from decide_me.store import load_runtime, runtime_paths, transact
from decide_me.taxonomy import stable_unique


OPEN_MUTATION_STATUSES = {"unresolved", "proposed", "rejected", "blocked"}
PROPOSABLE_STATUSES = {"unresolved", "rejected", "blocked"}
PROPOSAL_RESPONSE_STATUSES = {"proposed"}
_UNSET = object()


def discover_decision(ai_dir: str, session_id: str, decision: dict[str, Any]) -> dict[str, Any]:
    sanitized_decision = _sanitize_discovered_decision(decision)
    now = utc_now()
    event_id = new_event_id()

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        _require_mutable_session(bundle, session_id)
        decision_id = sanitized_decision.get("id")
        if decision_id and _decision_exists(bundle, decision_id):
            raise ValueError(f"decision {decision_id} already exists")
        event_decision = deepcopy(sanitized_decision)
        event_decision["requirement_id"] = next_requirement_id(_decision_views(bundle))
        obj = _decision_object_from_payload(event_decision, now, event_id)
        return [
            {
                "event_id": event_id,
                "session_id": session_id,
                "event_type": "object_recorded",
                "payload": {"object": obj},
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
    agent_relevant: bool | None | object = _UNSET,
) -> dict[str, Any]:
    notes_append = [note.strip() for note in (notes_append or []) if note and note.strip()]
    revisit_triggers_append = [
        trigger.strip() for trigger in (revisit_triggers_append or []) if trigger and trigger.strip()
    ]
    context_append = context_append.strip() if context_append and context_append.strip() else None
    if agent_relevant is not _UNSET:
        _validate_agent_relevant(agent_relevant, "agent_relevant")
    updates_agent_relevance = agent_relevant is not _UNSET
    if not notes_append and not revisit_triggers_append and not context_append and not updates_agent_relevance:
        bundle = current_bundle(ai_dir)
        session = _require_mutable_session(bundle, session_id)
        _require_bound_decision(session, decision_id)
        return _lookup_decision(bundle, decision_id)

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_mutable_session(bundle, session_id)
        _require_bound_decision(session, decision_id)
        decision = _lookup_decision(bundle, decision_id)
        metadata_patch: dict[str, Any] = {}
        if notes_append:
            metadata_patch["notes"] = stable_unique([*decision.get("notes", []), *notes_append])
        if revisit_triggers_append:
            metadata_patch["revisit_triggers"] = stable_unique(
                [*decision.get("revisit_triggers", []), *revisit_triggers_append]
            )
        patch: dict[str, Any] = {"metadata": metadata_patch}
        if context_append is not None:
            existing_context = decision.get("context") or decision.get("body")
            fragments = [fragment for fragment in [existing_context, context_append] if fragment]
            context = "\n".join(stable_unique(fragment.strip() for fragment in fragments if fragment.strip()))
            patch["body"] = context
            metadata_patch["context"] = context
        if updates_agent_relevance:
            metadata_patch["agent_relevant"] = agent_relevant
        return [
            {
                "session_id": session_id,
                "event_type": "object_updated",
                "payload": {"object_id": decision_id, "patch": patch},
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
    proposal_event_id = new_event_id()
    link_event_id = new_event_id()

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_mutable_session(bundle, session_id)
        _require_bound_decision(session, decision_id)
        _require_no_other_active_proposal(session, decision_id)
        decision = _lookup_decision(bundle, decision_id)
        _require_decision_status(decision_id, decision, PROPOSABLE_STATUSES, "issue proposal")
        next_version = int(decision["recommendation"]["version"]) + 1
        proposal = _object_payload(
            object_id=proposal_id,
            object_type="proposal",
            title=recommendation,
            body=why,
            status="active",
            created_at=now,
            event_id=proposal_event_id,
            metadata={
                "origin_session_id": session_id,
                "target_type": "decision",
                "target_id": decision_id,
                "recommendation_version": next_version,
                "based_on_project_head": None,
                "question_id": question_id,
                "question": question,
                "recommendation": recommendation,
                "why": why,
                "if_not": if_not,
                "is_active": True,
                "activated_at": now,
                "inactive_reason": None,
            },
        )
        link = _link_payload(
            link_id=f"L-{proposal_id}-recommends-{decision_id}",
            source_object_id=proposal_id,
            relation="recommends",
            target_object_id=decision_id,
            rationale=why,
            created_at=now,
            event_id=link_event_id,
        )
        return [
            {
                "session_id": session_id,
                "ts": now,
                "event_type": "session_question_asked",
                "payload": {
                    "question_id": question_id,
                    "target_object_id": decision_id,
                    "question": question,
                },
            },
            {
                "session_id": session_id,
                "event_type": "object_status_changed",
                "payload": {"object_id": decision_id, "status": "proposed"},
            },
            {
                "session_id": session_id,
                "event_type": "object_updated",
                "payload": {
                    "object_id": decision_id,
                    "patch": {
                        "metadata": {
                            "question": question,
                            "last_proposal_id": proposal_id,
                            "recommendation": {
                                "proposal_id": proposal_id,
                                "version": next_version,
                                "summary": recommendation,
                                "why": why,
                                "if_not": if_not,
                            },
                        }
                    },
                },
            },
            {
                "event_id": proposal_event_id,
                "session_id": session_id,
                "event_type": "object_recorded",
                "payload": {"object": proposal},
            },
            {
                "event_id": link_event_id,
                "session_id": session_id,
                "event_type": "object_linked",
                "payload": {"link": link},
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
    accept_link_event_id = new_event_id()

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
        answer = {
            "summary": target["recommendation"],
            "answered_at": now,
            "answered_via": mode,
        }
        accept_link = _link_payload(
            link_id=f"L-{target['target_id']}-accepts-{target['proposal_id']}",
            source_object_id=target["target_id"],
            relation="accepts",
            target_object_id=target["proposal_id"],
            rationale=target["recommendation"],
            created_at=now,
            event_id=accept_link_event_id,
        )
        return [
            {
                "session_id": session_id,
                "event_type": "session_answer_recorded",
                "payload": {
                    "question_id": target["question_id"],
                    "target_object_id": target["target_id"],
                    "answer": answer,
                },
            },
            {
                "session_id": session_id,
                "event_type": "object_status_changed",
                "payload": {"object_id": target["target_id"], "status": "accepted"},
            },
            {
                "session_id": session_id,
                "event_type": "object_updated",
                "payload": {
                    "object_id": target["target_id"],
                    "patch": {"metadata": {"accepted_answer": accepted_answer}},
                },
            },
            {
                "session_id": session_id,
                "event_type": "object_status_changed",
                "payload": {"object_id": target["proposal_id"], "status": "accepted"},
            },
            {
                "event_id": accept_link_event_id,
                "session_id": session_id,
                "event_type": "object_linked",
                "payload": {"link": accept_link},
            },
        ]

    _, bundle = transact(ai_dir, builder)
    return _lookup_decision(bundle, target_id["value"])


def reject_proposal(
    ai_dir: str, session_id: str, *, reason: str, proposal_id: str | None = None
) -> dict[str, Any]:
    reason = _require_non_empty_text(reason, "reason")
    now = utc_now()
    target_id: dict[str, str] = {}

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_open_session(bundle, session_id)
        target = _resolve_proposal_target(bundle, session, proposal_id=proposal_id)
        target_id["value"] = target["target_id"]
        decision = _lookup_decision(bundle, target["target_id"])
        _require_decision_status(
            target["target_id"], decision, PROPOSAL_RESPONSE_STATUSES, "reject proposal"
        )
        answer = {
            "summary": reason,
            "answered_at": now,
            "answered_via": "explicit",
        }
        return [
            {
                "session_id": session_id,
                "event_type": "session_answer_recorded",
                "payload": {
                    "question_id": target["question_id"],
                    "target_object_id": target["target_id"],
                    "answer": answer,
                },
            },
            {
                "session_id": session_id,
                "event_type": "object_status_changed",
                "payload": {"object_id": target["target_id"], "status": "rejected"},
            },
            {
                "session_id": session_id,
                "event_type": "object_status_changed",
                "payload": {"object_id": target["proposal_id"], "status": "rejected"},
            },
            {
                "session_id": session_id,
                "event_type": "object_updated",
                "payload": {
                    "object_id": target["proposal_id"],
                    "patch": {"metadata": {"rejection_reason": reason, "inactive_reason": "rejected"}},
                },
            },
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

        matches_recommendation = _normalize(answer) == _normalize(recommendation)
        accepted_answer = {
            "summary": answer,
            "accepted_at": now,
            "accepted_via": acceptance_mode,
            "proposal_id": target["proposal_id"],
        }
        events: list[dict[str, Any]] = [
            {
                "session_id": session_id,
                "event_type": "session_answer_recorded",
                "payload": {
                    "question_id": target["question_id"],
                    "target_object_id": target["target_id"],
                    "answer": {
                        "summary": answer,
                        "answered_at": now,
                        "answered_via": acceptance_mode,
                    },
                },
            },
            {
                "session_id": session_id,
                "event_type": "object_status_changed",
                "payload": {"object_id": target["target_id"], "status": "accepted"},
            },
            {
                "session_id": session_id,
                "event_type": "object_updated",
                "payload": {
                    "object_id": target["target_id"],
                    "patch": {"metadata": {"accepted_answer": accepted_answer}},
                },
            },
        ]
        if matches_recommendation:
            link_event_id = new_event_id()
            events.extend(
                [
                    {
                        "session_id": session_id,
                        "event_type": "object_status_changed",
                        "payload": {"object_id": target["proposal_id"], "status": "accepted"},
                    },
                    {
                        "event_id": link_event_id,
                        "session_id": session_id,
                        "event_type": "object_linked",
                        "payload": {
                            "link": _link_payload(
                                link_id=f"L-{target['target_id']}-accepts-{target['proposal_id']}",
                                source_object_id=target["target_id"],
                                relation="accepts",
                                target_object_id=target["proposal_id"],
                                rationale=answer,
                                created_at=now,
                                event_id=link_event_id,
                            )
                        },
                    },
                ]
            )
        else:
            events.extend(
                [
                    {
                        "session_id": session_id,
                        "event_type": "object_status_changed",
                        "payload": {"object_id": target["proposal_id"], "status": "rejected"},
                    },
                    {
                        "session_id": session_id,
                        "event_type": "object_updated",
                        "payload": {
                            "object_id": target["proposal_id"],
                            "patch": {
                                "metadata": {
                                    "rejection_reason": normalized_reason
                                    or "User supplied an alternative answer.",
                                    "inactive_reason": "rejected",
                                }
                            },
                        },
                    },
                ]
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
                "event_type": "object_status_changed",
                "payload": {"object_id": decision_id, "status": "deferred"},
            },
            {
                "session_id": session_id,
                "event_type": "object_updated",
                "payload": {
                    "object_id": decision_id,
                    "patch": {
                        "metadata": {
                            "frontier": "deferred",
                            "notes": stable_unique([*decision.get("notes", []), reason]),
                        }
                    },
                },
            },
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
    evidence_refs = stable_unique(str(ref).strip() for ref in evidence_refs if str(ref).strip())
    now = utc_now()

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_mutable_session(bundle, session_id)
        _require_bound_decision(session, decision_id)
        _require_no_other_active_proposal(session, decision_id)
        decision = _lookup_decision(bundle, decision_id)
        _require_decision_status(
            decision_id, decision, OPEN_MUTATION_STATUSES, "resolve by evidence"
        )
        events: list[dict[str, Any]] = [
            {
                "session_id": session_id,
                "event_type": "object_status_changed",
                "payload": {"object_id": decision_id, "status": "resolved-by-evidence"},
            },
            {
                "session_id": session_id,
                "event_type": "object_updated",
                "payload": {
                    "object_id": decision_id,
                    "patch": {
                        "metadata": {
                            "resolved_by_evidence": {
                                "source": source,
                                "summary": summary,
                                "resolved_at": now,
                                "evidence_refs": deepcopy(evidence_refs),
                            },
                            "accepted_answer": {
                                "summary": summary,
                                "accepted_at": now,
                                "accepted_via": "evidence",
                                "proposal_id": None,
                            },
                        }
                    },
                },
            },
        ]
        for evidence_ref in evidence_refs:
            evidence_event_id = new_event_id()
            link_event_id = new_event_id()
            evidence_id = f"O-evidence-{_stable_id(evidence_ref)}"
            events.append(
                {
                    "event_id": evidence_event_id,
                    "session_id": session_id,
                    "event_type": "object_recorded",
                    "payload": {
                        "object": _object_payload(
                            object_id=evidence_id,
                            object_type="evidence",
                            title=evidence_ref,
                            body=summary,
                            status="active",
                            created_at=now,
                            event_id=evidence_event_id,
                            metadata={"source": source, "ref": evidence_ref},
                        )
                    },
                }
            )
            events.append(
                {
                    "event_id": link_event_id,
                    "session_id": session_id,
                    "event_type": "object_linked",
                    "payload": {
                        "link": _link_payload(
                            link_id=f"L-{evidence_id}-supports-{decision_id}",
                            source_object_id=evidence_id,
                            relation="supports",
                            target_object_id=decision_id,
                            rationale=summary,
                            created_at=now,
                            event_id=link_event_id,
                        )
                    },
                }
            )
        return events

    _, bundle = transact(ai_dir, builder)
    return _lookup_decision(bundle, decision_id)


def resolve_decision_supersession(
    ai_dir: str,
    session_id: str,
    *,
    superseded_decision_id: str,
    superseding_decision_id: str,
    reason: str,
) -> dict[str, Any]:
    reason = reason.strip()
    if not reason:
        raise ValueError("reason must not be empty")
    if superseded_decision_id == superseding_decision_id:
        raise ValueError("decision cannot supersede itself")
    now = utc_now()

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_session(bundle, session_id)
        _require_bound_decision(session, superseding_decision_id)
        target = _lookup_decision(bundle, superseded_decision_id)
        superseding = _lookup_decision(bundle, superseding_decision_id)
        _require_not_invalidated(superseded_decision_id, target)
        _require_not_invalidated(superseding_decision_id, superseding)
        if superseding["status"] not in {"accepted", "resolved-by-evidence"}:
            raise ValueError(
                f"superseding decision {superseding_decision_id} must be accepted or resolved-by-evidence"
            )
        link_event_id = new_event_id()
        return [
            {
                "session_id": session_id,
                "event_type": "object_status_changed",
                "payload": {"object_id": superseded_decision_id, "status": "invalidated"},
            },
            {
                "session_id": session_id,
                "event_type": "object_updated",
                "payload": {
                    "object_id": superseded_decision_id,
                    "patch": {
                        "metadata": {
                            "invalidated_by": {
                                "decision_id": superseding_decision_id,
                                "reason": reason,
                                "invalidated_at": now,
                            }
                        }
                    },
                },
            },
            {
                "event_id": link_event_id,
                "session_id": session_id,
                "event_type": "object_linked",
                "payload": {
                    "link": _link_payload(
                        link_id=f"L-{superseding_decision_id}-supersedes-{superseded_decision_id}",
                        source_object_id=superseding_decision_id,
                        relation="supersedes",
                        target_object_id=superseded_decision_id,
                        rationale=reason,
                        created_at=now,
                        event_id=link_event_id,
                    )
                },
            }
        ]

    events, _ = transact(ai_dir, builder)
    event = events[-1]
    resolution = {
        "kind": "decision-supersession",
        "event_type": "object_linked",
        "event_id": event["event_id"],
        "scope": {
            "kind": "decision",
            "decision_id": superseded_decision_id,
        },
        "winning_decision_id": superseding_decision_id,
        "superseded_decision_ids": [superseded_decision_id],
        "reason": reason,
    }
    return {
        "status": "ok",
        "resolution": resolution,
        "decision_id": superseded_decision_id,
        "invalidated_by_decision_id": superseding_decision_id,
        "superseded_decision_id": superseded_decision_id,
        "superseding_decision_id": superseding_decision_id,
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
    search_terms: list[str] | None = None,
    source_refs: list[str] | None = None,
) -> dict[str, Any]:
    raise ValueError("classification updates are unsupported by the Phase 5-3 event model")


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
    for decision in _decision_views(bundle):
        if decision["id"] == decision_id:
            return decision
    raise ValueError(f"unknown decision: {decision_id}")


def _decision_exists(bundle: dict[str, Any], decision_id: str) -> bool:
    return any(decision["id"] == decision_id for decision in _decision_objects(bundle))


def _decision_objects(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in bundle["project_state"].get("objects", [])
        if item.get("type") == "decision"
    ]


def _decision_views(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [_decision_view(item) for item in _decision_objects(bundle)]


def _decision_view(obj: dict[str, Any]) -> dict[str, Any]:
    metadata = deepcopy(obj.get("metadata", {}))
    accepted_answer = metadata.get("accepted_answer") or {
        "summary": None,
        "accepted_at": None,
        "accepted_via": None,
        "proposal_id": None,
    }
    resolved = metadata.get("resolved_by_evidence") or {
        "source": None,
        "summary": None,
        "resolved_at": None,
        "evidence_refs": [],
    }
    recommendation = metadata.get("recommendation") or {
        "proposal_id": metadata.get("last_proposal_id"),
        "version": 0,
        "summary": None,
        "why": None,
        "if_not": None,
    }
    view = {
        **metadata,
        "id": obj["id"],
        "title": obj.get("title"),
        "body": obj.get("body"),
        "context": metadata.get("context") or obj.get("body"),
        "status": obj.get("status"),
        "requirement_id": metadata.get("requirement_id"),
        "kind": metadata.get("kind", "choice"),
        "domain": metadata.get("domain", "other"),
        "priority": metadata.get("priority", "P1"),
        "frontier": metadata.get("frontier", "later"),
        "resolvable_by": metadata.get("resolvable_by", "human"),
        "reversibility": metadata.get("reversibility", "reversible"),
        "notes": deepcopy(metadata.get("notes", [])),
        "revisit_triggers": deepcopy(metadata.get("revisit_triggers", [])),
        "recommendation": deepcopy(recommendation),
        "accepted_answer": deepcopy(accepted_answer),
        "resolved_by_evidence": deepcopy(resolved),
        "evidence_refs": deepcopy(metadata.get("evidence_refs") or resolved.get("evidence_refs") or []),
    }
    return view


def _object_payload(
    *,
    object_id: str,
    object_type: str,
    title: str | None,
    body: str | None,
    status: str,
    created_at: str,
    event_id: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": object_id,
        "type": object_type,
        "title": title,
        "body": body,
        "status": status,
        "created_at": created_at,
        "updated_at": None,
        "source_event_ids": [event_id],
        "metadata": deepcopy(metadata or {}),
    }


def _link_payload(
    *,
    link_id: str,
    source_object_id: str,
    relation: str,
    target_object_id: str,
    rationale: str | None,
    created_at: str,
    event_id: str,
) -> dict[str, Any]:
    return {
        "id": link_id,
        "source_object_id": source_object_id,
        "relation": relation,
        "target_object_id": target_object_id,
        "rationale": rationale,
        "created_at": created_at,
        "source_event_ids": [event_id],
    }


def _decision_object_from_payload(decision: dict[str, Any], created_at: str, event_id: str) -> dict[str, Any]:
    metadata = {
        "requirement_id": decision["requirement_id"],
        "kind": decision.get("kind", "choice"),
        "domain": decision.get("domain", "other"),
        "priority": decision.get("priority", "P1"),
        "frontier": decision.get("frontier", "later"),
        "resolvable_by": decision.get("resolvable_by", "human"),
        "reversibility": decision.get("reversibility", "reversible"),
        "notes": deepcopy(decision.get("notes", [])),
        "recommendation": {
            "proposal_id": None,
            "version": 0,
            "summary": None,
            "why": None,
            "if_not": None,
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
    }
    for key in (
        "question",
        "context",
        "bundle_id",
        "agent_relevant",
        "depends_on",
        "blocked_by",
        "options",
        "revisit_triggers",
    ):
        if key in decision:
            metadata[key] = deepcopy(decision[key])
    return _object_payload(
        object_id=decision["id"],
        object_type="decision",
        title=decision["title"],
        body=decision.get("context"),
        status=decision.get("status") or "unresolved",
        created_at=created_at,
        event_id=event_id,
        metadata=metadata,
    )


def _stable_id(*parts: Any) -> str:
    material = "|".join(str(part) for part in parts)
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:12]


def _sanitize_discovered_decision(decision: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(decision, dict):
        raise ValueError("decision must be an object")
    for key in ("id", "title"):
        if not decision.get(key):
            raise ValueError(f"decision object requires {key}")
    if "requirement_id" in decision:
        raise ValueError("decision object requirement_id is assigned by the runtime")
    forbidden = sorted(set(decision) & FORBIDDEN_DISCOVERED_DECISION_FIELDS)
    if forbidden:
        raise ValueError(f"decision object must not include {', '.join(forbidden)}")
    allowed = DISCOVERABLE_DECISION_FIELDS | {"status"}
    unknown = sorted(set(decision) - allowed)
    if unknown:
        raise ValueError(f"decision object contains unsupported fields: {', '.join(unknown)}")
    status = decision.get("status") or "unresolved"
    if status not in DISCOVERABLE_DECISION_STATUSES:
        allowed_statuses = ", ".join(sorted(DISCOVERABLE_DECISION_STATUSES))
        raise ValueError(f"decision object may only be created with statuses: {allowed_statuses}")
    if "agent_relevant" in decision:
        _validate_agent_relevant(decision["agent_relevant"], "decision.agent_relevant")
    sanitized = {key: deepcopy(value) for key, value in decision.items() if key in DISCOVERABLE_DECISION_FIELDS}
    sanitized["status"] = status
    return sanitized


def _validate_agent_relevant(value: Any, label: str) -> None:
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean or null")


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
    for decision in _decision_views(bundle):
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
    for decision in _decision_views(bundle):
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
