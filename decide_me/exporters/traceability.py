from __future__ import annotations

import csv
from copy import deepcopy
from io import StringIO
from pathlib import Path
from typing import Any

from decide_me.exporters.common import project_head, snapshot_generated_at
from decide_me.exporters.render import render_markdown_list, render_table_cell
from decide_me.store import load_runtime, read_event_log, runtime_paths
from decide_me.suppression import apply_semantic_suppression_to_session
from decide_me.taxonomy import stable_unique


TRACEABILITY_SCHEMA_VERSION = 1
TRACEABILITY_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "traceability"
MATRIX_COLUMNS = [
    "Requirement ID",
    "Decision ID",
    "Session ID",
    "Action Slice",
    "Implementation Ready",
    "Evidence Source",
    "Risk",
    "Test / Verification",
    "Status",
]


def export_traceability(
    ai_dir: str | Path,
    *,
    format: str,
    output: str | Path,
    session_ids: list[str] | None = None,
) -> Path:
    if format not in {"csv", "markdown"}:
        raise ValueError("format must be one of: csv, markdown")

    payload = build_traceability_payload_for_runtime(ai_dir, session_ids=session_ids)
    if format == "csv":
        body = render_traceability_csv(payload)
    else:
        body = render_traceability_markdown(payload)
    return _write_text_output(output, body)


def export_verification_gaps(
    ai_dir: str | Path,
    *,
    output: str | Path,
    session_ids: list[str] | None = None,
) -> Path:
    payload = build_traceability_payload_for_runtime(ai_dir, session_ids=session_ids)
    return _write_text_output(output, render_verification_gaps_markdown(payload))


def build_traceability_payload_for_runtime(
    ai_dir: str | Path,
    *,
    session_ids: list[str] | None = None,
) -> dict[str, Any]:
    context = build_action_export_context(
        ai_dir,
        session_ids=session_ids,
        export_name="traceability export",
    )
    return build_traceability_payload_from_context(context)


def build_action_export_context(
    ai_dir: str | Path,
    *,
    session_ids: list[str] | None,
    export_name: str,
) -> dict[str, Any]:
    paths = runtime_paths(ai_dir)
    bundle = load_runtime(paths)
    events = read_event_log(paths)
    source_session_ids, sessions = _selected_closed_sessions(bundle, session_ids, export_name)
    resolved_conflicts = bundle["project_state"].get("session_graph", {}).get("resolved_conflicts", [])
    from decide_me.planner import assemble_action_plan, detect_conflicts

    conflicts = detect_conflicts(sessions, resolved_conflicts=resolved_conflicts)
    if conflicts:
        conflict_ids = ", ".join(conflict["conflict_id"] for conflict in conflicts)
        raise ValueError(f"unresolved session conflicts block {export_name}: {conflict_ids}")

    normalized_sessions = _sessions_after_resolutions(sessions, resolved_conflicts)
    return {
        "bundle": bundle,
        "events": events,
        "source_session_ids": source_session_ids,
        "sessions": normalized_sessions,
        "action_plan": assemble_action_plan(sessions, resolved_conflicts=resolved_conflicts),
        "generated_at": snapshot_generated_at(bundle, events),
        "project_head": project_head(bundle),
    }


def build_traceability_payload_from_context(context: dict[str, Any]) -> dict[str, Any]:
    rows = _traceability_rows(context["action_plan"], context["sessions"])
    gaps = _verification_gaps(rows)
    return {
        "schema_version": TRACEABILITY_SCHEMA_VERSION,
        "generated_at": context["generated_at"],
        "project_head": context["project_head"],
        "source_session_ids": context["source_session_ids"],
        "rows": rows,
        "verification_gaps": gaps,
    }


def render_traceability_csv(payload: dict[str, Any]) -> str:
    handle = StringIO()
    writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in payload["rows"]:
        writer.writerow(_matrix_row(row))
    return handle.getvalue().rstrip() + "\n"


def render_traceability_markdown(payload: dict[str, Any]) -> str:
    rows = _render_markdown_matrix_rows(payload["rows"])
    template = (TRACEABILITY_TEMPLATE_DIR / "matrix.md").read_text(encoding="utf-8")
    return (
        template.replace("{{generated_at}}", payload["generated_at"] or "null")
        .replace("{{project_head}}", payload["project_head"] or "null")
        .replace("{{source_sessions}}", render_markdown_list(payload["source_session_ids"]))
        .replace("{{rows}}", rows)
    ).rstrip() + "\n"


def render_verification_gaps_markdown(payload: dict[str, Any]) -> str:
    gaps = payload["verification_gaps"]
    template = (TRACEABILITY_TEMPLATE_DIR / "verification-gaps.md").read_text(encoding="utf-8")
    return (
        template.replace("{{generated_at}}", payload["generated_at"] or "null")
        .replace("{{project_head}}", payload["project_head"] or "null")
        .replace("{{source_sessions}}", render_markdown_list(payload["source_session_ids"]))
        .replace("{{missing_tests}}", _render_gap_section(gaps["missing_tests"]))
        .replace("{{missing_evidence}}", _render_gap_section(gaps["missing_evidence"]))
    ).rstrip() + "\n"


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


def _traceability_rows(action_plan: dict[str, Any], sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    session_ids_by_decision_id = _session_ids_by_decision_id(sessions)
    rows: list[dict[str, Any]] = []

    for action_slice in action_plan.get("action_slices", []):
        decision_id = action_slice.get("decision_id")
        rows.append(
            _row(
                row_type="action-slice",
                decision_id=decision_id,
                session_id=session_ids_by_decision_id.get(decision_id),
                action_slice=action_slice.get("name") or decision_id or "Action slice",
                implementation_ready=bool(action_slice.get("implementation_ready")),
                evidence_source=action_slice.get("evidence_source"),
                risk=_risk_label(action_slice),
                status=action_slice.get("status") or "unknown",
                evidence_refs=action_slice.get("evidence_refs", []),
                source=action_slice,
            )
        )

    emitted_open_ids: set[str] = set()
    for blocker in action_plan.get("blockers", []):
        decision_id = blocker["id"]
        emitted_open_ids.add(decision_id)
        rows.append(
            _row(
                row_type="blocker",
                decision_id=decision_id,
                session_id=session_ids_by_decision_id.get(decision_id),
                action_slice=f"Resolve: {blocker.get('title') or decision_id}",
                implementation_ready=False,
                evidence_source=blocker.get("evidence_source"),
                risk=_risk_label(blocker, blocker=True),
                status=blocker.get("status") or "unresolved",
                evidence_refs=blocker.get("evidence_refs", []),
                source=blocker,
            )
        )

    for risk in action_plan.get("risks", []):
        decision_id = risk["id"]
        if decision_id in emitted_open_ids:
            continue
        rows.append(
            _row(
                row_type="risk",
                decision_id=decision_id,
                session_id=session_ids_by_decision_id.get(decision_id),
                action_slice=f"Mitigate: {risk.get('title') or decision_id}",
                implementation_ready=False,
                evidence_source=risk.get("evidence_source"),
                risk=_risk_label(risk, risk=True),
                status=risk.get("status") or "unresolved",
                evidence_refs=risk.get("evidence_refs", []),
                source=risk,
            )
        )

    rows = sorted(rows, key=_row_sort_key)
    for index, row in enumerate(rows, start=1):
        row["requirement_id"] = f"R-{index:03d}"
    return rows


def _row(
    *,
    row_type: str,
    decision_id: str | None,
    session_id: str | None,
    action_slice: str,
    implementation_ready: bool,
    evidence_source: str | None,
    risk: str,
    status: str,
    evidence_refs: list[str],
    source: dict[str, Any],
) -> dict[str, Any]:
    verification = _test_verification(source)
    row = {
        "requirement_id": None,
        "decision_id": decision_id,
        "session_id": session_id,
        "action_slice": action_slice,
        "implementation_ready": implementation_ready,
        "evidence_source": evidence_source or "none",
        "risk": risk,
        "test_verification": verification,
        "verification_defined": verification is not None,
        "status": status,
        "evidence_refs": stable_unique(evidence_refs),
        "row_type": row_type,
    }
    row["suggested_verification"] = _suggested_verification(row, source)
    return row


def _session_ids_by_decision_id(sessions: list[dict[str, Any]]) -> dict[str, str]:
    by_id: dict[str, str] = {}
    for session in sessions:
        session_id = session["session"]["id"]
        close_summary = session["close_summary"]
        for section in (
            "accepted_decisions",
            "deferred_decisions",
            "unresolved_blockers",
            "unresolved_risks",
        ):
            for item in close_summary.get(section, []):
                by_id.setdefault(item["id"], session_id)
        for action_slice in close_summary.get("candidate_action_slices", []):
            decision_id = action_slice.get("decision_id")
            if decision_id:
                by_id.setdefault(decision_id, session_id)
    return by_id


def _test_verification(source: dict[str, Any]) -> str | None:
    evidence_refs = source.get("evidence_refs", [])
    test_refs = [ref for ref in evidence_refs if _is_test_ref(ref)]
    if source.get("evidence_source") == "tests":
        if evidence_refs:
            return "tests evidence: " + ", ".join(evidence_refs)
        return "tests evidence"
    if test_refs:
        return "tests evidence: " + ", ".join(test_refs)
    return None


def _verification_gaps(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "missing_tests": [
            _gap(row, "No explicit test or verification evidence recorded")
            for row in rows
            if row["implementation_ready"] and not row["verification_defined"]
        ],
        "missing_evidence": [
            _gap(row, "No evidence_refs recorded")
            for row in rows
            if not row["evidence_refs"]
        ],
    }


def _gap(row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "requirement_id": row["requirement_id"],
        "decision_id": row["decision_id"],
        "session_id": row["session_id"],
        "action_slice": row["action_slice"],
        "reason": reason,
        "suggested_verification": row["suggested_verification"],
    }


def _suggested_verification(row: dict[str, Any], source: dict[str, Any]) -> str:
    text = " ".join(
        str(value).casefold()
        for value in (
            row.get("action_slice"),
            row.get("decision_id"),
            source.get("summary"),
            source.get("next_step"),
            source.get("responsibility"),
            source.get("resolvable_by"),
        )
        if value
    )
    if any(token in text for token in ("cli", "command", "subcommand", "scripts/decide_me.py")):
        return "CLI test plus schema validation"
    if any(
        token in text
        for token in (
            "export",
            "render",
            "template",
            "markdown",
            "csv",
            "yaml",
            "json",
            "adr",
            "issue",
            "draft",
            "agent instruction",
            "architecture",
            "traceability",
        )
    ):
        return "snapshot test plus schema validation"
    if source.get("resolvable_by") == "docs":
        return "documentation snapshot check"
    if source.get("resolvable_by") == "tests":
        return "regression test"
    if source.get("domain") == "ops" or source.get("responsibility") == "ops":
        return "operational smoke test"
    if row.get("risk") != "none":
        return "risk mitigation review"
    return "unit or integration test"


def _risk_label(item: dict[str, Any], *, blocker: bool = False, risk: bool = False) -> str:
    labels: list[str] = []
    if item.get("kind") == "risk" or risk:
        labels.append("risk")
    if blocker:
        labels.append("blocker")
    return "; ".join(labels) if labels else "none"


def _is_test_ref(ref: str) -> bool:
    normalized = ref.replace("\\", "/").casefold()
    return (
        normalized.startswith("tests/")
        or "/tests/" in normalized
        or normalized.startswith("test/")
        or "/test/" in normalized
        or normalized.endswith("_test.py")
        or normalized.endswith(".test.js")
        or normalized.endswith(".test.ts")
        or normalized.endswith(".spec.js")
        or normalized.endswith(".spec.ts")
    )


def _row_sort_key(row: dict[str, Any]) -> tuple[int, str, str, str]:
    row_type_rank = {"action-slice": 0, "blocker": 1, "risk": 2}
    return (
        row_type_rank.get(row["row_type"], 99),
        row.get("decision_id") or "",
        row.get("session_id") or "",
        row.get("action_slice") or "",
    )


def _matrix_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "Requirement ID": row["requirement_id"] or "",
        "Decision ID": row["decision_id"] or "",
        "Session ID": row["session_id"] or "",
        "Action Slice": row["action_slice"],
        "Implementation Ready": "true" if row["implementation_ready"] else "false",
        "Evidence Source": row["evidence_source"],
        "Risk": row["risk"],
        "Test / Verification": row["test_verification"] or "none defined",
        "Status": row["status"],
    }


def _render_markdown_matrix_rows(rows: list[dict[str, Any]]) -> str:
    header = "| " + " | ".join(MATRIX_COLUMNS) + " |"
    separator = "| " + " | ".join("---" for _ in MATRIX_COLUMNS) + " |"
    body = [
        "| " + " | ".join(render_table_cell(value) for value in _matrix_row(row).values()) + " |"
        for row in rows
    ]
    if not body:
        body.append("| " + " | ".join("" for _ in MATRIX_COLUMNS) + " |")
    return "\n".join([header, separator, *body])


def _render_gap_section(gaps: list[dict[str, Any]]) -> str:
    if not gaps:
        return "- none"
    rendered = []
    for gap in gaps:
        label = gap["decision_id"] or gap["requirement_id"] or "unknown"
        rendered.extend(
            [
                f"- {label}: {gap['action_slice']}",
                f"  - Requirement ID: {gap['requirement_id']}",
                f"  - Session ID: {gap['session_id'] or 'unknown'}",
                f"  - Reason: {gap['reason']}",
                f"  - Suggested verification: {gap['suggested_verification']}",
            ]
        )
    return "\n".join(rendered)


def _write_text_output(output: str | Path, body: str) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.rstrip() + "\n", encoding="utf-8")
    return path
