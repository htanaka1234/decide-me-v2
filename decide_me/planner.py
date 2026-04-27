from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from decide_me.events import utc_now
from decide_me.exports import export_plan
from decide_me.store import load_runtime, runtime_paths, transact
from decide_me.suppression import apply_semantic_suppression_to_session
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

    project_state = bundle["project_state"]
    graph = project_state["graph"]
    resolved_conflicts = graph.get("resolved_conflicts", [])
    conflicts = detect_conflicts(sessions, project_state, resolved_conflicts=resolved_conflicts)
    if conflicts:
        plan["status"] = "conflicts"
        plan["conflicts"] = conflicts
    else:
        plan["status"] = "action-plan"
        plan["action_plan"] = assemble_action_plan(
            sessions,
            project_state,
            resolved_conflicts=resolved_conflicts,
        )

    output = export_plan(ai_dir, plan)
    plan["export_path"] = str(output)
    _record_plan_generated(ai_dir, plan)
    return plan


def detect_conflicts(
    sessions: list[dict[str, Any]],
    project_state: dict[str, Any],
    *,
    resolved_conflicts: list[dict[str, Any]] | None = None,
    include_resolved: bool = False,
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    accepted_by_id: dict[str, tuple[str | None, str]] = {}
    actions_by_name: dict[str, tuple[str | None, str]] = {}
    normalized_sessions = _sessions_after_resolutions(sessions, resolved_conflicts or [])
    resolved_by_id = {
        resolved["conflict_id"]: resolved
        for resolved in (resolved_conflicts or [])
    }

    for session in normalized_sessions:
        close_summary = session["close_summary"]
        session_id = session["session"]["id"]

        for decision_id in close_summary["object_ids"].get("accepted_decisions", []):
            current_answer = _accepted_answer_for_session(project_state, close_summary, decision_id)
            previous = accepted_by_id.get(decision_id)
            if previous and previous[0] != current_answer:
                scope = {
                    "kind": "accepted_decision",
                    "decision_id": decision_id,
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
                        decision_id=decision_id,
                    )
                )
            else:
                accepted_by_id[decision_id] = (current_answer, session_id)

        for action_id in close_summary["object_ids"].get("actions", []):
            action = _objects_by_id(project_state).get(action_id)
            if not action:
                continue
            name = action.get("title") or action_id
            responsibility = action.get("metadata", {}).get("responsibility")
            previous = actions_by_name.get(name)
            if previous and previous[0] != responsibility:
                scope = {
                    "kind": "action",
                    "action_id": action_id,
                    "name": name,
                    "session_ids": sorted([previous[1], session_id]),
                }
                conflicts.append(
                    _conflict(
                        "action-responsibility-mismatch",
                        sorted([previous[1], session_id]),
                        scope,
                        "Action responsibility differs across sessions.",
                        resolved_by_id,
                        include_resolved,
                        action_id=action_id,
                        name=name,
                    )
                )
            else:
                actions_by_name[name] = (responsibility, session_id)

    return [conflict for conflict in conflicts if conflict is not None]


def assemble_action_plan(
    sessions: list[dict[str, Any]],
    project_state: dict[str, Any],
    *,
    resolved_conflicts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_sessions = _sessions_after_resolutions(sessions, resolved_conflicts or [])
    readiness = "ready"
    goals: list[str] = []
    actions: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    evidence_refs: list[str] = []
    workstream_inputs: list[dict[str, Any]] = []

    for session in normalized_sessions:
        close_summary = session["close_summary"]
        object_ids = close_summary["object_ids"]
        readiness = _merge_readiness(readiness, close_summary["readiness"])
        work_item = close_summary.get("work_item", {})
        goals.extend(value for value in (work_item.get("title"), work_item.get("statement")) if value)

        for action_id in object_ids.get("actions", []):
            action = _action_item(project_state, close_summary, action_id)
            if action:
                actions.append(action)
                evidence_refs.extend(action.get("evidence_refs", []))

        for decision_id in object_ids.get("blockers", []):
            item = _decision_item(project_state, close_summary, decision_id)
            if item:
                blockers.append(item)
                evidence_refs.extend(item.get("evidence_refs", []))

        for object_id in object_ids.get("risks", []):
            item = _risk_item(project_state, close_summary, object_id)
            if item:
                risks.append(item)
                evidence_refs.extend(item.get("evidence_refs", []))

        workstream_inputs.extend(_workstream_inputs(project_state, close_summary))

    merged_actions = _merge_actions(actions)
    return {
        "readiness": readiness,
        "goals": stable_unique(goals),
        "workstreams": _merge_workstreams(workstream_inputs),
        "actions": merged_actions,
        "implementation_ready_actions": [item for item in merged_actions if item.get("implementation_ready")],
        "blockers": _dedupe_by_id(blockers),
        "risks": _dedupe_by_id(risks),
        "evidence_refs": stable_unique(evidence_refs),
    }


def _merge_readiness(current: str, other: str) -> str:
    rank = {"ready": 0, "conditional": 1, "blocked": 2}
    return max(current, other, key=lambda value: rank[value])


def _objects_by_id(project_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {obj["id"]: obj for obj in project_state.get("objects", [])}


def _links_by_id(project_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {link["id"]: link for link in project_state.get("links", [])}


def _summary_links(project_state: dict[str, Any], close_summary: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = _links_by_id(project_state)
    return [by_id[link_id] for link_id in close_summary.get("link_ids", []) if link_id in by_id]


def _accepted_answer_for_session(
    project_state: dict[str, Any],
    close_summary: dict[str, Any],
    decision_id: str,
) -> str | None:
    by_id = _objects_by_id(project_state)
    for link in _summary_links(project_state, close_summary):
        if (
            link.get("source_object_id") == decision_id
            and link.get("relation") == "accepts"
            and by_id.get(link.get("target_object_id"), {}).get("type") == "proposal"
        ):
            option = _recommended_option(project_state, link["target_object_id"], close_summary)
            proposal = by_id[link["target_object_id"]]
            return option.get("title") if option else proposal.get("title") or proposal.get("body")
    evidence = _evidence_for_decision(project_state, close_summary, decision_id)
    if evidence:
        return evidence[0].get("summary") or evidence[0].get("ref")
    return None


def _recommended_option(
    project_state: dict[str, Any],
    proposal_id: str,
    close_summary: dict[str, Any],
) -> dict[str, Any] | None:
    by_id = _objects_by_id(project_state)
    summary_links = _summary_links(project_state, close_summary)
    candidate_links = [
        link
        for link in summary_links
        if link.get("source_object_id") == proposal_id and link.get("relation") == "recommends"
    ]
    if not candidate_links:
        candidate_links = [
            link
            for link in project_state.get("links", [])
            if link.get("source_object_id") == proposal_id and link.get("relation") == "recommends"
        ]
    for link in candidate_links:
        option = by_id.get(link["target_object_id"])
        if option and option.get("type") == "option":
            return option
    return None


def _evidence_for_decision(
    project_state: dict[str, Any],
    close_summary: dict[str, Any],
    decision_id: str,
) -> list[dict[str, Any]]:
    by_id = _objects_by_id(project_state)
    evidence = []
    for link in _summary_links(project_state, close_summary):
        if link.get("relation") != "supports" or link.get("target_object_id") != decision_id:
            continue
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


def _action_item(
    project_state: dict[str, Any],
    close_summary: dict[str, Any],
    action_id: str,
) -> dict[str, Any] | None:
    by_id = _objects_by_id(project_state)
    action = by_id.get(action_id)
    if not action or action.get("type") != "action":
        return None
    metadata = action.get("metadata", {})
    decision_id = metadata.get("decision_id") or _addressed_decision_id(project_state, close_summary, action_id)
    evidence_refs = list(metadata.get("evidence_refs", []))
    evidence_source = metadata.get("evidence_source")
    if decision_id:
        evidence = _evidence_for_decision(project_state, close_summary, decision_id)
        evidence_refs = stable_unique([*evidence_refs, *[item["ref"] for item in evidence]])
        evidence_source = evidence_source or (evidence[0].get("source") if evidence else None)
    return {
        "id": action["id"],
        "decision_id": decision_id,
        "name": action.get("title") or action["id"],
        "summary": action.get("body"),
        "responsibility": metadata.get("responsibility"),
        "priority": metadata.get("priority"),
        "status": action.get("status"),
        "kind": metadata.get("kind"),
        "resolvable_by": metadata.get("resolvable_by"),
        "reversibility": metadata.get("reversibility"),
        "implementation_ready": bool(metadata.get("implementation_ready")),
        "evidence_backed": bool(metadata.get("evidence_backed") or evidence_refs),
        "evidence_source": evidence_source,
        "evidence_refs": evidence_refs,
        "next_step": metadata.get("next_step"),
    }


def _addressed_decision_id(
    project_state: dict[str, Any],
    close_summary: dict[str, Any],
    action_id: str,
) -> str | None:
    for link in _summary_links(project_state, close_summary):
        if link.get("source_object_id") == action_id and link.get("relation") == "addresses":
            return link.get("target_object_id")
    return None


def _decision_item(
    project_state: dict[str, Any],
    close_summary: dict[str, Any],
    decision_id: str,
) -> dict[str, Any] | None:
    decision = _objects_by_id(project_state).get(decision_id)
    if not decision or decision.get("type") != "decision":
        return None
    metadata = decision.get("metadata", {})
    evidence = _evidence_for_decision(project_state, close_summary, decision_id)
    return {
        "id": decision["id"],
        "title": decision.get("title"),
        "summary": decision.get("body"),
        "accepted_answer": _accepted_answer_for_session(project_state, close_summary, decision_id),
        "status": decision.get("status"),
        "domain": metadata.get("domain"),
        "kind": metadata.get("kind"),
        "priority": metadata.get("priority"),
        "frontier": metadata.get("frontier"),
        "resolvable_by": metadata.get("resolvable_by"),
        "evidence_source": evidence[0].get("source") if evidence else None,
        "evidence_refs": [item["ref"] for item in evidence],
    }


def _risk_item(
    project_state: dict[str, Any],
    close_summary: dict[str, Any],
    object_id: str,
) -> dict[str, Any] | None:
    obj = _objects_by_id(project_state).get(object_id)
    if not obj:
        return None
    if obj.get("type") == "decision":
        return _decision_item(project_state, close_summary, object_id)
    if obj.get("type") != "risk":
        return None
    metadata = obj.get("metadata", {})
    return {
        "id": obj["id"],
        "title": obj.get("title"),
        "summary": obj.get("body"),
        "status": obj.get("status"),
        "domain": metadata.get("domain"),
        "kind": "risk",
        "priority": metadata.get("priority"),
        "resolvable_by": metadata.get("resolvable_by"),
        "evidence_refs": list(metadata.get("evidence_refs", [])),
    }


def _workstream_inputs(project_state: dict[str, Any], close_summary: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = _objects_by_id(project_state)
    inputs = []
    for decision_id in close_summary["object_ids"].get("decisions", []):
        decision = by_id.get(decision_id)
        if not decision or decision.get("type") != "decision":
            continue
        metadata = decision.get("metadata", {})
        inputs.append(
            {
                "decision_id": decision_id,
                "domain": metadata.get("domain", "other"),
                "accepted": decision.get("status") in {"accepted", "resolved-by-evidence"},
                "implementation_ready": False,
            }
        )
    for action_id in close_summary["object_ids"].get("actions", []):
        action = by_id.get(action_id)
        if not action or action.get("type") != "action":
            continue
        metadata = action.get("metadata", {})
        decision_id = metadata.get("decision_id") or _addressed_decision_id(project_state, close_summary, action_id)
        inputs.append(
            {
                "decision_id": decision_id,
                "domain": metadata.get("responsibility", "other"),
                "accepted": True,
                "implementation_ready": bool(metadata.get("implementation_ready")),
            }
        )
    return inputs


def _merge_workstreams(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in items:
        domain = item.get("domain") or "other"
        name = f"{domain}-workstream"
        current = merged.setdefault(
            name,
            {
                "name": name,
                "summary": f"Advance {domain} decisions for the current milestone.",
                "scope": [],
                "implementation_ready_scope": [],
                "accepted_count": 0,
            },
        )
        decision_id = item.get("decision_id")
        if decision_id:
            current["scope"] = stable_unique([*current["scope"], decision_id])
            if item.get("implementation_ready"):
                current["implementation_ready_scope"] = stable_unique(
                    [*current["implementation_ready_scope"], decision_id]
                )
            if item.get("accepted"):
                current["accepted_count"] += 1
    for item in merged.values():
        if item["implementation_ready_scope"]:
            domain = item["name"].removesuffix("-workstream")
            item["summary"] = (
                f"Advance {domain} decisions for the current milestone. "
                f"{len(item['implementation_ready_scope'])} implementation-ready action(s) are already grounded."
            )
    return sorted(merged.values(), key=_workstream_sort_key)


def _merge_actions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in items:
        key = item.get("id") or item.get("decision_id") or item.get("name") or ""
        if key not in merged:
            merged[key] = deepcopy(item)
            continue
        current = merged[key]
        preferred = current if _action_sort_key(current) <= _action_sort_key(item) else deepcopy(item)
        preferred["evidence_refs"] = stable_unique([*current.get("evidence_refs", []), *item.get("evidence_refs", [])])
        preferred["implementation_ready"] = bool(
            current.get("implementation_ready") or item.get("implementation_ready")
        )
        preferred["evidence_backed"] = bool(current.get("evidence_backed") or item.get("evidence_backed"))
        preferred["evidence_source"] = current.get("evidence_source") or item.get("evidence_source")
        preferred["next_step"] = preferred.get("next_step") or current.get("next_step") or item.get("next_step")
        merged[key] = preferred
    return sorted(merged.values(), key=_action_sort_key)


def _action_sort_key(item: dict[str, Any]) -> tuple[int, int, int, str]:
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


def _sessions_after_resolutions(
    sessions: list[dict[str, Any]],
    resolved_conflicts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized_sessions: list[dict[str, Any]] = []
    for session in sessions:
        normalized_session = deepcopy(session)
        for resolution in resolved_conflicts:
            apply_semantic_suppression_to_session(normalized_session, resolution)
        normalized_sessions.append(normalized_session)
    return normalized_sessions


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
