from __future__ import annotations

from pathlib import Path
from typing import Any

from decide_me.exporters.common import (
    DecisionEventIndex,
    build_decision_event_index,
    decision_summary,
    project_head,
    referenced_evidence_refs,
    snapshot_generated_at,
    superseded_by,
)
from decide_me.exporters.render import render_table_cell, render_yaml
from decide_me.store import load_runtime, read_event_log, runtime_paths


DECISION_REGISTER_SCHEMA_VERSION = 1
REGISTER_STATUSES = {"accepted", "resolved-by-evidence", "deferred"}


def export_decision_register(
    ai_dir: str | Path, *, format: str = "yaml", include_invalidated: bool = False
) -> Path:
    if format not in {"yaml", "markdown"}:
        raise ValueError("decision register format must be yaml or markdown")

    paths = runtime_paths(ai_dir)
    bundle = load_runtime(paths)
    events = read_event_log(paths)
    register = build_decision_register(bundle, events, include_invalidated=include_invalidated)

    if format == "yaml":
        output = paths.exports_dir / "decision-register.yaml"
        body = render_yaml(register)
    else:
        output = paths.exports_dir / "decision-register.md"
        body = render_decision_register_markdown(register)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(body.rstrip() + "\n", encoding="utf-8")
    return output


def build_decision_register(
    bundle: dict[str, Any], events: list[dict[str, Any]], *, include_invalidated: bool = False
) -> dict[str, Any]:
    index = build_decision_event_index(events)
    return {
        "schema_version": DECISION_REGISTER_SCHEMA_VERSION,
        "generated_at": snapshot_generated_at(bundle, events),
        "project_head": project_head(bundle),
        "decisions": [
            _decision_register_item(decision, index)
            for decision in sorted(bundle["project_state"]["decisions"], key=lambda item: item["id"])
            if _include_decision(decision, include_invalidated=include_invalidated)
        ],
    }


def render_decision_register_markdown(register: dict[str, Any]) -> str:
    lines = [
        "# Decision Register",
        "",
        f"Generated at: {render_table_cell(register.get('generated_at')) or 'null'}",
        f"Project head: {render_table_cell(register.get('project_head')) or 'null'}",
        "",
        "| ID | Status | Domain | Priority | Session | Superseded By | Title | Summary |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for decision in register["decisions"]:
        lines.append(
            "| "
            + " | ".join(
                render_table_cell(decision.get(key))
                for key in (
                    "id",
                    "status",
                    "domain",
                    "priority",
                    "session_id",
                    "superseded_by",
                    "title",
                    "summary",
                )
            )
            + " |"
        )
    if not register["decisions"]:
        lines.append("| none |  |  |  |  |  |  |  |")
    return "\n".join(lines)


def _include_decision(decision: dict[str, Any], *, include_invalidated: bool) -> bool:
    if decision["status"] in REGISTER_STATUSES:
        return True
    return include_invalidated and decision["status"] == "invalidated"


def _decision_register_item(decision: dict[str, Any], index: DecisionEventIndex) -> dict[str, Any]:
    decision_id = decision["id"]
    return {
        "id": decision_id,
        "title": decision.get("title"),
        "status": decision["status"],
        "domain": decision["domain"],
        "kind": decision["kind"],
        "priority": decision["priority"],
        "frontier": decision["frontier"],
        "session_id": index.session_ids.get(decision_id),
        "accepted_via": decision.get("accepted_answer", {}).get("accepted_via"),
        "summary": decision_summary(decision),
        "superseded_by": superseded_by(decision, index),
        "depends_on": decision.get("depends_on", []),
        "evidence_refs": referenced_evidence_refs(decision),
        "invalidated_by": _invalidated_by(decision),
    }


def _invalidated_by(decision: dict[str, Any]) -> dict[str, Any] | None:
    invalidated_by = decision.get("invalidated_by")
    if not invalidated_by:
        return None
    return {
        "decision_id": invalidated_by.get("decision_id"),
        "reason": invalidated_by.get("reason"),
        "invalidated_at": invalidated_by.get("invalidated_at"),
    }
