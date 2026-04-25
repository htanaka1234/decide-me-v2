from __future__ import annotations

from copy import deepcopy
from typing import Any

from decide_me.events import utc_now
from decide_me.exports import export_plan
from decide_me.store import load_runtime, runtime_paths, transact
from decide_me.taxonomy import stable_unique


def generate_plan(ai_dir: str, session_ids: list[str]) -> dict[str, Any]:
    if not session_ids:
        raise ValueError("at least one closed session is required to generate a plan")

    bundle = load_runtime(runtime_paths(ai_dir))
    sessions = []
    for session_id in session_ids:
        session = bundle["sessions"].get(session_id)
        if not session:
            raise ValueError(f"unknown session: {session_id}")
        if session["session"]["lifecycle"]["status"] != "closed":
            raise ValueError(f"session {session_id} must be closed before plan generation")
        sessions.append(session)

    plan = {
        "generated_at": utc_now(),
        "source_session_ids": session_ids,
        "status": None,
        "conflicts": [],
        "action_plan": None,
    }

    conflicts = detect_conflicts(sessions)
    if conflicts:
        plan["status"] = "conflicts"
        plan["conflicts"] = conflicts
    else:
        plan["status"] = "action-plan"
        plan["action_plan"] = assemble_action_plan(sessions)

    output = export_plan(ai_dir, plan)
    plan["export_path"] = str(output)
    _record_plan_generated(ai_dir, plan)
    return plan


def detect_conflicts(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    accepted_by_id: dict[str, tuple[str | None, str]] = {}
    workstreams_by_name: dict[str, tuple[set[str], str]] = {}
    actions_by_name: dict[str, tuple[str, str]] = {}

    for session in sessions:
        close_summary = session["close_summary"]
        session_id = session["session"]["id"]

        for decision in close_summary["accepted_decisions"]:
            previous = accepted_by_id.get(decision["id"])
            current_answer = decision.get("accepted_answer")
            if previous and previous[0] != current_answer:
                conflicts.append(
                    {
                        "kind": "accepted-answer-mismatch",
                        "decision_id": decision["id"],
                        "session_ids": [previous[1], session_id],
                        "summary": "Accepted answers differ for the same decision.",
                    }
                )
            else:
                accepted_by_id[decision["id"]] = (current_answer, session_id)

        for workstream in close_summary["candidate_workstreams"]:
            name = workstream["name"]
            scope = set(workstream.get("scope", []))
            previous = workstreams_by_name.get(name)
            if previous and previous[0] & scope and previous[0] != scope:
                conflicts.append(
                    {
                        "kind": "workstream-scope-mismatch",
                        "name": name,
                        "session_ids": [previous[1], session_id],
                        "summary": "Workstream scope differs across sessions.",
                    }
                )
            else:
                merged = set(previous[0]) if previous else set()
                merged.update(scope)
                workstreams_by_name[name] = (merged, session_id)

        for action_slice in close_summary["candidate_action_slices"]:
            name = action_slice["name"]
            responsibility = action_slice.get("responsibility")
            previous = actions_by_name.get(name)
            if previous and previous[0] != responsibility:
                conflicts.append(
                    {
                        "kind": "action-slice-responsibility-mismatch",
                        "name": name,
                        "session_ids": [previous[1], session_id],
                        "summary": "Action-slice responsibility differs across sessions.",
                    }
                )
            else:
                actions_by_name[name] = (responsibility, session_id)

    return conflicts


def assemble_action_plan(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    close_summaries = [session["close_summary"] for session in sessions]
    readiness = "ready"
    blockers: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    workstreams: list[dict[str, Any]] = []
    action_slices: list[dict[str, Any]] = []
    evidence_refs: list[str] = []
    goals: list[str] = []

    for close_summary in close_summaries:
        readiness = _merge_readiness(readiness, close_summary["readiness"])
        blockers.extend(deepcopy(close_summary["unresolved_blockers"]))
        risks.extend(deepcopy(close_summary["unresolved_risks"]))
        workstreams.extend(deepcopy(close_summary["candidate_workstreams"]))
        action_slices.extend(deepcopy(close_summary["candidate_action_slices"]))
        evidence_refs.extend(close_summary["evidence_refs"])
        if close_summary.get("goal"):
            goals.append(close_summary["goal"])

    merged_action_slices = _merge_action_slices(action_slices)
    return {
        "readiness": readiness,
        "goals": stable_unique(goals),
        "workstreams": _merge_workstreams(workstreams),
        "action_slices": merged_action_slices,
        "implementation_ready_slices": [item for item in merged_action_slices if item.get("implementation_ready")],
        "blockers": _dedupe_by_id(blockers),
        "risks": _dedupe_by_id(risks),
        "evidence_refs": stable_unique(evidence_refs),
    }


def _merge_readiness(current: str, other: str) -> str:
    rank = {"ready": 0, "conditional": 1, "blocked": 2}
    worst = max(current, other, key=lambda value: rank[value])
    return worst


def _dedupe_by_name(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    ordered: list[dict[str, Any]] = []
    for item in items:
        name = item.get("name")
        if name in seen:
            continue
        seen.add(name)
        ordered.append(item)
    return ordered


def _merge_workstreams(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in items:
        name = item["name"]
        current = merged.setdefault(
            name,
            {
                "name": name,
                "summary": item.get("summary"),
                "scope": [],
                "implementation_ready_scope": [],
                "accepted_count": 0,
            },
        )
        current["scope"] = stable_unique([*current.get("scope", []), *item.get("scope", [])])
        current["implementation_ready_scope"] = stable_unique(
            [*current.get("implementation_ready_scope", []), *item.get("implementation_ready_scope", [])]
        )
        current["accepted_count"] = max(current.get("accepted_count", 0), item.get("accepted_count", 0))
        if len(current["implementation_ready_scope"]) > len(item.get("implementation_ready_scope", [])):
            current["summary"] = (
                f"{name.removesuffix('-workstream')} workstream with "
                f"{len(current['implementation_ready_scope'])} implementation-ready slice(s)."
            )
        elif item.get("summary"):
            current["summary"] = item["summary"]
    return sorted(merged.values(), key=_workstream_sort_key)


def _merge_action_slices(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in items:
        key = item.get("decision_id") or item.get("name") or ""
        if key not in merged:
            merged[key] = deepcopy(item)
            continue
        current = merged[key]
        preferred = current if _action_slice_sort_key(current) <= _action_slice_sort_key(item) else deepcopy(item)
        preferred["evidence_refs"] = stable_unique([*current.get("evidence_refs", []), *item.get("evidence_refs", [])])
        preferred["implementation_ready"] = bool(
            current.get("implementation_ready") or item.get("implementation_ready")
        )
        preferred["evidence_backed"] = bool(current.get("evidence_backed") or item.get("evidence_backed"))
        preferred["evidence_source"] = current.get("evidence_source") or item.get("evidence_source")
        preferred["next_step"] = preferred.get("next_step") or current.get("next_step") or item.get("next_step")
        merged[key] = preferred
    return sorted(merged.values(), key=_action_slice_sort_key)


def _action_slice_sort_key(item: dict[str, Any]) -> tuple[int, int, int, str]:
    priority_rank = {"P0": 0, "P1": 1, "P2": 2}
    return (
        0 if item.get("evidence_backed") else 1,
        0 if item.get("implementation_ready") else 1,
        priority_rank.get(item.get("priority"), 3),
        item.get("name") or "",
    )


def _workstream_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    return (
        -len(item.get("implementation_ready_scope", [])),
        -len(item.get("scope", [])),
        item.get("name") or "",
    )


def _dedupe_by_id(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    ordered: list[dict[str, Any]] = []
    for item in items:
        item_id = item.get("id")
        if item_id in seen:
            continue
        seen.add(item_id)
        ordered.append(item)
    return ordered


def _record_plan_generated(ai_dir: str, plan: dict[str, Any]) -> None:
    def builder(_: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "event_type": "plan_generated",
                "payload": {
                    "session_ids": plan["source_session_ids"],
                    "status": plan["status"],
                },
            }
        ]

    transact(ai_dir, builder)
