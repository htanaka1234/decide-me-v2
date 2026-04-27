from __future__ import annotations

import json
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from decide_me.exporters.common import (
    build_decision_event_index,
    project_head,
    snapshot_generated_at,
)
from decide_me.exporters.render import render_markdown_list, render_markdown_text
from decide_me.planner import assemble_action_plan, detect_conflicts
from decide_me.store import load_runtime, read_event_log, runtime_paths
from decide_me.suppression import apply_semantic_suppression_to_session
from decide_me.taxonomy import stable_unique


GITHUB_ISSUES_EXPORT_SCHEMA_VERSION = 1
GITHUB_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "github"
ISSUE_FORM_FILES = (
    "decide-decision.yml",
    "decide-task.yml",
    "decide-conflict.yml",
    "decide-risk.yml",
)
TYPE_RANK = {"decision": 0, "task": 1, "risk": 2, "conflict": 3}


def export_github_templates(output_dir: str | Path, *, ai_dir: str | Path | None = None) -> list[Path]:
    _ = ai_dir
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in ISSUE_FORM_FILES:
        source = GITHUB_TEMPLATE_DIR / name
        target = target_dir / name
        shutil.copyfile(source, target)
        paths.append(target)
    return paths


def export_github_issues(
    ai_dir: str | Path,
    session_ids: list[str],
    output_dir: str | Path,
) -> Path:
    if not session_ids:
        raise ValueError("at least one closed session is required to export GitHub issues")

    paths = runtime_paths(ai_dir)
    bundle = load_runtime(paths)
    events = read_event_log(paths)
    sessions = _closed_sessions(bundle, session_ids)
    manifest, bodies = build_github_issues_export(bundle, events, sessions, session_ids)

    target_dir = Path(output_dir)
    return _write_github_issues_output(target_dir, manifest, bodies)


def build_github_issues_export(
    bundle: dict[str, Any],
    events: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    session_ids: list[str],
) -> tuple[dict[str, Any], dict[str, str]]:
    graph = bundle["project_state"]["graph"]
    resolved_conflicts = graph.get("resolved_conflicts", [])
    index = build_decision_event_index(events)
    generated_at = snapshot_generated_at(bundle, events)
    current_project_head = project_head(bundle)
    conflicts = detect_conflicts(
        sessions,
        bundle["project_state"],
        resolved_conflicts=resolved_conflicts,
    )

    if conflicts:
        plan_status = "conflicts"
        issues, bodies = _conflict_issues(
            conflicts,
            generated_at=generated_at,
            project_head=current_project_head,
        )
    else:
        plan_status = "action-plan"
        action_plan = assemble_action_plan(
            sessions,
            bundle["project_state"],
            resolved_conflicts=resolved_conflicts,
        )
        normalized_sessions = _sessions_after_resolutions(sessions, resolved_conflicts)
        issues, bodies = _action_plan_issues(
            action_plan,
            normalized_sessions,
            index.session_ids,
            generated_at=generated_at,
            project_head=current_project_head,
        )

    issues = sorted(issues, key=_issue_sort_key)
    manifest = {
        "schema_version": GITHUB_ISSUES_EXPORT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "project_head": current_project_head,
        "source_session_ids": list(session_ids),
        "plan_status": plan_status,
        "issues": issues,
    }
    return manifest, bodies


def _closed_sessions(bundle: dict[str, Any], session_ids: list[str]) -> list[dict[str, Any]]:
    sessions = []
    for session_id in session_ids:
        session = bundle["sessions"].get(session_id)
        if not session:
            raise ValueError(f"unknown session: {session_id}")
        if session["session"]["lifecycle"]["status"] != "closed":
            raise ValueError(f"session {session_id} must be closed before GitHub issue export")
        sessions.append(session)
    return sessions


def _write_github_issues_output(
    target_dir: Path,
    manifest: dict[str, Any],
    bodies: dict[str, str],
) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    issues_dir = target_dir / "issues"
    manifest_path = target_dir / "issues.json"
    if issues_dir.exists() and not issues_dir.is_dir():
        raise ValueError(f"GitHub issue export path is not a directory: {issues_dir}")
    if manifest_path.exists() and manifest_path.is_dir():
        raise ValueError(f"GitHub issue export manifest path is a directory: {manifest_path}")

    with tempfile.TemporaryDirectory(prefix=".github-issues-", dir=target_dir) as temp_name:
        temp_root = Path(temp_name)
        temp_issues_dir = temp_root / "issues"
        temp_issues_dir.mkdir()
        for relative_path, body in sorted(bodies.items()):
            target = temp_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body.rstrip() + "\n", encoding="utf-8")

        temp_manifest_path = temp_root / "issues.json"
        temp_manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        if issues_dir.exists():
            shutil.rmtree(issues_dir)
        shutil.move(str(temp_issues_dir), str(issues_dir))
        temp_manifest_path.replace(manifest_path)
    return manifest_path


def _action_plan_issues(
    action_plan: dict[str, Any],
    sessions: list[dict[str, Any]],
    session_ids_by_decision_id: dict[str, str],
    *,
    generated_at: str | None,
    project_head: str | None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    issues: list[dict[str, Any]] = []
    bodies: dict[str, str] = {}
    emitted_decision_ids: set[str] = set()
    evidence_by_id = _evidence_by_id(action_plan)

    for blocker in action_plan.get("blockers", []):
        issue, body_path, body = _decision_issue(
            blocker,
            evidence_by_id=evidence_by_id,
            session_id=session_ids_by_decision_id.get(blocker["id"]),
            generated_at=generated_at,
            project_head=project_head,
        )
        issues.append(issue)
        bodies[body_path] = body
        emitted_decision_ids.add(blocker["id"])

    for action in action_plan.get("implementation_ready_actions", []):
        issue, body_path, body = _task_issue(
            action,
            evidence_by_id=evidence_by_id,
            session_id=session_ids_by_decision_id.get(action.get("decision_id", "")),
            generated_at=generated_at,
            project_head=project_head,
        )
        issues.append(issue)
        bodies[body_path] = body

    for risk in _risk_candidates(action_plan, sessions):
        if risk["id"] in emitted_decision_ids:
            continue
        issue, body_path, body = _risk_issue(
            risk,
            evidence_by_id=evidence_by_id,
            session_id=session_ids_by_decision_id.get(risk["id"]),
            generated_at=generated_at,
            project_head=project_head,
        )
        issues.append(issue)
        bodies[body_path] = body

    return issues, bodies


def _decision_issue(
    decision: dict[str, Any],
    *,
    evidence_by_id: dict[str, dict[str, Any]],
    session_id: str | None,
    generated_at: str | None,
    project_head: str | None,
) -> tuple[dict[str, Any], str, str]:
    decision_id = decision["id"]
    title = decision.get("title") or decision_id
    body_path = f"issues/{_path_component(decision_id)}-decision.md"
    labels = _stable_labels(
        [
            "decide-me",
            "decision",
            "blocker",
            decision.get("priority"),
            decision.get("domain"),
            decision.get("kind") if decision.get("kind") == "risk" else None,
        ]
    )
    issue = {
        "title": f"[decision] {title}",
        "labels": labels,
        "body_path": body_path,
        "source": {
            "decision_id": decision_id,
            "session_id": session_id,
        },
    }
    body = _render_template(
        "issue-decision.md",
        {
            "title": title,
            "summary": render_markdown_text(decision.get("accepted_answer")),
            "decision_id": decision_id,
            "session_id": session_id or "unknown",
            "priority": decision.get("priority") or "unknown",
            "status": decision.get("status") or "unknown",
            "domain": decision.get("domain") or "unknown",
            "kind": decision.get("kind") or "unknown",
            "resolvable_by": decision.get("resolvable_by") or "unknown",
            "evidence": render_markdown_list(_evidence_for_item(decision, evidence_by_id)),
            "generated_at": generated_at or "null",
            "project_head": project_head or "null",
        },
    )
    return issue, body_path, body


def _task_issue(
    action: dict[str, Any],
    *,
    evidence_by_id: dict[str, dict[str, Any]],
    session_id: str | None,
    generated_at: str | None,
    project_head: str | None,
) -> tuple[dict[str, Any], str, str]:
    decision_id = action.get("decision_id") or action.get("name") or "task"
    name = action.get("name") or decision_id
    body_path = f"issues/{_path_component(decision_id)}-task.md"
    issue = {
        "title": f"[task] {name}",
        "labels": _stable_labels(
            [
                "decide-me",
                "task",
                action.get("priority"),
                action.get("responsibility"),
                "implementation-ready",
            ]
        ),
        "body_path": body_path,
        "source": {
            "decision_id": action.get("decision_id"),
            "session_id": session_id,
        },
    }
    body = _render_template(
        "issue-task.md",
        {
            "title": name,
            "summary": render_markdown_text(action.get("summary")),
            "next_step": render_markdown_text(action.get("next_step")),
            "decision_id": action.get("decision_id") or "unknown",
            "session_id": session_id or "unknown",
            "priority": action.get("priority") or "unknown",
            "status": action.get("status") or "unknown",
            "responsibility": action.get("responsibility") or "unknown",
            "kind": action.get("kind") or "unknown",
            "evidence_source": action.get("evidence_source") or "none",
            "evidence": render_markdown_list(_evidence_for_item(action, evidence_by_id)),
            "generated_at": generated_at or "null",
            "project_head": project_head or "null",
        },
    )
    return issue, body_path, body


def _risk_issue(
    risk: dict[str, Any],
    *,
    evidence_by_id: dict[str, dict[str, Any]],
    session_id: str | None,
    generated_at: str | None,
    project_head: str | None,
) -> tuple[dict[str, Any], str, str]:
    risk_id = risk["id"]
    title = risk.get("title") or risk_id
    body_path = f"issues/{_path_component(risk_id)}-risk.md"
    issue = {
        "title": f"[risk] {title}",
        "labels": _stable_labels(["decide-me", "risk", risk.get("priority"), risk.get("domain")]),
        "body_path": body_path,
        "source": {
            "decision_id": risk_id,
            "session_id": session_id,
        },
    }
    body = _render_template(
        "issue-risk.md",
        {
            "title": title,
            "summary": render_markdown_text(risk.get("accepted_answer")),
            "decision_id": risk_id,
            "session_id": session_id or "unknown",
            "priority": risk.get("priority") or "unknown",
            "status": risk.get("status") or "unknown",
            "domain": risk.get("domain") or "unknown",
            "resolvable_by": risk.get("resolvable_by") or "unknown",
            "evidence": render_markdown_list(_evidence_for_item(risk, evidence_by_id)),
            "generated_at": generated_at or "null",
            "project_head": project_head or "null",
        },
    )
    return issue, body_path, body


def _conflict_issues(
    conflicts: list[dict[str, Any]],
    *,
    generated_at: str | None,
    project_head: str | None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    issues: list[dict[str, Any]] = []
    bodies: dict[str, str] = {}
    for conflict in conflicts:
        conflict_id = conflict["conflict_id"]
        body_path = f"issues/{_path_component(conflict_id)}-conflict.md"
        issue = {
            "title": f"[conflict] {conflict['kind']}",
            "labels": _stable_labels(["decide-me", "conflict"]),
            "body_path": body_path,
            "source": {
                "conflict_id": conflict_id,
                "session_ids": conflict.get("session_ids", []),
            },
        }
        body = _render_template(
            "issue-conflict.md",
            {
                "title": conflict["kind"],
                "summary": render_markdown_text(conflict.get("summary")),
                "conflict_id": conflict_id,
                "session_ids": render_markdown_list(conflict.get("session_ids", [])),
                "scope": "```json\n"
                + json.dumps(conflict.get("scope", {}), ensure_ascii=False, indent=2, sort_keys=True)
                + "\n```",
                "requires_resolution": str(bool(conflict.get("requires_resolution"))).lower(),
                "generated_at": generated_at or "null",
                "project_head": project_head or "null",
            },
        )
        issues.append(issue)
        bodies[body_path] = body
    return issues, bodies


def _risk_candidates(action_plan: dict[str, Any], sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _ = sessions
    by_id: dict[str, dict[str, Any]] = {}
    for risk in action_plan.get("risks", []):
        by_id.setdefault(risk["id"], risk)
    return [by_id[key] for key in sorted(by_id)]


def _evidence_by_id(action_plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: item
        for item in action_plan.get("evidence", [])
        if item.get("id")
    }


def _evidence_for_item(item: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]) -> list[str]:
    return stable_unique(
        evidence["ref"]
        for evidence_id in item.get("evidence_ids", [])
        if (evidence := evidence_by_id.get(evidence_id)) and evidence.get("ref")
    )


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


def _render_template(name: str, values: dict[str, Any]) -> str:
    template = (GITHUB_TEMPLATE_DIR / name).read_text(encoding="utf-8")
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", str(value))
    return rendered


def _stable_labels(values: list[str | None]) -> list[str]:
    labels: list[str] = []
    for value in values:
        if not value:
            continue
        if value not in labels:
            labels.append(value)
    return labels


def _issue_sort_key(issue: dict[str, Any]) -> tuple[int, str]:
    labels = issue.get("labels", [])
    issue_type = next((label for label in labels if label in TYPE_RANK), "")
    return (TYPE_RANK.get(issue_type, 99), issue.get("body_path", ""))


def _path_component(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in value)
    return cleaned.strip(".-") or "item"
