from __future__ import annotations

from typing import Any

from decide_me.object_views import active_proposal_view, related_decision_ids
from decide_me.projections import OPEN_DECISION_STATUSES, decision_is_invalidated, visible_decision_ids


PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}
FRONTIER_RANK = {"now": 0, "later": 1, "discovered-later": 2, "deferred": 3}


def open_decisions(project_state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in project_state["objects"]
        if item.get("type") == "decision" and item["status"] in OPEN_DECISION_STATUSES
    ]


def select_next_decision(
    project_state: dict[str, Any],
    related_object_ids: list[str] | None = None,
    *,
    scope: str = "project",
) -> dict[str, Any] | None:
    if scope not in {"project", "session"}:
        raise ValueError(f"unsupported decision selection scope: {scope}")
    if scope == "session" and related_object_ids is None:
        raise ValueError("session-scoped decision selection requires related_object_ids")

    allowed = set(related_decision_ids(project_state, related_object_ids or []))
    visible_ids = visible_decision_ids(project_state)
    if related_object_ids is not None and not allowed:
        return None
    candidates = [
        decision
        for decision in open_decisions(project_state)
        if related_object_ids is None or decision["id"] in allowed
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda decision: _decision_sort_key(project_state, decision, visible_ids))


def stop_reached(project_state: dict[str, Any]) -> bool:
    for decision in open_decisions(project_state):
        metadata = decision.get("metadata", {})
        if metadata.get("priority") == "P0" and metadata.get("frontier") == "now":
            return False
    return True


def proposal_is_stale(
    project_state: dict[str, Any], session_state: dict[str, Any]
) -> tuple[bool, str | None]:
    proposal = active_proposal_view(project_state, session_state)
    lifecycle = session_state["session"]["lifecycle"]["status"]
    if lifecycle == "closed":
        return True, "session-closed"
    if proposal is None or not proposal.get("proposal_id") or not proposal.get("is_active"):
        reason = proposal.get("inactive_reason") if proposal else None
        return True, reason or "no-active-proposal"
    target_id = proposal.get("target_id")
    if target_id:
        for decision in project_state["objects"]:
            if decision["id"] == target_id and decision_is_invalidated(decision):
                return True, "decision-invalidated"
    based_on_project_head = (
        proposal.get("based_on_project_head")
        or session_state.get("working_state", {}).get("last_seen_project_head")
    )
    if based_on_project_head and based_on_project_head != project_state["state"]["project_head"]:
        return True, "project-head-changed"
    return False, None


def _decision_sort_key(
    project_state: dict[str, Any], decision: dict[str, Any], visible_ids: set[str]
) -> tuple[int, int, int, str]:
    metadata = decision.get("metadata", {})
    dependency_count = len(
        [
            link
            for link in project_state.get("links", [])
            if link.get("source_object_id") == decision["id"]
            and link.get("relation") == "depends_on"
            and link.get("target_object_id") in visible_ids
        ]
    )
    return (
        PRIORITY_RANK.get(metadata.get("priority"), 99),
        FRONTIER_RANK.get(metadata.get("frontier"), 99),
        dependency_count,
        decision["id"],
    )
