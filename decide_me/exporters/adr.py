from __future__ import annotations

from pathlib import Path
from typing import Any

from decide_me.exporters.common import (
    DecisionEventIndex,
    build_decision_event_index,
    decision_summary,
    lookup_decision,
    project_head,
    referenced_evidence,
    snapshot_generated_at,
    superseded_by,
)
from decide_me.exporters.render import (
    render_markdown_list,
    render_markdown_text,
    render_yaml,
    slugify,
)
from decide_me.store import load_runtime, read_event_log, runtime_paths


STRUCTURED_ADR_EXPORTABLE_STATUSES = {"accepted", "resolved-by-evidence"}


def export_structured_adr(
    ai_dir: str | Path, decision_id: str, *, include_invalidated: bool = False
) -> Path:
    paths = runtime_paths(ai_dir)
    bundle = load_runtime(paths)
    events = read_event_log(paths)
    decision = lookup_decision(bundle, decision_id)
    _require_structured_adr_exportable(decision, include_invalidated=include_invalidated)

    index = build_decision_event_index(events)
    title = decision["title"] or decision["id"]
    evidence = referenced_evidence(decision)
    template = (
        Path(__file__).resolve().parents[2] / "templates" / "structured-adr-template.md"
    ).read_text(encoding="utf-8")
    body = (
        template.replace("{{frontmatter}}", render_yaml(_frontmatter(decision, index, bundle, events)))
        .replace("{{decision_id}}", decision["id"])
        .replace("{{title}}", title)
        .replace("{{context}}", render_markdown_text(decision.get("context")))
        .replace("{{decision}}", render_markdown_text(decision_summary(decision)))
        .replace("{{alternatives}}", render_markdown_list(decision.get("options", [])))
        .replace("{{consequences}}", render_markdown_list(decision.get("notes", [])))
        .replace("{{revisit_triggers}}", render_markdown_list(decision.get("revisit_triggers", [])))
        .replace("{{evidence}}", render_markdown_list(evidence))
    )

    output = paths.adr_dir / "structured" / f"{decision['id']}-{slugify(title)}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(body.rstrip() + "\n", encoding="utf-8")
    return output


def _frontmatter(
    decision: dict[str, Any],
    index: DecisionEventIndex,
    bundle: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
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
        "supersedes": index.supersedes.get(decision_id, []),
        "superseded_by": superseded_by(decision, index),
        "depends_on": decision.get("depends_on", []),
        "evidence": referenced_evidence(decision),
        "risk": {
            "technical": None,
            "operational": None,
        },
        "audit": {
            "generated_at": snapshot_generated_at(bundle, events),
            "source": "decide-me",
            "project_head": project_head(bundle),
        },
    }


def _require_structured_adr_exportable(
    decision: dict[str, Any], *, include_invalidated: bool
) -> None:
    status = decision["status"]
    if status in STRUCTURED_ADR_EXPORTABLE_STATUSES:
        return
    if status == "invalidated":
        if not include_invalidated:
            raise ValueError(
                f"decision {decision['id']} is invalidated; pass --include-invalidated to export it"
            )
        if decision_summary(decision):
            return
        raise ValueError(
            f"decision {decision['id']} is invalidated and has no accepted or evidence-resolved summary"
        )
    raise ValueError(f"decision {decision['id']} is not exportable as a structured ADR")
