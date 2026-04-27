from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from decide_me.object_views import active_proposal_view, links_for, objects_by_id, related_decision_ids
from decide_me.events import new_entity_id, new_event_id, utc_now
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
        action_events, action_ids, action_link_ids = _close_session_action_events(
            bundle["project_state"],
            session,
            now,
        )
        close_summary = build_close_summary(
            bundle["project_state"],
            session,
            action_ids=action_ids,
            action_link_ids=action_link_ids,
        )
        close_summary["generated_at"] = now
        return [
            *_proposal_boundary_status_events(
                bundle,
                session,
                now,
                "Session closed with unresolved active proposal.",
            ),
            *action_events,
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


def build_close_summary(
    project_state: dict[str, Any],
    session_state: dict[str, Any],
    *,
    action_ids: list[str] | None = None,
    action_link_ids: list[str] | None = None,
) -> dict[str, Any]:
    by_id = objects_by_id(project_state)
    session_decision_ids = related_decision_ids(
        project_state, session_state["session"].get("related_object_ids", [])
    )
    decisions = [
        by_id[decision_id]
        for decision_id in session_decision_ids
        if decision_id in by_id
        and by_id[decision_id].get("type") == "decision"
        and not decision_is_invalidated(by_id[decision_id])
    ]
    accepted_decision_ids = [
        decision["id"]
        for decision in decisions
        if decision.get("status") in {"accepted", "resolved-by-evidence"}
    ]
    deferred_decision_ids = [decision["id"] for decision in decisions if decision.get("status") == "deferred"]
    blocker_ids = [
        decision["id"]
        for decision in decisions
        if _decision_metadata(decision).get("priority") == "P0"
        and _decision_metadata(decision).get("frontier") == "now"
        and decision.get("status") in OPEN_DECISION_STATUSES
    ]
    risk_ids = _risk_object_ids(project_state, decisions)
    evidence_ids = _related_source_ids(project_state, session_decision_ids, relation="supports", object_type="evidence")
    verification_ids = _related_source_ids(
        project_state,
        stable_unique([*session_decision_ids, *(action_ids or [])]),
        relation="verifies",
        object_type="verification",
    )
    revisit_trigger_ids = _related_source_ids(
        project_state,
        session_decision_ids,
        relation="revisits",
        object_type="revisit_trigger",
    )
    summary_action_ids = stable_unique([*(action_ids or []), *_existing_action_ids(project_state, accepted_decision_ids)])

    related_ids = stable_unique(
        [
            *session_decision_ids,
            *accepted_decision_ids,
            *deferred_decision_ids,
            *blocker_ids,
            *risk_ids,
            *summary_action_ids,
            *evidence_ids,
            *verification_ids,
            *revisit_trigger_ids,
        ]
    )
    link_ids = stable_unique(
        [
            *(action_link_ids or []),
            *[
                link["id"]
                for link in project_state.get("links", [])
                if link.get("source_object_id") in related_ids or link.get("target_object_id") in related_ids
            ],
        ]
    )

    readiness = "ready"
    if blocker_ids:
        readiness = "blocked"
    elif risk_ids:
        readiness = "conditional"

    bound_context = session_state["session"].get("bound_context_hint")
    latest_summary = session_state["summary"].get("latest_summary")
    current_question = session_state["summary"].get("current_question_preview")

    return {
        "work_item": {
            "title": bound_context or latest_summary or session_state["session"]["id"],
            "statement": current_question or latest_summary or bound_context,
            "objective_object_id": _objective_object_id(project_state),
        },
        "readiness": readiness,
        "object_ids": {
            "decisions": stable_unique(session_decision_ids),
            "accepted_decisions": stable_unique(accepted_decision_ids),
            "deferred_decisions": stable_unique(deferred_decision_ids),
            "blockers": stable_unique(blocker_ids),
            "risks": stable_unique(risk_ids),
            "actions": stable_unique(summary_action_ids),
            "evidence": stable_unique(evidence_ids),
            "verifications": stable_unique(verification_ids),
            "revisit_triggers": stable_unique(revisit_trigger_ids),
        },
        "link_ids": stable_unique(link_ids),
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
    active = active_proposal_view(bundle["project_state"], session)
    if not active or not active.get("is_active"):
        return []
    events = [
        {
            "session_id": session["session"]["id"],
            "event_type": "object_status_changed",
            "payload": {
                "object_id": active["proposal_id"],
                "from_status": "active",
                "to_status": "inactive",
                "reason": reason,
                "changed_at": changed_at,
            },
        },
        {
            "session_id": session["session"]["id"],
            "event_type": "object_updated",
            "payload": {
                "object_id": active["proposal_id"],
                "patch": {"metadata": {"inactive_reason": "session-boundary"}},
            },
        },
    ]
    target_id = active.get("target_id")
    if target_id:
        for obj in bundle["project_state"].get("objects", []):
            if obj.get("id") == target_id and obj.get("type") == "decision" and obj.get("status") == "proposed":
                events.append(
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
                )
                break
    return events


def _close_session_action_events(
    project_state: dict[str, Any],
    session_state: dict[str, Any],
    created_at: str,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    by_id = objects_by_id(project_state)
    link_by_id = {link["id"]: link for link in project_state.get("links", [])}
    session_decision_ids = related_decision_ids(
        project_state, session_state["session"].get("related_object_ids", [])
    )
    events: list[dict[str, Any]] = []
    action_ids: list[str] = []
    action_link_ids: list[str] = []
    for decision_id in session_decision_ids:
        decision = by_id.get(decision_id)
        if not decision or decision.get("type") != "decision":
            continue
        if decision.get("status") not in {"accepted", "resolved-by-evidence"}:
            continue
        action_id = _action_object_id(session_state["session"]["id"], decision_id)
        link_id = _action_addresses_link_id(action_id, decision_id)
        action_ids.append(action_id)
        action_link_ids.append(link_id)
        summary = _decision_resolution_summary(project_state, decision)
        action = _action_object(project_state, decision, action_id, session_state["session"]["id"], summary, created_at)
        existing_action = by_id.get(action_id)
        if existing_action is not None and existing_action.get("type") != "action":
            raise ValueError(f"deterministic action id {action_id} already exists as {existing_action.get('type')}")
        if existing_action is None:
            event_id = new_event_id()
            action["source_event_ids"] = [event_id]
            events.append(
                {
                    "event_id": event_id,
                    "session_id": session_state["session"]["id"],
                    "event_type": "object_recorded",
                    "payload": {"object": action},
                }
            )
            by_id[action_id] = action
        link = _link_payload(
            link_id=link_id,
            source_object_id=action_id,
            relation="addresses",
            target_object_id=decision_id,
            rationale=summary,
            created_at=created_at,
            event_id="",
        )
        existing_link = link_by_id.get(link_id)
        if existing_link is not None:
            if (
                existing_link.get("source_object_id") != action_id
                or existing_link.get("relation") != "addresses"
                or existing_link.get("target_object_id") != decision_id
            ):
                raise ValueError(f"deterministic action link id {link_id} already exists with different endpoints")
            continue
        event_id = new_event_id()
        link["source_event_ids"] = [event_id]
        events.append(
            {
                "event_id": event_id,
                "session_id": session_state["session"]["id"],
                "event_type": "object_linked",
                "payload": {"link": link},
            }
        )
        link_by_id[link_id] = link
    return events, stable_unique(action_ids), stable_unique(action_link_ids)


def _action_object(
    project_state: dict[str, Any],
    decision: dict[str, Any],
    action_id: str,
    session_id: str,
    summary: str | None,
    created_at: str,
) -> dict[str, Any]:
    metadata = _decision_metadata(decision)
    evidence = _decision_evidence(project_state, decision["id"])
    resolvable_by = metadata.get("resolvable_by", "human")
    return {
        "id": action_id,
        "type": "action",
        "title": decision.get("title") or decision["id"],
        "body": summary,
        "status": "active",
        "created_at": created_at,
        "updated_at": None,
        "source_event_ids": [],
        "metadata": {
            "origin_session_id": session_id,
            "decision_id": decision["id"],
            "responsibility": metadata.get("domain", "other"),
            "priority": metadata.get("priority", "P1"),
            "decision_status": decision.get("status"),
            "kind": metadata.get("kind", "choice"),
            "resolvable_by": resolvable_by,
            "reversibility": metadata.get("reversibility", "reversible"),
            "implementation_ready": _implementation_ready(decision, summary),
            "evidence_backed": bool(evidence),
            "evidence_source": evidence[0].get("source") if evidence else None,
            "evidence_refs": [item["ref"] for item in evidence],
            "next_step": _action_next_step(decision),
        },
    }


def _implementation_ready(decision: dict[str, Any], summary: str | None) -> bool:
    metadata = _decision_metadata(decision)
    if decision.get("status") == "resolved-by-evidence":
        return True
    return metadata.get("resolvable_by") in {"codebase", "docs", "tests"} and bool(summary)


def _action_next_step(decision: dict[str, Any]) -> str:
    subject = decision.get("title") or decision["id"]
    resolvable_by = _decision_metadata(decision).get("resolvable_by", "human")
    if resolvable_by == "codebase":
        return f"Implement {subject}."
    if resolvable_by == "docs":
        return f"Document {subject}."
    if resolvable_by == "tests":
        return f"Add tests for {subject}."
    if resolvable_by == "external":
        return f"Coordinate the external dependency for {subject}."
    return f"Drive {subject} to completion."


def _decision_metadata(decision: dict[str, Any]) -> dict[str, Any]:
    return decision.get("metadata", {})


def _decision_resolution_summary(project_state: dict[str, Any], decision: dict[str, Any]) -> str | None:
    if decision.get("status") == "accepted":
        proposal = _accepted_proposal(project_state, decision["id"])
        if proposal:
            option = _recommended_option(project_state, proposal["id"])
            return option.get("title") if option else proposal.get("title") or proposal.get("body")
    evidence = _decision_evidence(project_state, decision["id"])
    if evidence:
        return evidence[0].get("summary") or evidence[0].get("ref")
    return None


def _accepted_proposal(project_state: dict[str, Any], decision_id: str) -> dict[str, Any] | None:
    by_id = objects_by_id(project_state)
    proposals = []
    for link in links_for(project_state, source_object_id=decision_id, relation="accepts"):
        proposal = by_id.get(link["target_object_id"])
        if proposal and proposal.get("type") == "proposal":
            proposals.append(proposal)
    if not proposals:
        return None
    return sorted(proposals, key=lambda item: (item.get("updated_at") or item.get("created_at") or "", item["id"]))[-1]


def _recommended_option(project_state: dict[str, Any], proposal_id: str) -> dict[str, Any] | None:
    by_id = objects_by_id(project_state)
    for link in links_for(project_state, source_object_id=proposal_id, relation="recommends"):
        option = by_id.get(link["target_object_id"])
        if option and option.get("type") == "option":
            return option
    return None


def _decision_evidence(project_state: dict[str, Any], decision_id: str) -> list[dict[str, Any]]:
    by_id = objects_by_id(project_state)
    evidence = []
    for link in links_for(project_state, relation="supports", target_object_id=decision_id):
        obj = by_id.get(link["source_object_id"])
        if obj and obj.get("type") == "evidence":
            evidence.append(
                {
                    "id": obj["id"],
                    "source": obj.get("metadata", {}).get("source"),
                    "ref": obj.get("metadata", {}).get("ref") or obj.get("title") or obj["id"],
                    "summary": link.get("rationale") or obj.get("body"),
                }
            )
    return evidence


def _risk_object_ids(project_state: dict[str, Any], decisions: list[dict[str, Any]]) -> list[str]:
    decision_ids = {decision["id"] for decision in decisions}
    risks = [
        decision["id"]
        for decision in decisions
        if _decision_metadata(decision).get("kind") == "risk"
        and decision.get("status") in OPEN_DECISION_STATUSES
    ]
    for obj in project_state.get("objects", []):
        if obj.get("type") != "risk":
            continue
        if obj.get("id") in decision_ids or any(
            link.get("source_object_id") == obj["id"] and link.get("target_object_id") in decision_ids
            or link.get("target_object_id") == obj["id"] and link.get("source_object_id") in decision_ids
            for link in project_state.get("links", [])
        ):
            risks.append(obj["id"])
    return stable_unique(risks)


def _related_source_ids(
    project_state: dict[str, Any],
    target_ids: list[str],
    *,
    relation: str,
    object_type: str,
) -> list[str]:
    by_id = objects_by_id(project_state)
    targets = set(target_ids)
    return stable_unique(
        link["source_object_id"]
        for link in project_state.get("links", [])
        if link.get("relation") == relation
        and link.get("target_object_id") in targets
        and by_id.get(link.get("source_object_id"), {}).get("type") == object_type
    )


def _existing_action_ids(project_state: dict[str, Any], decision_ids: list[str]) -> list[str]:
    by_id = objects_by_id(project_state)
    decisions = set(decision_ids)
    return stable_unique(
        link["source_object_id"]
        for link in project_state.get("links", [])
        if link.get("relation") == "addresses"
        and link.get("target_object_id") in decisions
        and by_id.get(link.get("source_object_id"), {}).get("type") == "action"
    )


def _objective_object_id(project_state: dict[str, Any]) -> str | None:
    by_id = objects_by_id(project_state)
    if by_id.get("O-project-objective", {}).get("type") == "objective":
        return "O-project-objective"
    for obj in project_state.get("objects", []):
        if obj.get("type") == "objective":
            return obj["id"]
    return None


def _action_object_id(session_id: str, decision_id: str) -> str:
    return f"O-action-{_short_hash(session_id, decision_id)}"


def _action_addresses_link_id(action_id: str, decision_id: str) -> str:
    return f"L-{action_id}-addresses-{decision_id}"


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
        "source_event_ids": [event_id] if event_id else [],
    }


def _short_hash(*parts: Any) -> str:
    material = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:12]
