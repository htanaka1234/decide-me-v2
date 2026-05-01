from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from decide_me.documents.compiler import compile_document
from decide_me.documents.merge import managed_region
from decide_me.documents.render_csv import render_csv_document
from decide_me.documents.render_markdown import render_markdown_document
from decide_me.domains import load_domain_registry
from decide_me.registers import build_risk_register
from decide_me.safety_gate import build_safety_gate_report
from decide_me.store import load_runtime, runtime_paths
from tests.helpers.evaluation_scenarios import EvaluationScenario, ScenarioRuntime
from tests.helpers.snapshot_normalization import (
    normalize_csv_snapshot,
    normalize_markdown_snapshot,
    normalize_snapshot_text,
    stable_json,
)


def collect_evaluation_snapshots(
    scenario: EvaluationScenario,
    runtime: ScenarioRuntime,
    report: dict[str, Any],
) -> dict[str, str]:
    bundle = load_runtime(runtime_paths(runtime.ai_dir))
    project_state = bundle["project_state"]
    snapshots = {
        "project-state.selected.json": stable_json(project_state),
        "evaluation-report.json": stable_json(report),
        "safety-gates.json": stable_json(
            build_safety_gate_report(
                project_state,
                now=scenario.evaluation["now"],
                domain_registry=load_domain_registry(runtime.ai_dir),
            )
        ),
        "risk-register.json": stable_json(build_risk_register(project_state)),
    }
    for expected in scenario.evaluation["expected_documents"]:
        document_type = expected["type"]
        document = compile_document(
            runtime.ai_dir,
            document_type=document_type,
            session_ids=runtime.closed_session_ids,
            domain_pack_id=scenario.domain_pack,
            now=scenario.evaluation["now"],
        )
        snapshots[f"documents/{document_type}.json"] = stable_json(document)
        if expected["format"] == "markdown":
            markdown = managed_region(
                render_markdown_document(document),
                document_type=document_type,
                project_head=document.get("project_head"),
            )
            snapshots[f"documents/{document_type}.md"] = normalize_markdown_snapshot(markdown)
        elif expected["format"] == "csv":
            snapshots[f"documents/{document_type}.csv"] = normalize_csv_snapshot(
                render_csv_document(document)
            )
    return dict(sorted(snapshots.items()))


def assert_evaluation_snapshots_match(
    testcase: Any,
    scenario: EvaluationScenario,
    actual_snapshots: dict[str, str],
) -> None:
    expected_snapshots = load_expected_snapshots(scenario.root / "expected_outputs")
    expected_keys = set(expected_snapshots)
    actual_keys = set(actual_snapshots)
    missing = sorted(expected_keys - actual_keys)
    extra = sorted(actual_keys - expected_keys)
    messages = []
    if missing:
        messages.append("missing snapshots: " + ", ".join(missing))
    if extra:
        messages.append("extra snapshots: " + ", ".join(extra))
    for key in sorted(expected_keys & actual_keys):
        expected = expected_snapshots[key]
        actual = normalize_snapshot_text(key, actual_snapshots[key])
        if expected != actual:
            messages.append(_snapshot_diff(key, expected, actual))
    if messages:
        testcase.fail(f"{scenario.scenario_id} snapshot mismatch\n\n" + "\n\n".join(messages))


def load_expected_snapshots(root: Path) -> dict[str, str]:
    snapshots: dict[str, str] = {}
    if not root.exists():
        return snapshots
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == ".gitkeep":
            continue
        key = path.relative_to(root).as_posix()
        snapshots[key] = normalize_snapshot_text(key, path.read_text(encoding="utf-8"))
    return snapshots


def _snapshot_diff(key: str, expected: str, actual: str) -> str:
    return "".join(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile=f"expected/{key}",
            tofile=f"actual/{key}",
        )
    ).rstrip()
