from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers.evaluation_assertions import assert_evaluation_report_matches_expectations
from tests.helpers.evaluation_scenarios import (
    build_scenario_runtime,
    load_scenario,
    run_scenario_evaluation,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_DIR = REPO_ROOT / "tests" / "scenarios"
EXPECTED_SCENARIOS = {
    "operations_incident",
    "personal_planning",
    "policy_interpretation",
    "procurement_decision",
    "research_protocol",
    "software_project",
    "writing_project",
}
# These are the committed Phase 11 benchmark scenarios, not a partial allow-list.
# Adding exploratory scenarios under tests/scenarios intentionally requires updating
# both EXPECTED_SCENARIOS and EXPECTED_SCENARIO_PACKS.
EXPECTED_SCENARIO_PACKS = {
    "operations_incident": "operations",
    "personal_planning": "personal_planning",
    "policy_interpretation": "generic",
    "procurement_decision": "procurement",
    "research_protocol": "research",
    "software_project": "software",
    "writing_project": "writing",
}


class EvaluationScenarioFixtureTests(unittest.TestCase):
    def test_all_initial_scenarios_pass_evaluation_smoke(self) -> None:
        scenario_paths = sorted(SCENARIOS_DIR.glob("*/scenario.yaml"))

        self.assertEqual(
            EXPECTED_SCENARIOS,
            {path.parent.name for path in scenario_paths},
        )
        with tempfile.TemporaryDirectory() as tmp:
            work_root = Path(tmp)
            for scenario_path in scenario_paths:
                with self.subTest(scenario=scenario_path.parent.name):
                    self.assertTrue(
                        (scenario_path.parent / "expected" / "document_outputs" / ".gitkeep").exists(),
                        "scenario expected/document_outputs placeholder is missing",
                    )
                    scenario = load_scenario(scenario_path)
                    runtime = build_scenario_runtime(scenario, work_root)
                    report = run_scenario_evaluation(scenario, runtime)

                    assert_evaluation_report_matches_expectations(self, scenario, report)

    def test_initial_scenarios_use_specific_domain_packs(self) -> None:
        scenario_paths = sorted(SCENARIOS_DIR.glob("*/scenario.yaml"))

        actual = {
            path.parent.name: load_scenario(path).domain_pack
            for path in scenario_paths
        }

        self.assertEqual(EXPECTED_SCENARIO_PACKS, actual)


if __name__ == "__main__":
    unittest.main()
