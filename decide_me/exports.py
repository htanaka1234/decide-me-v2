from __future__ import annotations

from pathlib import Path
from typing import Any

from decide_me.events import utc_now
from decide_me.exporters.adr import export_structured_adr
from decide_me.exporters.decision_register import export_decision_register
from decide_me.store import load_runtime, runtime_paths


def export_adr(ai_dir: str, decision_id: str) -> Path:
    paths = runtime_paths(ai_dir)
    bundle = load_runtime(paths)
    decision = _lookup_decision(bundle, decision_id)
    if decision["status"] not in {"accepted", "resolved-by-evidence"}:
        raise ValueError(f"decision {decision_id} is not accepted")
    if decision["domain"] != "technical":
        raise ValueError(f"decision {decision_id} is not technical")

    template = (Path(__file__).resolve().parent.parent / "templates" / "adr-template.md").read_text(
        encoding="utf-8"
    )
    body = (
        template.replace("{{decision_id}}", decision["id"])
        .replace("{{title}}", decision["title"] or decision["id"])
        .replace("{{context}}", decision.get("context") or "No additional context recorded.")
        .replace(
            "{{decision}}",
            decision["accepted_answer"]["summary"] or decision["resolved_by_evidence"]["summary"] or "",
        )
        .replace("{{consequences}}", _render_list(decision.get("revisit_triggers", [])))
        .replace("{{evidence}}", _render_list(decision.get("evidence_refs", [])))
    )
    slug = _slugify(decision["title"] or decision["id"])
    output = paths.adr_dir / f"{decision['id']}-{slug}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(body + "\n", encoding="utf-8")
    return output


def export_plan(ai_dir: str, plan: dict[str, Any]) -> Path:
    paths = runtime_paths(ai_dir)
    paths.plans_dir.mkdir(parents=True, exist_ok=True)
    timestamp = utc_now().replace(":", "").replace("-", "")
    if plan["status"] == "conflicts":
        body = _render_conflicts(plan)
        output = paths.plans_dir / f"conflicts-{timestamp}.md"
    else:
        template = (
            Path(__file__).resolve().parent.parent / "templates" / "plan-template.md"
        ).read_text(encoding="utf-8")
        action_plan = plan["action_plan"]
        body = (
            template.replace("{{generated_at}}", plan["generated_at"])
            .replace("{{source_sessions}}", _render_list(plan["source_session_ids"]))
            .replace("{{readiness}}", action_plan["readiness"])
            .replace("{{goals}}", _render_list(action_plan["goals"]))
            .replace("{{workstreams}}", _render_dict_list(action_plan["workstreams"]))
            .replace(
                "{{implementation_ready_slices}}",
                _render_action_slices(action_plan.get("implementation_ready_slices", [])),
            )
            .replace("{{action_slices}}", _render_action_slices(action_plan["action_slices"]))
            .replace("{{blockers}}", _render_dict_list(action_plan["blockers"]))
            .replace("{{risks}}", _render_dict_list(action_plan["risks"]))
        )
        output = paths.plans_dir / f"plan-{timestamp}.md"
    output.write_text(body + "\n", encoding="utf-8")
    return output


def _lookup_decision(bundle: dict[str, Any], decision_id: str) -> dict[str, Any]:
    for decision in bundle["project_state"]["decisions"]:
        if decision["id"] == decision_id:
            return decision
    raise ValueError(f"unknown decision: {decision_id}")


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    pieces = ["".join(ch for ch in token if ch.isalnum()) for token in lowered.split()]
    return "-".join(piece for piece in pieces if piece) or "decision"


def _render_list(values: list[Any]) -> str:
    if not values:
        return "- none"
    return "\n".join(f"- {value}" for value in values)


def _render_dict_list(values: list[dict[str, Any]]) -> str:
    if not values:
        return "- none"
    rendered = []
    for value in values:
        name = value.get("name") or value.get("id") or "item"
        detail = value.get("summary") or value.get("accepted_answer") or value.get("scope") or ""
        rendered.append(f"- {name}: {detail}".rstrip(": "))
    return "\n".join(rendered)


def _render_action_slices(values: list[dict[str, Any]]) -> str:
    if not values:
        return "- none"
    rendered = []
    for value in values:
        labels = []
        if value.get("decision_id"):
            labels.append(value["decision_id"])
        if value.get("priority"):
            labels.append(value["priority"])
        if value.get("implementation_ready"):
            labels.append("implementation-ready")
        if value.get("evidence_source"):
            labels.append(f"via {value['evidence_source']}")
        header = value.get("name") or value.get("decision_id") or "item"
        if labels:
            header = f"{header} [{'; '.join(labels)}]"
        details = [value.get("summary") or ""]
        next_step = value.get("next_step")
        if next_step and next_step != details[0]:
            details.append(f"Next: {next_step}")
        rendered.append(f"- {header}: {' '.join(part for part in details if part).strip()}".rstrip(": "))
    return "\n".join(rendered)


def _render_conflicts(plan: dict[str, Any]) -> str:
    lines = [
        "# Conflicts",
        "",
        f"Generated at: {plan['generated_at']}",
        "",
        "Source sessions:",
        _render_list(plan["source_session_ids"]),
        "",
        "Detected conflicts:",
        _render_dict_list(plan["conflicts"]),
    ]
    return "\n".join(lines)
