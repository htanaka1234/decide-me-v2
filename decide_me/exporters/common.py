from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from decide_me.object_views import decision_views


@dataclass
class DecisionEventIndex:
    session_ids: dict[str, str] = field(default_factory=dict)
    superseded_by: dict[str, str] = field(default_factory=dict)
    supersedes: dict[str, list[str]] = field(default_factory=dict)


def build_decision_event_index(events: list[dict[str, Any]]) -> DecisionEventIndex:
    index = DecisionEventIndex()
    known_decision_ids: set[str] = set()
    for event in events:
        session_id = event["session_id"]
        payload = event["payload"]
        event_type = event["event_type"]

        if event_type == "object_recorded" and payload["object"].get("type") == "decision":
            decision_id = payload["object"]["id"]
            known_decision_ids.add(decision_id)
            index.session_ids.setdefault(decision_id, session_id)
        else:
            for decision_id in _referenced_decision_objects(event, known_decision_ids):
                index.session_ids.setdefault(decision_id, session_id)

        if event_type == "object_linked" and payload["link"]["relation"] == "supersedes":
            superseding_id = payload["link"]["source_object_id"]
            superseded_id = payload["link"]["target_object_id"]
            index.superseded_by[superseded_id] = superseding_id
            supersedes = index.supersedes.setdefault(superseding_id, [])
            if superseded_id not in supersedes:
                supersedes.append(superseded_id)

    for superseded_ids in index.supersedes.values():
        superseded_ids.sort()
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
    for decision in decision_views(bundle["project_state"]):
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


def referenced_evidence(decision: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for ref in decision.get("evidence", []):
        if ref not in refs:
            refs.append(ref)
    for ref in decision.get("resolved_by_evidence", {}).get("evidence", []):
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


def _referenced_decision_objects(event: dict[str, Any], known_decision_ids: set[str]) -> list[str]:
    payload = event["payload"]
    event_type = event["event_type"]
    if event_type in {"object_updated", "object_status_changed"} and payload["object_id"] in known_decision_ids:
        return [payload["object_id"]]
    if (
        event_type in {"session_question_asked", "session_answer_recorded"}
        and payload["target_object_id"] in known_decision_ids
    ):
        return [payload["target_object_id"]]
    if event_type == "object_linked":
        link = payload["link"]
        return [
            object_id
            for object_id in (link["source_object_id"], link["target_object_id"])
            if object_id in known_decision_ids
        ]
    return []
