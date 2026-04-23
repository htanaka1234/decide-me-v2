from __future__ import annotations

from typing import Any

from decide_me.projections import OPEN_DECISION_STATUSES, decision_is_invalidated, visible_decision_ids


PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}
FRONTIER_RANK = {"now": 0, "later": 1, "discovered-later": 2, "deferred": 3}


def open_decisions(project_state: dict[str, Any]) -> list[dict[str, Any]]:
    return [decision for decision in project_state["decisions"] if decision["status"] in OPEN_DECISION_STATUSES]


def select_next_decision(
    project_state: dict[str, Any],
    decision_ids: list[str] | None = None,
    *,
    scope: str = "project",
) -> dict[str, Any] | None:
    if scope not in {"project", "session"}:
        raise ValueError(f"unsupported decision selection scope: {scope}")
    if scope == "session" and decision_ids is None:
        raise ValueError("session-scoped decision selection requires decision_ids")

    allowed = set(decision_ids or [])
    visible_ids = visible_decision_ids(project_state)
    if decision_ids is not None and not allowed:
        return None
    candidates = [
        decision
        for decision in open_decisions(project_state)
        if decision_ids is None or decision["id"] in allowed
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda decision: _decision_sort_key(decision, visible_ids))


def stop_reached(project_state: dict[str, Any]) -> bool:
    for decision in open_decisions(project_state):
        if decision["priority"] == "P0" and decision["frontier"] == "now":
            return False
    return True


def proposal_is_stale(
    project_state: dict[str, Any], session_state: dict[str, Any]
) -> tuple[bool, str | None]:
    proposal = session_state["working_state"]["active_proposal"]
    lifecycle = session_state["session"]["lifecycle"]["status"]
    if lifecycle == "closed":
        return True, "session-closed"
    if not proposal.get("proposal_id") or not proposal.get("is_active"):
        return True, proposal.get("inactive_reason") or "no-active-proposal"
    target_id = proposal.get("target_id")
    if target_id:
        for decision in project_state["decisions"]:
            if decision["id"] == target_id and decision_is_invalidated(decision):
                return True, "decision-invalidated"
    if proposal.get("based_on_project_version") != project_state["state"]["project_version"]:
        return True, "project-version-changed"
    return False, None


def _decision_sort_key(decision: dict[str, Any], visible_ids: set[str]) -> tuple[int, int, int, str]:
    return (
        PRIORITY_RANK.get(decision["priority"], 99),
        FRONTIER_RANK.get(decision["frontier"], 99),
        len([candidate for candidate in decision.get("depends_on", []) if candidate in visible_ids]),
        decision["id"],
    )
