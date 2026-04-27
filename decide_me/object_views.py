from __future__ import annotations

from copy import deepcopy
from typing import Any


def objects_by_id(project_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {obj["id"]: obj for obj in project_state.get("objects", [])}


def links_for(
    project_state: dict[str, Any],
    *,
    source_object_id: str | None = None,
    relation: str | None = None,
    target_object_id: str | None = None,
) -> list[dict[str, Any]]:
    links = []
    for link in project_state.get("links", []):
        if source_object_id is not None and link.get("source_object_id") != source_object_id:
            continue
        if relation is not None and link.get("relation") != relation:
            continue
        if target_object_id is not None and link.get("target_object_id") != target_object_id:
            continue
        links.append(link)
    return sorted(links, key=lambda item: (item.get("created_at") or "", item["id"]))


def decision_views(project_state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        decision_view(project_state, obj["id"])
        for obj in sorted(project_state.get("objects", []), key=lambda item: item["id"])
        if obj.get("type") == "decision"
    ]


def decision_view(project_state: dict[str, Any], decision_id: str) -> dict[str, Any]:
    obj = _require_object(project_state, decision_id, "decision")
    metadata = deepcopy(obj.get("metadata", {}))
    accepted = accepted_proposal_for_decision(project_state, decision_id)
    evidence = evidence_for_decision(project_state, decision_id)
    latest_proposal = latest_proposal_for_decision(project_state, decision_id)
    return {
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
        "recommendation": _recommendation_view(project_state, latest_proposal),
        "accepted_answer": _accepted_answer_view(project_state, accepted),
        "resolved_by_evidence": _evidence_resolution_view(evidence),
        "evidence_refs": [item["ref"] for item in evidence],
    }


def proposal_view(project_state: dict[str, Any], proposal_id: str) -> dict[str, Any]:
    obj = _require_object(project_state, proposal_id, "proposal")
    metadata = deepcopy(obj.get("metadata", {}))
    decision_id = proposal_decision_id(project_state, proposal_id)
    option = proposal_option(project_state, proposal_id)
    recommendation = option.get("title") if option else obj.get("title")
    return {
        "proposal_id": obj["id"],
        "origin_session_id": metadata.get("origin_session_id"),
        "target_type": "decision" if decision_id else None,
        "target_id": decision_id,
        "recommendation_version": metadata.get("recommendation_version"),
        "based_on_project_head": metadata.get("based_on_project_head"),
        "is_active": obj.get("status") == "active",
        "activated_at": metadata.get("activated_at") or obj.get("created_at"),
        "inactive_reason": metadata.get("inactive_reason") if obj.get("status") == "active" else metadata.get("inactive_reason") or obj.get("status"),
        "question_id": metadata.get("question_id"),
        "question": metadata.get("question"),
        "recommendation": recommendation,
        "why": metadata.get("why") or obj.get("body"),
        "if_not": metadata.get("if_not"),
        "object": deepcopy(obj),
        "option": deepcopy(option) if option else None,
    }


def active_proposal_view(project_state: dict[str, Any], session_state: dict[str, Any]) -> dict[str, Any] | None:
    proposal_id = session_state.get("working_state", {}).get("active_proposal_id")
    if not proposal_id:
        return None
    try:
        return proposal_view(project_state, proposal_id)
    except ValueError:
        return None


def proposal_decision_id(project_state: dict[str, Any], proposal_id: str) -> str | None:
    for link in links_for(project_state, source_object_id=proposal_id, relation="addresses"):
        target = objects_by_id(project_state).get(link["target_object_id"])
        if target and target.get("type") == "decision":
            return target["id"]
    return None


def proposal_option(project_state: dict[str, Any], proposal_id: str) -> dict[str, Any] | None:
    by_id = objects_by_id(project_state)
    for link in links_for(project_state, source_object_id=proposal_id, relation="recommends"):
        target = by_id.get(link["target_object_id"])
        if target and target.get("type") == "option":
            return target
    return None


def proposals_for_decision(project_state: dict[str, Any], decision_id: str) -> list[dict[str, Any]]:
    proposal_ids = [
        link["source_object_id"]
        for link in links_for(project_state, relation="addresses", target_object_id=decision_id)
    ]
    by_id = objects_by_id(project_state)
    return [
        by_id[proposal_id]
        for proposal_id in proposal_ids
        if proposal_id in by_id and by_id[proposal_id].get("type") == "proposal"
    ]


def latest_proposal_for_decision(project_state: dict[str, Any], decision_id: str) -> dict[str, Any] | None:
    proposals = proposals_for_decision(project_state, decision_id)
    if not proposals:
        return None
    return sorted(proposals, key=lambda item: (item.get("created_at") or "", item["id"]))[-1]


def accepted_proposal_for_decision(project_state: dict[str, Any], decision_id: str) -> dict[str, Any] | None:
    by_id = objects_by_id(project_state)
    accepted = []
    for link in links_for(project_state, source_object_id=decision_id, relation="accepts"):
        proposal = by_id.get(link["target_object_id"])
        if proposal and proposal.get("type") == "proposal":
            accepted.append(proposal)
    if not accepted:
        return None
    return sorted(accepted, key=lambda item: (item.get("updated_at") or item.get("created_at") or "", item["id"]))[-1]


def evidence_for_decision(project_state: dict[str, Any], decision_id: str) -> list[dict[str, Any]]:
    by_id = objects_by_id(project_state)
    evidence = []
    for link in links_for(project_state, relation="supports", target_object_id=decision_id):
        obj = by_id.get(link["source_object_id"])
        if not obj or obj.get("type") != "evidence":
            continue
        evidence.append(
            {
                "id": obj["id"],
                "source": obj.get("metadata", {}).get("source"),
                "ref": obj.get("metadata", {}).get("ref") or obj.get("title") or obj["id"],
                "summary": link.get("rationale") or obj.get("body"),
            }
        )
    return evidence


def related_decision_ids(project_state: dict[str, Any], related_object_ids: list[str]) -> list[str]:
    by_id = objects_by_id(project_state)
    related = set(related_object_ids)
    for link in project_state.get("links", []):
        source = link.get("source_object_id")
        target = link.get("target_object_id")
        if source in related:
            related.add(target)
        if target in related:
            related.add(source)
    return sorted(
        object_id
        for object_id in related
        if by_id.get(object_id, {}).get("type") == "decision"
    )


def _recommendation_view(project_state: dict[str, Any], proposal: dict[str, Any] | None) -> dict[str, Any]:
    if proposal is None:
        return {"proposal_id": None, "version": 0, "summary": None, "why": None, "if_not": None}
    view = proposal_view(project_state, proposal["id"])
    return {
        "proposal_id": proposal["id"],
        "version": view.get("recommendation_version") or 0,
        "summary": view.get("recommendation"),
        "why": view.get("why"),
        "if_not": view.get("if_not"),
    }


def _accepted_answer_view(project_state: dict[str, Any], proposal: dict[str, Any] | None) -> dict[str, Any]:
    if proposal is None:
        return {"summary": None, "accepted_at": None, "accepted_via": None, "proposal_id": None}
    view = proposal_view(project_state, proposal["id"])
    metadata = proposal.get("metadata", {})
    return {
        "summary": view.get("recommendation"),
        "accepted_at": proposal.get("updated_at") or proposal.get("created_at"),
        "accepted_via": metadata.get("accepted_via") or "explicit",
        "proposal_id": proposal["id"],
    }


def _evidence_resolution_view(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    if not evidence:
        return {"source": None, "summary": None, "resolved_at": None, "evidence_refs": []}
    first = evidence[0]
    return {
        "source": first.get("source"),
        "summary": first.get("summary"),
        "resolved_at": None,
        "evidence_refs": [item["ref"] for item in evidence],
    }


def _require_object(project_state: dict[str, Any], object_id: str, object_type: str | None = None) -> dict[str, Any]:
    obj = objects_by_id(project_state).get(object_id)
    if obj is None:
        raise ValueError(f"unknown object: {object_id}")
    if object_type is not None and obj.get("type") != object_type:
        raise ValueError(f"object {object_id} is not a {object_type}")
    return obj
