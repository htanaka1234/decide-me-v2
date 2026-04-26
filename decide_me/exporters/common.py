from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DecisionEventIndex:
    session_ids: dict[str, str] = field(default_factory=dict)
    superseded_by: dict[str, str] = field(default_factory=dict)
    supersedes: dict[str, list[str]] = field(default_factory=dict)


def build_decision_event_index(events: list[dict[str, Any]]) -> DecisionEventIndex:
    index = DecisionEventIndex()
    for event in events:
        session_id = event["session_id"]
        payload = event["payload"]
        event_type = event["event_type"]

        if event_type == "decision_discovered":
            decision_id = payload["decision"]["id"]
            index.session_ids.setdefault(decision_id, session_id)
        else:
            for decision_id in _referenced_decision_ids(event):
                index.session_ids.setdefault(decision_id, session_id)

        if event_type == "decision_invalidated":
            superseded_id = payload["decision_id"]
            superseding_id = payload["invalidated_by_decision_id"]
            index.superseded_by[superseded_id] = superseding_id
            supersedes = index.supersedes.setdefault(superseding_id, [])
            if superseded_id not in supersedes:
                supersedes.append(superseded_id)

    for decision_ids in index.supersedes.values():
        decision_ids.sort()
    return index


def decision_summary(decision: dict[str, Any]) -> str | None:
    accepted_summary = decision.get("accepted_answer", {}).get("summary")
    if accepted_summary:
        return accepted_summary
    evidence_summary = decision.get("resolved_by_evidence", {}).get("summary")
    if evidence_summary:
        return evidence_summary
    return None


def lookup_decision(bundle: dict[str, Any], decision_id: str) -> dict[str, Any]:
    for decision in bundle["project_state"]["decisions"]:
        if decision["id"] == decision_id:
            return decision
    raise ValueError(f"unknown decision: {decision_id}")


def snapshot_generated_at(bundle: dict[str, Any], events: list[dict[str, Any]]) -> str | None:
    updated_at = bundle["project_state"].get("state", {}).get("updated_at")
    if updated_at:
        return updated_at
    if events:
        return events[-1]["ts"]
    return None


def project_head(bundle: dict[str, Any]) -> str | None:
    return bundle["project_state"].get("state", {}).get("project_head")


def referenced_evidence_refs(decision: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for ref in decision.get("evidence_refs", []):
        if ref not in refs:
            refs.append(ref)
    for ref in decision.get("resolved_by_evidence", {}).get("evidence_refs", []):
        if ref not in refs:
            refs.append(ref)
    return refs


def superseded_by(decision: dict[str, Any], index: DecisionEventIndex) -> str | None:
    decision_id = decision["id"]
    indexed = index.superseded_by.get(decision_id)
    if indexed:
        return indexed
    invalidated_by = decision.get("invalidated_by")
    if invalidated_by:
        return invalidated_by.get("decision_id")
    return None


def _referenced_decision_ids(event: dict[str, Any]) -> list[str]:
    payload = event["payload"]
    event_type = event["event_type"]
    if event_type == "proposal_issued":
        return [payload["proposal"]["target_id"]]
    if event_type in {"proposal_accepted", "proposal_rejected"}:
        return [payload["target_id"]]
    if event_type in {
        "decision_enriched",
        "question_asked",
        "decision_deferred",
        "decision_resolved_by_evidence",
    }:
        return [payload["decision_id"]]
    if event_type == "decision_invalidated":
        return [payload["decision_id"], payload["invalidated_by_decision_id"]]
    return []
