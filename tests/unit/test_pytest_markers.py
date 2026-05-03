from __future__ import annotations

import unittest

from tests.conftest import markers_for_test_path


class PytestMarkerClassificationTests(unittest.TestCase):
    def test_unit_tests_are_marked_unit(self) -> None:
        self.assertEqual(("unit",), markers_for_test_path("tests/unit/test_events.py"))

    def test_integration_tests_are_marked_integration(self) -> None:
        self.assertEqual(("integration",), markers_for_test_path("tests/integration/test_runtime_flow.py"))

    def test_smoke_tests_are_marked_smoke(self) -> None:
        self.assertEqual(("smoke",), markers_for_test_path("tests/smoke/test_full_object_runtime_flow.py"))

    def test_evaluation_scenario_integration_is_slow_evaluation_phase_gate(self) -> None:
        markers = set(markers_for_test_path("tests/integration/test_evaluation_scenarios.py"))

        self.assertEqual({"evaluation", "integration", "phase_gate", "slow"}, markers)

    def test_phase_specific_integration_tests_are_phase_gate(self) -> None:
        markers = set(markers_for_test_path("tests/integration/test_phase10_distribution_artifact.py"))

        self.assertEqual({"integration", "phase_gate"}, markers)

    def test_phase10_gate_script_tests_are_phase_gate(self) -> None:
        markers = set(markers_for_test_path("tests/integration/test_phase10_gate_script.py"))

        self.assertEqual({"integration", "phase_gate"}, markers)

    def test_evaluation_helper_units_are_unit_evaluation(self) -> None:
        markers = set(markers_for_test_path("tests/unit/test_evaluation_scenario_helpers.py"))

        self.assertEqual({"evaluation", "unit"}, markers)


if __name__ == "__main__":
    unittest.main()
