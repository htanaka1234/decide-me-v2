from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from decide_me.exporters.common import project_head, snapshot_generated_at
from decide_me.projections import build_decision_stack_graph
from decide_me.registers import build_assumption_register, build_evidence_register, build_risk_register
from decide_me.safety_gate import build_safety_gate_report
from decide_me.stale_detection import (
    detect_revisit_due,
    detect_stale_assumptions,
    detect_stale_evidence,
    detect_verification_gaps,
)
from decide_me.store import load_runtime, read_event_log, runtime_paths
from decide_me.suppression import apply_semantic_suppression_to_session
from decide_me.taxonomy import stable_unique


ACTION_PLAN_DOCUMENT_TYPES = {"action-plan"}


@dataclass(frozen=True)
class DocumentContext:
    bundle: dict[str, Any]
    events: list[dict[str, Any]]
    project_state: dict[str, Any]
    scoped_project_state: dict[str, Any]
    sessions: list[dict[str, Any]]
    source_session_ids: list[str]
    generated_at: str | None
    project_head: str | None
    evidence_register: dict[str, Any]
    assumption_register: dict[str, Any]
    risk_register: dict[str, Any]
    safety_gates: dict[str, Any]
    stale_assumptions: dict[str, Any]
    stale_evidence: dict[str, Any]
    verification_gaps: dict[str, Any]
    revisit_due: dict[str, Any]
    action_plan: dict[str, Any] | None
    object_ids: list[str]
    scope_object_ids: list[str]
    scope_link_ids: list[str]
    include_invalidated: bool


def build_document_context(
    ai_dir: str | Path,
    *,
    document_type: str,
    session_ids: list[str] | None = None,
    object_ids: list[str] | None = None,
    include_invalidated: bool = False,
    now: str | None = None,
) -> DocumentContext:
    paths = runtime_paths(ai_dir)
    bundle = load_runtime(paths)
    events = read_event_log(paths)
    project_state = bundle["project_state"]
    source_session_ids, sessions = _selected_closed_sessions(
        bundle,
        session_ids,
        f"{document_type} document export",
    )
    normalized_sessions = _sessions_after_resolutions(
        sessions,
        project_state.get("graph", {}).get("resolved_conflicts", []),
    )
    requested_object_ids = sorted(stable_unique(object_ids or []))
    scoped_project_state, scope_object_ids, scope_link_ids = _scoped_project_state(
        project_state,
        normalized_sessions,
        object_ids=requested_object_ids,
        include_invalidated=include_invalidated,
    )
    action_plan = None
    if document_type in ACTION_PLAN_DOCUMENT_TYPES:
        action_plan = _build_action_plan(
            document_type,
            sessions,
            project_state,
            scoped_project_state,
            scope_object_ids,
            scope_link_ids,
        )

    return DocumentContext(
        bundle=bundle,
        events=events,
        project_state=project_state,
        scoped_project_state=scoped_project_state,
        sessions=normalized_sessions,
        source_session_ids=source_session_ids,
        generated_at=now or snapshot_generated_at(bundle, events),
        project_head=project_head(bundle),
        evidence_register=build_evidence_register(scoped_project_state),
        assumption_register=build_assumption_register(scoped_project_state),
        risk_register=build_risk_register(scoped_project_state),
        safety_gates=build_safety_gate_report(scoped_project_state, now=now),
        stale_assumptions=detect_stale_assumptions(scoped_project_state, now=now),
        stale_evidence=detect_stale_evidence(scoped_project_state, now=now),
        verification_gaps=detect_verification_gaps(scoped_project_state, now=now),
        revisit_due=detect_revisit_due(scoped_project_state, now=now),
        action_plan=action_plan,
        object_ids=requested_object_ids,
        scope_object_ids=scope_object_ids,
        scope_link_ids=scope_link_ids,
        include_invalidated=include_invalidated,
    )


def _build_action_plan(
    document_type: str,
    sessions: list[dict[str, Any]],
    project_state: dict[str, Any],
    scoped_project_state: dict[str, Any],
    scope_object_ids: list[str],
    scope_link_ids: list[str],
) -> dict[str, Any]:
    from decide_me.planner import assemble_action_plan, detect_conflicts

    resolved_conflicts = project_state.get("graph", {}).get("resolved_conflicts", [])
    conflicts = detect_conflicts(
        sessions,
        project_state,
        resolved_conflicts=resolved_conflicts,
    )
    if conflicts:
        conflict_ids = ", ".join(conflict["conflict_id"] for conflict in conflicts)
        raise ValueError(f"unresolved session conflicts block {document_type} document export: {conflict_ids}")
    scoped_sessions = _scoped_sessions(sessions, scope_object_ids, scope_link_ids)
    action_plan = assemble_action_plan(
        scoped_sessions,
        scoped_project_state,
        resolved_conflicts=resolved_conflicts,
    )
    return _filter_action_plan_sources(action_plan, scope_object_ids, scope_link_ids)


def _scoped_project_state(
    project_state: dict[str, Any],
    sessions: list[dict[str, Any]],
    *,
    object_ids: list[str],
    include_invalidated: bool,
) -> tuple[dict[str, Any], list[str], list[str]]:
    objects_by_id = {obj["id"]: obj for obj in project_state.get("objects", [])}
    links_by_id = {link["id"]: link for link in project_state.get("links", [])}
    session_object_ids, session_link_ids = _session_scope_ids(sessions, links_by_id)
    for object_id in object_ids:
        if object_id not in objects_by_id:
            raise ValueError(f"unknown object_id: {object_id}")
        if object_id not in session_object_ids:
            raise ValueError(f"object_id is outside selected session scope: {object_id}")
        if not include_invalidated and objects_by_id[object_id].get("status") == "invalidated":
            raise ValueError(f"object_id is invalidated; pass --include-invalidated: {object_id}")

    if object_ids:
        scoped_object_ids, scoped_link_ids = _object_narrowed_scope(
            object_ids,
            session_object_ids,
            session_link_ids,
            links_by_id,
        )
    else:
        scoped_object_ids = set(session_object_ids)
        scoped_link_ids = set(session_link_ids)

    if not include_invalidated:
        scoped_object_ids = {
            object_id
            for object_id in scoped_object_ids
            if objects_by_id.get(object_id, {}).get("status") != "invalidated"
        }
    scoped_link_ids = {
        link_id
        for link_id in scoped_link_ids
        if (link := links_by_id.get(link_id))
        and link.get("source_object_id") in scoped_object_ids
        and link.get("target_object_id") in scoped_object_ids
    }
    scoped_object_ids.update(
        endpoint
        for link_id in scoped_link_ids
        if (link := links_by_id.get(link_id))
        for endpoint in (link.get("source_object_id"), link.get("target_object_id"))
        if endpoint in objects_by_id
    )
    if not include_invalidated:
        scoped_object_ids = {
            object_id
            for object_id in scoped_object_ids
            if objects_by_id.get(object_id, {}).get("status") != "invalidated"
        }
        scoped_link_ids = {
            link_id
            for link_id in scoped_link_ids
            if (link := links_by_id.get(link_id))
            and link.get("source_object_id") in scoped_object_ids
            and link.get("target_object_id") in scoped_object_ids
        }

    scoped = deepcopy(project_state)
    scoped["objects"] = [
        deepcopy(objects_by_id[object_id])
        for object_id in sorted(scoped_object_ids)
        if object_id in objects_by_id
    ]
    scoped["links"] = [
        deepcopy(links_by_id[link_id])
        for link_id in sorted(scoped_link_ids)
        if link_id in links_by_id
    ]
    scoped["counts"] = _counts_for_scoped_state(scoped["objects"], scoped["links"])
    scoped["graph"] = build_decision_stack_graph(scoped)
    return scoped, [obj["id"] for obj in scoped["objects"]], [link["id"] for link in scoped["links"]]


def _scoped_sessions(
    sessions: list[dict[str, Any]],
    scope_object_ids: list[str],
    scope_link_ids: list[str],
) -> list[dict[str, Any]]:
    object_scope = set(scope_object_ids)
    link_scope = set(scope_link_ids)
    scoped_sessions = []
    for session in sessions:
        scoped_session = deepcopy(session)
        session_payload = scoped_session.get("session", {})
        session_payload["related_object_ids"] = [
            object_id
            for object_id in session_payload.get("related_object_ids", [])
            if object_id in object_scope
        ]
        close_summary = scoped_session.get("close_summary", {})
        close_object_ids = close_summary.get("object_ids", {})
        for key, values in list(close_object_ids.items()):
            close_object_ids[key] = [object_id for object_id in values if object_id in object_scope]
        close_summary["link_ids"] = [
            link_id
            for link_id in close_summary.get("link_ids", [])
            if link_id in link_scope
        ]
        work_item = close_summary.get("work_item", {})
        if work_item.get("objective_object_id") not in object_scope:
            work_item.pop("objective_object_id", None)
        scoped_sessions.append(scoped_session)
    return scoped_sessions


def _filter_action_plan_sources(
    action_plan: dict[str, Any],
    scope_object_ids: list[str],
    scope_link_ids: list[str],
) -> dict[str, Any]:
    object_scope = set(scope_object_ids)
    link_scope = set(scope_link_ids)
    filtered = deepcopy(action_plan)
    filtered["source_object_ids"] = [
        object_id
        for object_id in filtered.get("source_object_ids", [])
        if object_id in object_scope
    ]
    filtered["source_link_ids"] = [
        link_id
        for link_id in filtered.get("source_link_ids", [])
        if link_id in link_scope
    ]
    return filtered


def _session_scope_ids(
    sessions: list[dict[str, Any]],
    links_by_id: dict[str, dict[str, Any]],
) -> tuple[set[str], set[str]]:
    object_ids: set[str] = set()
    link_ids: set[str] = set()
    for session in sessions:
        object_ids.update(session.get("session", {}).get("related_object_ids", []))
        close_summary = session.get("close_summary", {})
        for values in close_summary.get("object_ids", {}).values():
            object_ids.update(values)
        objective_id = close_summary.get("work_item", {}).get("objective_object_id")
        if objective_id:
            object_ids.add(objective_id)
        link_ids.update(close_summary.get("link_ids", []))
    object_ids.update(
        endpoint
        for link_id in link_ids
        if (link := links_by_id.get(link_id))
        for endpoint in (link.get("source_object_id"), link.get("target_object_id"))
        if endpoint
    )
    link_ids.update(
        link["id"]
        for link in links_by_id.values()
        if link.get("source_object_id") in object_ids and link.get("target_object_id") in object_ids
    )
    return object_ids, link_ids


def _object_narrowed_scope(
    requested_object_ids: list[str],
    session_object_ids: set[str],
    session_link_ids: set[str],
    links_by_id: dict[str, dict[str, Any]],
) -> tuple[set[str], set[str]]:
    allowed_requested_ids = set(requested_object_ids) & session_object_ids
    scoped_object_ids = set(allowed_requested_ids)
    scoped_link_ids: set[str] = set()
    changed = True
    while changed:
        changed = False
        for link_id in session_link_ids:
            link = links_by_id.get(link_id)
            if not link:
                continue
            source_id = link.get("source_object_id")
            target_id = link.get("target_object_id")
            if source_id not in session_object_ids or target_id not in session_object_ids:
                continue
            if source_id not in scoped_object_ids and target_id not in scoped_object_ids:
                continue
            if link_id not in scoped_link_ids:
                scoped_link_ids.add(link_id)
                changed = True
            for object_id in (source_id, target_id):
                if object_id and object_id not in scoped_object_ids:
                    scoped_object_ids.add(object_id)
                    changed = True
    return scoped_object_ids, scoped_link_ids


def _counts_for_scoped_state(objects: list[dict[str, Any]], links: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_relation: dict[str, int] = {}
    for obj in objects:
        by_type[obj["type"]] = by_type.get(obj["type"], 0) + 1
        by_status[obj["status"]] = by_status.get(obj["status"], 0) + 1
    for link in links:
        by_relation[link["relation"]] = by_relation.get(link["relation"], 0) + 1
    return {
        "object_total": len(objects),
        "link_total": len(links),
        "by_type": {key: by_type[key] for key in sorted(by_type)},
        "by_status": {key: by_status[key] for key in sorted(by_status)},
        "by_relation": {key: by_relation[key] for key in sorted(by_relation)},
    }


def _selected_closed_sessions(
    bundle: dict[str, Any],
    session_ids: list[str] | None,
    export_name: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    if session_ids:
        source_session_ids = sorted(stable_unique(session_ids))
    else:
        source_session_ids = sorted(
            session_id
            for session_id, session in bundle["sessions"].items()
            if session["session"]["lifecycle"]["status"] == "closed"
        )

    sessions: list[dict[str, Any]] = []
    for session_id in source_session_ids:
        session = bundle["sessions"].get(session_id)
        if not session:
            raise ValueError(f"unknown session: {session_id}")
        if session["session"]["lifecycle"]["status"] != "closed":
            raise ValueError(f"session {session_id} must be closed before {export_name}")
        sessions.append(session)
    return source_session_ids, sessions


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
