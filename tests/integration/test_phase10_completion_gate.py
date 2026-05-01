from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from scripts import evaluate_scenarios
from tests.helpers.evaluation_scenarios import load_scenario


REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_DIR = REPO_ROOT / "tests" / "scenarios"
INITIAL_SCENARIOS = {
    "career_plan",
    "household_project",
    "procurement_decision",
    "research_protocol",
    "software_refactor",
    "writing_project",
}
REQUIRED_DOMAIN_PACKS = {"generic", "software", "research", "procurement"}
REQUIRED_DOCUMENT_TYPES = {
    "decision-brief",
    "action-plan",
    "review-memo",
    "research-plan",
    "comparison-table",
}
REQUIRED_DOCUMENT_FORMATS = {"json", "markdown", "csv"}
CORE_SNAPSHOT_FILES = {
    "project-state.json",
    "evaluation-report.json",
    "safety-gates.json",
    "risk-register.json",
}


class Phase10CompletionGateTests(unittest.TestCase):
    def test_evaluation_runner_passes_all_committed_scenarios(self) -> None:
        code, stdout, stderr = _run_runner(
            "--scenarios",
            str(SCENARIOS_DIR),
            "--format",
            "json",
        )

        self.assertEqual("", stderr)
        self.assertEqual(0, code)
        summary = json.loads(stdout)
        scenario_paths = sorted(SCENARIOS_DIR.glob("*/scenario.yaml"))
        self.assertEqual("passed", summary["status"])
        self.assertGreaterEqual(summary["scenario_count"], 6)
        self.assertEqual(len(scenario_paths), summary["scenario_count"])
        for result in summary["scenarios"]:
            with self.subTest(scenario=result["scenario_id"]):
                self.assertEqual("passed", result["status"])
                self.assertEqual("passed", result["evaluation_status"])
                self.assertEqual("passed", result["snapshot_status"])
                self.assertEqual(0, result["failure_count"])
                self.assertEqual(0, result["snapshot_mismatch_count"])
                self.assertEqual([], result["failures"])
                self.assertEqual([], result["snapshot_failures"])

    def test_initial_scenario_contracts_cover_phase10_acceptance_surface(self) -> None:
        scenarios = _load_scenarios()
        by_id = {scenario.scenario_id: scenario.data for scenario in scenarios}

        self.assertTrue(INITIAL_SCENARIOS.issubset(set(by_id)))
        self.assertTrue(REQUIRED_DOMAIN_PACKS.issubset({scenario.domain_pack for scenario in scenarios}))
        self.assertTrue(REQUIRED_DOCUMENT_TYPES.issubset(_document_types(scenarios)))
        self.assertTrue(REQUIRED_DOCUMENT_FORMATS.issubset(_document_formats(scenarios)))

        software_conflicts = by_id["software_refactor"]["evaluation"]["expected_conflicts"]
        self.assertEqual(1, software_conflicts["count"])
        self.assertIn(
            "decision-accepted-proposal-mismatch",
            software_conflicts["required_conflict_types"],
        )

        for scenario_id in ["research_protocol", "procurement_decision"]:
            with self.subTest(scenario=scenario_id):
                evaluation = by_id[scenario_id]["evaluation"]
                self.assertTrue(evaluation["expected_evidence_coverage"]["required_evidence_requirement_ids"])
                self.assertTrue(evaluation["expected_risks"]["required_domain_risk_types"])
                self.assertTrue(evaluation["expected_risks"]["required_risk_tiers"])
                safety = evaluation["expected_safety_gates"]
                self.assertTrue(safety["required_rule_ids"])
                self.assertTrue(safety["required_approval_thresholds"])
                self.assertGreaterEqual(safety["min_approval_required_count"], 1)

        for scenario_id in ["career_plan", "household_project"]:
            with self.subTest(scenario=scenario_id):
                safety = by_id[scenario_id]["evaluation"]["expected_safety_gates"]
                self.assertEqual(0, safety["max_approval_required_count"])
                self.assertIn("human_review", safety["forbidden_approval_thresholds"])
                self.assertIn("external_review", safety["forbidden_approval_thresholds"])

    def test_committed_snapshot_baselines_cover_expected_outputs(self) -> None:
        for scenario in _load_scenarios():
            expected_outputs = scenario.root / "expected_outputs"
            with self.subTest(scenario=scenario.scenario_id):
                self.assertTrue(expected_outputs.is_dir())
                for name in CORE_SNAPSHOT_FILES:
                    self.assertTrue((expected_outputs / name).is_file(), name)
                for document in scenario.evaluation["expected_documents"]:
                    document_type = document["type"]
                    self.assertTrue(
                        (expected_outputs / "documents" / f"{document_type}.json").is_file(),
                        document_type,
                    )
                    if document["format"] in {"markdown", "csv"}:
                        suffix = "md" if document["format"] == "markdown" else "csv"
                        self.assertTrue(
                            (expected_outputs / "documents" / f"{document_type}.{suffix}").is_file(),
                            document_type,
                        )


def _run_runner(*args: str) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = evaluate_scenarios.main(list(args))
    return code, stdout.getvalue(), stderr.getvalue()


def _load_scenarios() -> list[Any]:
    return [load_scenario(path) for path in sorted(SCENARIOS_DIR.glob("*/scenario.yaml"))]


def _document_types(scenarios: list[Any]) -> set[str]:
    return {
        document["type"]
        for scenario in scenarios
        for document in scenario.evaluation["expected_documents"]
    }


def _document_formats(scenarios: list[Any]) -> set[str]:
    return {
        document["format"]
        for scenario in scenarios
        for document in scenario.evaluation["expected_documents"]
    }


if __name__ == "__main__":
    unittest.main()
