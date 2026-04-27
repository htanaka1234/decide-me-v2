from __future__ import annotations

from pathlib import Path
from typing import Any

from decide_me.exporters.render import render_markdown_list, render_markdown_text
from decide_me.exporters.traceability import (
    build_action_export_context,
    build_traceability_payload_from_context,
)
from decide_me.taxonomy import stable_unique


ARCHITECTURE_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "architecture"
CROSSCUTTING_TERMS = (
    "security",
    "privacy",
    "audit",
    "auth",
    "authentication",
    "authorization",
    "compliance",
    "risk",
)


def export_architecture_doc(
    ai_dir: str | Path,
    *,
    format: str,
    output: str | Path,
    session_ids: list[str] | None = None,
) -> Path:
    if format != "arc42":
        raise ValueError("format must be arc42")

    context = build_action_export_context(
        ai_dir,
        session_ids=session_ids,
        export_name="architecture document export",
    )
    body = render_arc42_document(context)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.rstrip() + "\n", encoding="utf-8")
    return path


def render_arc42_document(context: dict[str, Any]) -> str:
    bundle = context["bundle"]
    project = bundle["project_state"]["project"]
    sessions = context["sessions"]
    action_plan = context["action_plan"]
    traceability = build_traceability_payload_from_context(context)
    final_decisions = _final_decisions(sessions, bundle["project_state"], action_plan)

    template = (ARCHITECTURE_TEMPLATE_DIR / "arc42.md").read_text(encoding="utf-8")
    return (
        template.replace("{{generated_at}}", context["generated_at"] or "null")
        .replace("{{project_head}}", context["project_head"] or "null")
        .replace("{{project_name}}", render_markdown_text(project.get("name")))
        .replace("{{objective}}", render_markdown_text(project.get("objective")))
        .replace("{{current_milestone}}", render_markdown_text(project.get("current_milestone")))
        .replace("{{source_sessions}}", render_markdown_list(context["source_session_ids"]))
        .replace("{{session_goals}}", _render_session_goals(sessions))
        .replace("{{constraints}}", _render_decisions(_constraints(final_decisions)))
        .replace("{{context_scope}}", _render_context_scope(sessions, action_plan))
        .replace("{{solution_strategy}}", _render_decisions(_solution_decisions(final_decisions)))
        .replace("{{building_blocks}}", _render_building_blocks(action_plan))
        .replace("{{deployment_operations}}", _render_deployment_operations(final_decisions, action_plan))
        .replace("{{crosscutting_concepts}}", _render_decisions(_crosscutting_decisions(final_decisions)))
        .replace("{{architecture_decisions}}", _render_decisions(final_decisions))
        .replace("{{quality_requirements}}", _render_quality_requirements(traceability))
        .replace("{{risks_and_debt}}", _render_risks_and_debt(sessions, action_plan))
        .replace("{{glossary}}", _render_glossary(bundle["taxonomy_state"]))
    ).rstrip() + "\n"


def _final_decisions(
    sessions: list[dict[str, Any]],
    project_state: dict[str, Any],
    action_plan: dict[str, Any],
) -> list[dict[str, Any]]:
    objects = {obj["id"]: obj for obj in project_state.get("objects", [])}
    evidence_by_id = _evidence_by_id(action_plan)
    actions_by_decision = {
        action.get("decision_id"): action
        for action in action_plan.get("actions", [])
        if action.get("decision_id")
    }
    decisions: dict[str, dict[str, Any]] = {}
    for session in sessions:
        session_id = session["session"]["id"]
        for decision_id in session["close_summary"].get("object_ids", {}).get("accepted_decisions", []):
            decision = objects.get(decision_id)
            if not decision or decision.get("type") != "decision":
                continue
            metadata = decision.get("metadata", {})
            action = actions_by_decision.get(decision_id, {})
            item = {
                "id": decision_id,
                "title": decision.get("title"),
                "context": decision.get("body"),
                "accepted_answer": action.get("summary"),
                "status": decision.get("status"),
                "domain": metadata.get("domain"),
                "kind": metadata.get("kind"),
                "priority": metadata.get("priority"),
                "resolvable_by": metadata.get("resolvable_by"),
                "evidence_refs": _evidence_refs_for_item(action, evidence_by_id),
            }
            item["session_id"] = session_id
            decisions.setdefault(item["id"], item)
    return sorted(decisions.values(), key=lambda item: item["id"])


def _constraints(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [decision for decision in decisions if decision.get("kind") == "constraint"]


def _solution_decisions(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        decision
        for decision in decisions
        if decision.get("domain") in {"technical", "data", "product"}
        and decision.get("kind") != "constraint"
    ]


def _crosscutting_decisions(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        decision
        for decision in decisions
        if decision.get("domain") in {"legal", "data", "ops"}
        or decision.get("kind") in {"dependency", "risk", "constraint"}
        or _contains_crosscutting_term(decision)
    ]


def _contains_crosscutting_term(decision: dict[str, Any]) -> bool:
    text = " ".join(
        str(value).casefold()
        for value in (
            decision.get("id"),
            decision.get("title"),
            decision.get("accepted_answer"),
            decision.get("context"),
        )
        if value
    )
    return any(term in text for term in CROSSCUTTING_TERMS)


def _render_session_goals(sessions: list[dict[str, Any]]) -> str:
    goals = stable_unique(
        goal
        for session in sessions
        for goal in (
            session["close_summary"].get("work_item", {}).get("statement"),
            session["close_summary"].get("work_item", {}).get("title"),
        )
        if goal
    )
    return render_markdown_list(goals)


def _render_context_scope(sessions: list[dict[str, Any]], action_plan: dict[str, Any]) -> str:
    lines = [
        "Source sessions:",
        render_markdown_list([session["session"]["id"] for session in sessions]),
        "",
        "Workstreams:",
        _render_workstreams(action_plan.get("workstreams", [])),
    ]
    return "\n".join(lines)


def _render_building_blocks(action_plan: dict[str, Any]) -> str:
    lines = [
        "Workstreams:",
        _render_workstreams(action_plan.get("workstreams", [])),
        "",
        "Actions:",
        _render_actions(action_plan.get("actions", []), _evidence_by_id(action_plan)),
    ]
    return "\n".join(lines)


def _render_deployment_operations(
    decisions: list[dict[str, Any]], action_plan: dict[str, Any]
) -> str:
    ops_decisions = [decision for decision in decisions if decision.get("domain") == "ops"]
    ops_actions = [
        action
        for action in action_plan.get("actions", [])
        if action.get("responsibility") == "ops"
    ]
    lines = [
        "Ops decisions:",
        _render_decisions(ops_decisions),
        "",
        "Ops actions:",
        _render_actions(ops_actions, _evidence_by_id(action_plan)),
    ]
    return "\n".join(lines)


def _render_quality_requirements(traceability: dict[str, Any]) -> str:
    rows = traceability["rows"]
    ready_count = len([row for row in rows if row["implementation_ready"]])
    verified_count = len([row for row in rows if row["verification_defined"]])
    missing_tests = traceability["verification_gaps"]["missing_tests"]
    missing_evidence = traceability["verification_gaps"]["missing_evidence"]
    lines = [
        f"- Traceability rows: {len(rows)}",
        f"- Implementation-ready rows: {ready_count}",
        f"- Explicit verification rows: {verified_count}",
        f"- Missing tests: {len(missing_tests)}",
        f"- Missing evidence: {len(missing_evidence)}",
    ]
    if missing_tests:
        lines.append("- Verification gap report should be reviewed before implementation.")
    return "\n".join(lines)


def _render_risks_and_debt(sessions: list[dict[str, Any]], action_plan: dict[str, Any]) -> str:
    lines = [
        "Unresolved blockers:",
        _render_decisions(action_plan.get("blockers", [])),
        "",
        "Unresolved risks:",
        _render_decisions(action_plan.get("risks", [])),
        "",
        "Deferred risks:",
        "- none",
    ]
    return "\n".join(lines)


def _render_decisions(decisions: list[dict[str, Any]]) -> str:
    if not decisions:
        return "- none"
    lines = []
    for decision in sorted(decisions, key=lambda item: item["id"]):
        evidence_refs = decision.get("evidence_refs", [])
        evidence = ", ".join(evidence_refs) if evidence_refs else "none recorded"
        summary = decision.get("accepted_answer") or decision.get("summary") or decision.get("title")
        labels = [
            decision.get("domain"),
            decision.get("kind"),
            decision.get("status"),
            decision.get("session_id"),
        ]
        label = "; ".join(str(value) for value in labels if value)
        lines.append(
            f"- {decision['id']} ({label}): {render_markdown_text(summary)} Evidence: {evidence}."
        )
    return "\n".join(lines)


def _render_workstreams(workstreams: list[dict[str, Any]]) -> str:
    if not workstreams:
        return "- none"
    lines = []
    for workstream in workstreams:
        scope = ", ".join(workstream.get("scope", [])) or "none"
        ready = ", ".join(workstream.get("implementation_ready_scope", [])) or "none"
        lines.append(
            f"- {workstream['name']}: {workstream.get('summary') or 'No summary recorded.'} "
            f"Scope: {scope}. Implementation-ready: {ready}."
        )
    return "\n".join(lines)


def _render_actions(actions: list[dict[str, Any]], evidence_by_id: dict[str, dict[str, Any]]) -> str:
    if not actions:
        return "- none"
    lines = []
    for action in actions:
        ready = "yes" if action.get("implementation_ready") else "no"
        evidence = ", ".join(_evidence_refs_for_item(action, evidence_by_id)) or "none recorded"
        lines.append(
            f"- {action.get('decision_id') or 'unknown'}: "
            f"{action.get('name') or 'Action'} "
            f"(ready: {ready}; owner: {action.get('responsibility') or 'unknown'}). "
            f"{render_markdown_text(action.get('summary'))} Evidence: {evidence}."
        )
    return "\n".join(lines)


def _evidence_by_id(action_plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: item
        for item in action_plan.get("evidence", [])
        if item.get("id")
    }


def _evidence_refs_for_item(item: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]) -> list[str]:
    return stable_unique(
        evidence["ref"]
        for evidence_id in item.get("evidence_ids", [])
        if (evidence := evidence_by_id.get(evidence_id)) and evidence.get("ref")
    )


def _render_glossary(taxonomy_state: dict[str, Any]) -> str:
    nodes = [
        node
        for node in taxonomy_state.get("nodes", [])
        if node.get("status") == "active" and not str(node.get("id", "")).startswith("AXIS-")
    ]
    if not nodes:
        return "- none"
    return "\n".join(
        f"- {node['id']} ({node.get('axis') or 'tag'}): {node.get('label')}"
        for node in sorted(nodes, key=lambda item: item["id"])
    )
