from __future__ import annotations

import hashlib
import json
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

    resolved_conflicts = bundle["project_state"].get("session_graph", {}).get("resolved_conflicts", [])
    conflicts = detect_conflicts(sessions, resolved_conflicts=resolved_conflicts)
    if conflicts:
        plan["status"] = "conflicts"
        plan["conflicts"] = conflicts
    else:
        plan["status"] = "action-plan"
        plan["action_plan"] = assemble_action_plan(sessions, resolved_conflicts=resolved_conflicts)

    output = export_plan(ai_dir, plan)
    plan["export_path"] = str(output)
    _record_plan_generated(ai_dir, plan)
    return plan


def detect_conflicts(
    sessions: list[dict[str, Any]],
    *,
    resolved_conflicts: list[dict[str, Any]] | None = None,
    include_resolved: bool = False,
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    accepted_by_id: dict[str, tuple[str | None, str]] = {}
    workstreams_by_name: dict[str, tuple[set[str], str]] = {}
    actions_by_name: dict[str, tuple[str, str]] = {}
    resolved_by_id = {
        resolved["conflict_id"]: resolved
        for resolved in (resolved_conflicts or [])
    }

    for session in sessions:
        close_summary = session["close_summary"]
        session_id = session["session"]["id"]

        for decision in close_summary["accepted_decisions"]:
            previous = accepted_by_id.get(decision["id"])
            current_answer = decision.get("accepted_answer")
            if previous and previous[0] != current_answer:
                scope = {
                    "kind": "accepted_decision",
                    "decision_id": decision["id"],
                    "session_ids": sorted([previous[1], session_id]),
                }
                conflicts.append(
                    _conflict(
                        "accepted-answer-mismatch",
                        sorted([previous[1], session_id]),
                        scope,
                        "Accepted answers differ for the same decision.",
                        resolved_by_id,
                        include_resolved,
                        decision_id=decision["id"],
                    )
                )
            else:
                accepted_by_id[decision["id"]] = (current_answer, session_id)

        for workstream in close_summary["candidate_workstreams"]:
            name = workstream["name"]
            scope = set(workstream.get("scope", []))
            previous = workstreams_by_name.get(name)
            if previous and previous[0] & scope and previous[0] != scope:
                conflict_scope = {
                    "kind": "workstream",
                    "name": name,
                    "session_ids": sorted([previous[1], session_id]),
                }
                conflicts.append(
                    _conflict(
                        "workstream-scope-mismatch",
                        sorted([previous[1], session_id]),
                        conflict_scope,
                        "Workstream scope differs across sessions.",
                        resolved_by_id,
                        include_resolved,
                        name=name,
                    )
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
                scope = {
                    "kind": "action_slice",
                    "name": name,
                    "session_ids": sorted([previous[1], session_id]),
                }
                conflicts.append(
                    _conflict(
                        "action-slice-responsibility-mismatch",
                        sorted([previous[1], session_id]),
                        scope,
                        "Action-slice responsibility differs across sessions.",
                        resolved_by_id,
                        include_resolved,
                        name=name,
                    )
                )
            else:
                actions_by_name[name] = (responsibility, session_id)

    return [conflict for conflict in conflicts if conflict is not None]


def assemble_action_plan(
    sessions: list[dict[str, Any]],
    *,
    resolved_conflicts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    close_summaries = _close_summaries_after_resolutions(sessions, resolved_conflicts or [])
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


def _conflict(
    kind: str,
    session_ids: list[str],
    scope: dict[str, Any],
    summary: str,
    resolved_by_id: dict[str, dict[str, Any]],
    include_resolved: bool,
    **extra: Any,
) -> dict[str, Any] | None:
    conflict_id = _conflict_id(kind, session_ids, scope)
    resolved = resolved_by_id.get(conflict_id)
    if resolved and not include_resolved:
        return None
    conflict = {
        "id": conflict_id,
        "conflict_id": conflict_id,
        "kind": kind,
        "session_ids": session_ids,
        "scope": scope,
        "summary": summary,
        "requires_resolution": resolved is None,
    }
    conflict.update(extra)
    if resolved:
        conflict["resolution"] = deepcopy(resolved)
    return conflict


def _conflict_id(kind: str, session_ids: list[str], scope: dict[str, Any]) -> str:
    material = json.dumps(
        {"kind": kind, "session_ids": sorted(session_ids), "scope": scope},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"C-{kind}-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:12]}"


def _close_summaries_after_resolutions(
    sessions: list[dict[str, Any]],
    resolved_conflicts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected_session_ids = {session["session"]["id"] for session in sessions}
    removals: dict[str, dict[str, set[str]]] = {}
    for resolution in resolved_conflicts:
        scope = resolution["scope"]
        if resolution["winning_session_id"] not in selected_session_ids:
            continue
        for rejected_session_id in resolution["rejected_session_ids"]:
            if rejected_session_id not in selected_session_ids:
                continue
            session_removals = removals.setdefault(
                rejected_session_id,
                {"accepted_decisions": set(), "workstreams": set(), "action_slices": set()},
            )
            if scope["kind"] == "accepted_decision":
                decision_id = scope.get("decision_id")
                if decision_id:
                    session_removals["accepted_decisions"].add(decision_id)
                    session_removals["action_slices"].add(decision_id)
            elif scope["kind"] == "workstream":
                name = scope.get("name")
                if name:
                    session_removals["workstreams"].add(name)
            elif scope["kind"] == "action_slice":
                name = scope.get("name")
                if name:
                    session_removals["action_slices"].add(name)

    close_summaries: list[dict[str, Any]] = []
    for session in sessions:
        session_id = session["session"]["id"]
        close_summary = deepcopy(session["close_summary"])
        session_removals = removals.get(session_id)
        if session_removals:
            _apply_close_summary_removals(close_summary, session_removals)
        close_summaries.append(close_summary)
    return close_summaries


def _apply_close_summary_removals(
    close_summary: dict[str, Any],
    removals: dict[str, set[str]],
) -> None:
    accepted_decisions = removals["accepted_decisions"]
    if accepted_decisions:
        close_summary["accepted_decisions"] = [
            item for item in close_summary["accepted_decisions"] if item.get("id") not in accepted_decisions
        ]
        for key in ("deferred_decisions", "unresolved_blockers", "unresolved_risks"):
            close_summary[key] = [item for item in close_summary[key] if item.get("id") not in accepted_decisions]

    action_slices = removals["action_slices"]
    if action_slices:
        close_summary["candidate_action_slices"] = [
            item
            for item in close_summary["candidate_action_slices"]
            if item.get("name") not in action_slices and item.get("decision_id") not in action_slices
        ]

    workstreams = removals["workstreams"]
    filtered_workstreams: list[dict[str, Any]] = []
    for workstream in close_summary["candidate_workstreams"]:
        if workstream.get("name") in workstreams:
            continue
        updated = deepcopy(workstream)
        if accepted_decisions:
            updated["scope"] = [item for item in updated.get("scope", []) if item not in accepted_decisions]
            updated["implementation_ready_scope"] = [
                item for item in updated.get("implementation_ready_scope", []) if item not in accepted_decisions
            ]
            updated["accepted_count"] = len(
                [item for item in updated.get("scope", []) if item not in accepted_decisions]
            )
        if updated.get("scope"):
            filtered_workstreams.append(updated)
    close_summary["candidate_workstreams"] = filtered_workstreams


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
