from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from decide_me.exporters.common import project_head, snapshot_generated_at
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
    action_plan = None
    if document_type in ACTION_PLAN_DOCUMENT_TYPES:
        action_plan = _build_action_plan(document_type, sessions, project_state)

    return DocumentContext(
        bundle=bundle,
        events=events,
        project_state=project_state,
        sessions=normalized_sessions,
        source_session_ids=source_session_ids,
        generated_at=now or snapshot_generated_at(bundle, events),
        project_head=project_head(bundle),
        evidence_register=build_evidence_register(project_state),
        assumption_register=build_assumption_register(project_state),
        risk_register=build_risk_register(project_state),
        safety_gates=build_safety_gate_report(project_state, now=now),
        stale_assumptions=detect_stale_assumptions(project_state, now=now),
        stale_evidence=detect_stale_evidence(project_state, now=now),
        verification_gaps=detect_verification_gaps(project_state, now=now),
        revisit_due=detect_revisit_due(project_state, now=now),
        action_plan=action_plan,
        object_ids=sorted(stable_unique(object_ids or [])),
        include_invalidated=include_invalidated,
    )


def _build_action_plan(
    document_type: str,
    sessions: list[dict[str, Any]],
    project_state: dict[str, Any],
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
    return assemble_action_plan(
        sessions,
        project_state,
        resolved_conflicts=resolved_conflicts,
    )


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
