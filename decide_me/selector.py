from __future__ import annotations

from typing import Any

from decide_me.projections import OPEN_DECISION_STATUSES


PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}
FRONTIER_RANK = {"now": 0, "later": 1, "discovered-later": 2, "deferred": 3}


def open_decisions(project_state: dict[str, Any]) -> list[dict[str, Any]]:
    return [decision for decision in project_state["decisions"] if decision["status"] in OPEN_DECISION_STATUSES]


def select_next_decision(
    project_state: dict[str, Any], decision_ids: list[str] | None = None
) -> dict[str, Any] | None:
    allowed = set(decision_ids or [])
    candidates = [
        decision
        for decision in open_decisions(project_state)
        if not allowed or decision["id"] in allowed
    ]
    if not candidates:
        return None
    return min(candidates, key=_decision_sort_key)


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
    if proposal.get("based_on_project_version") != project_state["state"]["project_version"]:
        return True, "project-version-changed"
    return False, None


def _decision_sort_key(decision: dict[str, Any]) -> tuple[int, int, int, str]:
    return (
        PRIORITY_RANK.get(decision["priority"], 99),
        FRONTIER_RANK.get(decision["frontier"], 99),
        len(decision.get("depends_on", [])),
        decision["id"],
    )
