from __future__ import annotations

import unittest

from tests.conftest import markers_for_test_path


class PytestMarkerClassificationTests(unittest.TestCase):
    def test_unit_tests_are_marked_unit(self) -> None:
        self.assertEqual(("unit",), markers_for_test_path("tests/unit/test_events.py"))

    def test_integration_tests_are_marked_integration(self) -> None:
        self.assertEqual(("integration",), markers_for_test_path("tests/integration/test_runtime_flow.py"))

    def test_smoke_tests_are_marked_smoke_and_phase_gate(self) -> None:
        markers = set(markers_for_test_path("tests/smoke/test_full_object_runtime_flow.py"))

        self.assertEqual({"phase_gate", "smoke"}, markers)

    def test_evaluation_scenario_integration_is_slow_evaluation_phase_gate(self) -> None:
        markers = set(markers_for_test_path("tests/integration/test_evaluation_scenarios.py"))

        self.assertEqual({"evaluation", "integration", "phase_gate", "slow"}, markers)

    def test_phase_specific_integration_tests_are_phase_gate(self) -> None:
        markers = set(markers_for_test_path("tests/integration/test_phase11_distribution_artifact.py"))

        self.assertEqual({"integration", "phase_gate"}, markers)

    def test_phase11_gate_script_tests_are_phase_gate(self) -> None:
        markers = set(markers_for_test_path("tests/integration/test_phase11_gate_script.py"))

        self.assertEqual({"integration", "phase_gate"}, markers)

    def test_phase_gate_units_are_explicit_contract_subset(self) -> None:
        for path in [
            "tests/unit/test_evaluation_report_schema.py",
            "tests/unit/test_evaluation_scenario_schema.py",
            "tests/unit/test_pytest_markers.py",
        ]:
            with self.subTest(path=path):
                self.assertEqual(
                    {"evaluation", "phase_gate", "unit"} if "evaluation_" in path else {"phase_gate", "unit"},
                    set(markers_for_test_path(path)),
                )

    def test_evaluation_helper_units_are_unit_evaluation(self) -> None:
        markers = set(markers_for_test_path("tests/unit/test_evaluation_scenario_helpers.py"))

        self.assertEqual({"evaluation", "unit"}, markers)


if __name__ == "__main__":
    unittest.main()
