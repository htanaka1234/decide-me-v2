from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import yaml

from scripts import evaluate_scenarios


REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_DIR = REPO_ROOT / "tests" / "scenarios"


class EvaluateScenariosScriptTests(unittest.TestCase):
    def test_json_run_succeeds_for_committed_scenarios(self) -> None:
        code, stdout, stderr = _run_runner(
            "--scenarios",
            str(SCENARIOS_DIR),
            "--format",
            "json",
        )

        self.assertEqual("", stderr)
        self.assertEqual(0, code)
        summary = json.loads(stdout)
        self.assertEqual("passed", summary["status"])
        expected_count = len(list(SCENARIOS_DIR.glob("*/scenario.yaml")))
        self.assertGreaterEqual(summary["scenario_count"], 6)
        self.assertEqual(expected_count, summary["scenario_count"])
        self.assertFalse(summary["update_snapshots"])
        self.assertTrue(all(item["status"] == "passed" for item in summary["scenarios"]))

    def test_single_scenario_directory_input_succeeds(self) -> None:
        code, stdout, _stderr = _run_runner(
            "--scenarios",
            str(SCENARIOS_DIR / "personal_planning"),
            "--format",
            "json",
        )

        self.assertEqual(0, code)
        summary = json.loads(stdout)
        self.assertEqual("passed", summary["status"])
        self.assertEqual(1, summary["scenario_count"])
        self.assertEqual("personal_planning", summary["scenarios"][0]["scenario_id"])

    def test_single_scenario_yaml_input_succeeds(self) -> None:
        code, stdout, _stderr = _run_runner(
            "--scenarios",
            str(SCENARIOS_DIR / "personal_planning" / "scenario.yaml"),
            "--format",
            "json",
        )

        self.assertEqual(0, code)
        summary = json.loads(stdout)
        self.assertEqual("passed", summary["status"])
        self.assertEqual(1, summary["scenario_count"])
        self.assertEqual("personal_planning", summary["scenarios"][0]["scenario_id"])

    def test_json_discovery_failure_includes_diagnostic_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing-scenarios"

            code, stdout, stderr = _run_runner(
                "--scenarios",
                str(missing),
                "--format",
                "json",
            )

            self.assertEqual("", stderr)
            self.assertEqual(1, code)
            summary = json.loads(stdout)
            self.assertEqual("failed", summary["status"])
            self.assertEqual(0, summary["scenario_count"])
            self.assertEqual([], summary["scenarios"])
            self.assertEqual("scenario_discovery", summary["failures"][0]["metric"])
            self.assertIn("scenario path does not exist", summary["failures"][0]["message"])

    def test_snapshot_mismatch_fails_without_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scenarios = _copy_one_scenario(Path(tmp), "personal_planning")
            expected = scenarios / "personal_planning" / "expected" / "document_outputs"
            (expected / "risk-register.json").unlink()
            (expected / "evaluation-report.json").write_text('{"changed": true}\n', encoding="utf-8")

            code, stdout, _stderr = _run_runner(
                "--scenarios",
                str(scenarios),
                "--format",
                "json",
            )

            self.assertEqual(1, code)
            summary = json.loads(stdout)
            result = summary["scenarios"][0]
            self.assertEqual("failed", summary["status"])
            self.assertEqual("failed", result["snapshot_status"])
            self.assertGreater(result["snapshot_mismatch_count"], 0)
            self.assertTrue(any("extra snapshots: risk-register.json" in item for item in result["snapshot_failures"]))
            self.assertTrue(any("--- expected/evaluation-report.json" in item for item in result["snapshot_failures"]))

    def test_update_snapshots_writes_copied_scenario_baselines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scenarios = _copy_one_scenario(Path(tmp), "personal_planning")
            expected = scenarios / "personal_planning" / "expected" / "document_outputs"
            (expected / "risk-register.json").unlink()
            (expected / "project-state.json").write_text('{"changed": true}\n', encoding="utf-8")

            code, stdout, _stderr = _run_runner(
                "--scenarios",
                str(scenarios),
                "--update-snapshots",
                "--format",
                "json",
            )

            self.assertEqual(0, code)
            summary = json.loads(stdout)
            result = summary["scenarios"][0]
            self.assertEqual("passed", summary["status"])
            self.assertEqual("updated", result["snapshot_status"])
            self.assertGreaterEqual(result["updated_snapshot_count"], 2)
            self.assertTrue((expected / "risk-register.json").is_file())
            self.assertNotEqual('{"changed": true}\n', (expected / "project-state.json").read_text(encoding="utf-8"))

            code, stdout, _stderr = _run_runner(
                "--scenarios",
                str(scenarios),
                "--format",
                "json",
            )

            self.assertEqual(0, code)
            self.assertEqual("passed", json.loads(stdout)["status"])

    def test_update_snapshots_is_skipped_when_evaluation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scenarios = _copy_one_scenario(Path(tmp), "personal_planning")
            decisions_file = scenarios / "personal_planning" / "expected" / "decisions.yaml"
            payload = yaml.safe_load(decisions_file.read_text(encoding="utf-8"))
            payload["required_domain_decision_types"].append(
                "missing_decision_type"
            )
            decisions_file.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
            expected_report = (
                scenarios
                / "personal_planning"
                / "expected"
                / "document_outputs"
                / "evaluation-report.json"
            )
            before = expected_report.read_text(encoding="utf-8")

            code, stdout, _stderr = _run_runner(
                "--scenarios",
                str(scenarios),
                "--update-snapshots",
                "--format",
                "json",
            )

            self.assertEqual(1, code)
            summary = json.loads(stdout)
            result = summary["scenarios"][0]
            self.assertEqual("failed", summary["status"])
            self.assertEqual("failed", result["evaluation_status"])
            self.assertEqual("failed", result["snapshot_status"])
            self.assertEqual(0, result["updated_snapshot_count"])
            self.assertIn("snapshot update skipped because evaluation failed", result["snapshot_failures"])
            self.assertEqual(before, expected_report.read_text(encoding="utf-8"))


def _run_runner(*args: str) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = evaluate_scenarios.main(list(args))
    return code, stdout.getvalue(), stderr.getvalue()


def _copy_one_scenario(tmp: Path, scenario_id: str) -> Path:
    scenarios = tmp / "scenarios"
    shutil.copytree(SCENARIOS_DIR / scenario_id, scenarios / scenario_id)
    return scenarios


if __name__ == "__main__":
    unittest.main()
