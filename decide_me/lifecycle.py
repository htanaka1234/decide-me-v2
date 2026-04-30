from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Callable

from decide_me.domains import DomainPack, domain_pack_digest, load_domain_registry
from decide_me.object_views import active_proposal_view, links_for, objects_by_id
from decide_me.events import new_entity_id, new_event_id, utc_now
from decide_me.projections import OPEN_DECISION_STATUSES, decision_is_invalidated, effective_session_status
from decide_me.search import search_sessions, session_list_entry
from decide_me.store import load_runtime, runtime_paths, transact
from decide_me.taxonomy import resolved_tag_nodes, stable_unique


CLOSE_SUMMARY_TRAVERSAL_RELATIONS = {
    "addresses",
    "recommends",
    "accepts",
    "supports",
    "verifies",
    "revisits",
    "blocked_by",
    "challenges",
}


def create_session(
    ai_dir: str,
    context: str | None = None,
    *,
    domain_pack_id: str | None = None,
) -> dict[str, Any]:
    session_id = new_entity_id("S")
    now = utc_now()
    domain_pack = _select_domain_pack(ai_dir, context=context, domain_pack_id=domain_pack_id)
    classification = _domain_pack_classification(domain_pack, now)

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
                        "classification": classification,
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
    domain_packs: list[str] | None = None,
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
        domain_packs=domain_packs,
        abstraction_levels=abstraction_levels,
        tag_terms=tag_terms,
    )
    return {
        "status": "ok",
        "filters": {
            "query": query,
            "status": statuses or [],
            "domain": domains or [],
            "domain_pack": domain_packs or [],
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


def close_session(
    ai_dir: str,
    session_id: str,
    *,
    now: str | None = None,
    tx_id: str | None = None,
    event_id_prefix: str | None = None,
) -> dict[str, Any]:
    fixed_now = now is not None
    closed_at = now or utc_now()
    event_id_factory = _event_id_factory(event_id_prefix)

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_session(bundle, session_id)
        if session["session"]["lifecycle"]["status"] == "closed":
            raise ValueError(f"session {session_id} is already closed")
        action_events, action_ids, action_link_ids = _close_session_action_events(
            bundle["project_state"],
            session,
            closed_at,
            event_id_factory=event_id_factory,
        )
        close_summary = build_close_summary(
            bundle["project_state"],
            session,
            action_ids=action_ids,
            action_link_ids=action_link_ids,
        )
        close_summary["generated_at"] = closed_at
        events = [
            *_proposal_boundary_status_events(
                bundle,
                session,
                closed_at,
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
                "payload": {"closed_at": closed_at},
            },
        ]
        if fixed_now:
            for event in events:
                event.setdefault("ts", closed_at)
        if event_id_factory is not None:
            for event in events:
                if "event_id" not in event:
                    event["event_id"] = event_id_factory()
        return events

    _, bundle = transact(ai_dir, builder, tx_id=tx_id)
    return bundle["sessions"][session_id]


def _event_id_factory(prefix: str | None) -> Callable[[], str] | None:
    if prefix is None:
        return None
    counter = 0

    def next_event_id() -> str:
        nonlocal counter
        counter += 1
        return f"{prefix}-{counter:04d}"

    return next_event_id


def build_close_summary(
    project_state: dict[str, Any],
    session_state: dict[str, Any],
    *,
    action_ids: list[str] | None = None,
    action_link_ids: list[str] | None = None,
) -> dict[str, Any]:
    by_id = objects_by_id(project_state)
    subset_object_ids, subset_link_ids = _session_graph_subset(
        project_state,
        session_state,
        extra_object_ids=action_ids or [],
    )
    session_decision_ids = _session_summary_decision_ids(project_state, session_state, subset_object_ids)
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
    subset_objects = [by_id[object_id] for object_id in subset_object_ids if object_id in by_id]
    risk_ids = stable_unique(
        [
            *[
                decision["id"]
                for decision in decisions
                if _decision_metadata(decision).get("kind") == "risk"
                and decision.get("status") in OPEN_DECISION_STATUSES
            ],
            *[obj["id"] for obj in subset_objects if obj.get("type") == "risk"],
        ]
    )
    evidence_ids = stable_unique(obj["id"] for obj in subset_objects if obj.get("type") == "evidence")
    verification_ids = stable_unique(obj["id"] for obj in subset_objects if obj.get("type") == "verification")
    revisit_trigger_ids = stable_unique(obj["id"] for obj in subset_objects if obj.get("type") == "revisit_trigger")
    summary_action_ids = _summary_action_ids(
        project_state,
        session_state,
        subset_object_ids,
        accepted_decision_ids,
        action_ids or [],
    )
    link_ids = stable_unique([*(action_link_ids or []), *subset_link_ids])

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


def _select_domain_pack(
    ai_dir: str,
    *,
    context: str | None,
    domain_pack_id: str | None,
) -> DomainPack:
    registry = load_domain_registry(ai_dir)
    if domain_pack_id is None:
        selected_pack_id = registry.infer_from_context(context or "")
    else:
        selected_pack_id = domain_pack_id.strip()
        if not selected_pack_id:
            raise ValueError("domain pack must be a non-empty string")
    try:
        return registry.get(selected_pack_id)
    except KeyError as exc:
        raise ValueError(f"unknown domain pack: {selected_pack_id}") from exc


def _domain_pack_classification(pack: DomainPack, updated_at: str) -> dict[str, Any]:
    return {
        "domain": pack.default_core_domain,
        "abstraction_level": None,
        "domain_pack_id": pack.pack_id,
        "domain_pack_version": pack.version,
        "domain_pack_digest": domain_pack_digest(pack),
        "assigned_tags": [],
        "search_terms": [],
        "source_refs": [],
        "updated_at": updated_at,
    }


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
    *,
    event_id_factory: Callable[[], str] | None = None,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    by_id = objects_by_id(project_state)
    link_by_id = {link["id"]: link for link in project_state.get("links", [])}
    session_decision_ids = _session_action_decision_ids(project_state, session_state)
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
            event_id = event_id_factory() if event_id_factory is not None else new_event_id()
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
        event_id = event_id_factory() if event_id_factory is not None else new_event_id()
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


def _session_summary_decision_ids(
    project_state: dict[str, Any],
    session_state: dict[str, Any],
    subset_object_ids: list[str],
) -> list[str]:
    by_id = objects_by_id(project_state)
    final_decision_ids = set(_session_final_decision_ids(project_state, session_state, for_action_generation=False))
    return stable_unique(
        object_id
        for object_id in subset_object_ids
        if by_id.get(object_id, {}).get("type") == "decision"
        and not decision_is_invalidated(by_id[object_id])
        and (
            by_id[object_id].get("status") not in {"accepted", "resolved-by-evidence"}
            or object_id in final_decision_ids
            or _decision_has_related_summary_anchor(project_state, session_state, object_id)
        )
    )


def _session_action_decision_ids(project_state: dict[str, Any], session_state: dict[str, Any]) -> list[str]:
    by_id = objects_by_id(project_state)
    return stable_unique(
        decision_id
        for decision_id in _session_final_decision_ids(project_state, session_state, for_action_generation=True)
        if by_id.get(decision_id, {}).get("type") == "decision"
        and by_id[decision_id].get("status") in {"accepted", "resolved-by-evidence"}
        and not decision_is_invalidated(by_id[decision_id])
    )


def _decision_has_related_summary_anchor(
    project_state: dict[str, Any],
    session_state: dict[str, Any],
    decision_id: str,
) -> bool:
    by_id = objects_by_id(project_state)
    related_ids = set(session_state["session"].get("related_object_ids", []))
    for link in project_state.get("links", []):
        if link.get("relation") not in CLOSE_SUMMARY_TRAVERSAL_RELATIONS:
            continue
        source_id = link.get("source_object_id")
        target_id = link.get("target_object_id")
        if source_id == decision_id:
            other_id = target_id
        elif target_id == decision_id:
            other_id = source_id
        else:
            continue
        other = by_id.get(other_id)
        if other_id in related_ids and other and other.get("type") != "decision":
            return True
    return False


def _session_final_decision_ids(
    project_state: dict[str, Any],
    session_state: dict[str, Any],
    *,
    for_action_generation: bool,
) -> list[str]:
    by_id = objects_by_id(project_state)
    session_id = session_state["session"]["id"]
    related_ids = set(session_state["session"].get("related_object_ids", []))
    final_ids: list[str] = []

    for link in project_state.get("links", []):
        relation = link.get("relation")
        source_id = link.get("source_object_id")
        target_id = link.get("target_object_id")
        source = by_id.get(source_id)
        target = by_id.get(target_id)
        if relation == "accepts":
            if (
                source
                and target
                and source.get("type") == "decision"
                and target.get("type") == "proposal"
                and source.get("status") == "accepted"
                and (
                    target.get("metadata", {}).get("origin_session_id") == session_id
                    or target_id in related_ids
                )
            ):
                final_ids.append(source_id)
        elif relation == "supports":
            if (
                source
                and target
                and source.get("type") == "evidence"
                and target.get("type") == "decision"
                and target.get("status") == "resolved-by-evidence"
                and source_id in related_ids
                and (not for_action_generation or target_id in related_ids)
            ):
                final_ids.append(target_id)
    return stable_unique(final_ids)


def _session_graph_subset(
    project_state: dict[str, Any],
    session_state: dict[str, Any],
    *,
    extra_object_ids: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    by_id = objects_by_id(project_state)
    links = project_state.get("links", [])
    session_id = session_state["session"]["id"]
    seeds = stable_unique(
        [*session_state["session"].get("related_object_ids", []), *(extra_object_ids or [])]
    )
    seed_action_ids = {
        object_id
        for object_id in seeds
        if by_id.get(object_id, {}).get("type") == "action"
    }
    extra_ids = set(extra_object_ids or [])
    visited: set[str] = set()
    visited_order: list[str] = []
    link_ids: list[str] = []
    queue = list(seeds)

    while queue:
        object_id = queue.pop(0)
        if object_id in visited:
            continue
        if not _allow_session_graph_object(
            by_id.get(object_id),
            object_id,
            session_id,
            seed_action_ids,
            extra_ids,
        ):
            continue
        visited.add(object_id)
        visited_order.append(object_id)
        for link in links:
            if link.get("relation") not in CLOSE_SUMMARY_TRAVERSAL_RELATIONS:
                continue
            source_id = link.get("source_object_id")
            target_id = link.get("target_object_id")
            if source_id != object_id and target_id != object_id:
                continue
            other_id = target_id if source_id == object_id else source_id
            if not _allow_session_graph_object(
                by_id.get(other_id),
                other_id,
                session_id,
                seed_action_ids,
                extra_ids,
            ):
                continue
            link_ids.append(link["id"])
            if other_id not in visited:
                queue.append(other_id)

    return stable_unique(visited_order), stable_unique(link_ids)


def _allow_session_graph_object(
    obj: dict[str, Any] | None,
    object_id: str | None,
    session_id: str,
    seed_action_ids: set[str],
    extra_object_ids: set[str],
) -> bool:
    if not object_id:
        return False
    if object_id in extra_object_ids:
        return True
    if obj is None:
        return False
    if obj.get("type") != "action":
        return True
    return object_id in seed_action_ids or obj.get("metadata", {}).get("origin_session_id") == session_id


def _summary_action_ids(
    project_state: dict[str, Any],
    session_state: dict[str, Any],
    subset_object_ids: list[str],
    accepted_decision_ids: list[str],
    generated_action_ids: list[str],
) -> list[str]:
    by_id = objects_by_id(project_state)
    seed_action_ids = [
        object_id
        for object_id in session_state["session"].get("related_object_ids", [])
        if by_id.get(object_id, {}).get("type") == "action"
    ]
    existing_action_ids = [
        object_id
        for object_id in subset_object_ids
        if by_id.get(object_id, {}).get("type") == "action"
        and by_id[object_id].get("metadata", {}).get("origin_session_id") == session_state["session"]["id"]
    ]
    accepted_ids = set(accepted_decision_ids)
    return stable_unique(
        [
            *generated_action_ids,
            *[
                action_id
                for action_id in [*seed_action_ids, *existing_action_ids]
                if _action_addresses_accepted_decision(project_state, action_id, accepted_ids)
            ],
        ]
    )


def _action_addresses_accepted_decision(
    project_state: dict[str, Any],
    action_id: str,
    accepted_decision_ids: set[str],
) -> bool:
    return any(
        link.get("source_object_id") == action_id
        and link.get("relation") == "addresses"
        and link.get("target_object_id") in accepted_decision_ids
        for link in project_state.get("links", [])
    )


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
            "evidence": [item["ref"] for item in evidence],
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
                    "ref": obj.get("metadata", {}).get("source_ref") or obj.get("title") or obj["id"],
                    "summary": link.get("rationale") or obj.get("body"),
                }
            )
    return evidence


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
