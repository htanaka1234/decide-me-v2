from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers.evaluation_assertions import assert_evaluation_report_matches_expectations
from tests.helpers.evaluation_scenarios import (
    EvaluationScenario,
    build_scenario_runtime,
    load_scenario,
    run_scenario_evaluation,
)
from tests.helpers.evaluation_snapshots import (
    assert_evaluation_snapshots_match,
    collect_evaluation_snapshots,
)
from tests.helpers.impact_runtime import event_hash_snapshot, runtime_state_snapshot


REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_DIR = REPO_ROOT / "tests" / "scenarios"
EXPECTED_SCENARIOS = {
    "career_plan",
    "household_project",
    "procurement_decision",
    "research_protocol",
    "software_refactor",
    "writing_project",
}


class EvaluationScenarioSnapshotTests(unittest.TestCase):
    def test_all_evaluation_scenario_snapshots_match_expected_outputs(self) -> None:
        scenario_paths = sorted(SCENARIOS_DIR.glob("*/scenario.yaml"))

        self.assertEqual(EXPECTED_SCENARIOS, {path.parent.name for path in scenario_paths})
        with tempfile.TemporaryDirectory() as tmp:
            work_root = Path(tmp)
            for scenario_path in scenario_paths:
                with self.subTest(scenario=scenario_path.parent.name):
                    scenario = load_scenario(scenario_path)
                    runtime = build_scenario_runtime(scenario, work_root)
                    event_before = event_hash_snapshot(runtime.ai_dir)
                    runtime_before = runtime_state_snapshot(runtime.ai_dir)

                    report = run_scenario_evaluation(scenario, runtime)
                    snapshots = collect_evaluation_snapshots(scenario, runtime, report)

                    self.assertEqual(event_before, event_hash_snapshot(runtime.ai_dir))
                    self.assertEqual(runtime_before, runtime_state_snapshot(runtime.ai_dir))
                    assert_evaluation_report_matches_expectations(self, scenario, report)
                    assert_evaluation_snapshots_match(self, scenario, snapshots)

    def test_snapshot_comparison_reports_missing_extra_and_changed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = root / "expected_outputs"
            expected.mkdir()
            (expected / ".gitkeep").write_text("", encoding="utf-8")
            (expected / "a.json").write_text('{"value": 1}\n', encoding="utf-8")
            (expected / "b.csv").write_text("id,value\nB,2\nA,1\n", encoding="utf-8")
            scenario = EvaluationScenario(
                data={"scenario_id": "demo_snapshot"},
                path=root / "scenario.yaml",
                root=root,
                seed_paths={},
            )

            with self.assertRaises(AssertionError) as raised:
                assert_evaluation_snapshots_match(
                    self,
                    scenario,
                    {
                        "a.json": '{"value": 2}\n',
                        "c.json": "{}\n",
                    },
                )

            message = str(raised.exception)
            self.assertIn("missing snapshots: b.csv", message)
            self.assertIn("extra snapshots: c.json", message)
            self.assertIn("--- expected/a.json", message)
            self.assertIn("+++ actual/a.json", message)


if __name__ == "__main__":
    unittest.main()
