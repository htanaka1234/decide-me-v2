from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.helpers.impact_runtime import (
    build_impact_runtime,
    candidate_target_ids,
    edge_ids,
    object_ids,
    run_json_cli,
)


class Phase6GraphImpactGateTests(unittest.TestCase):
    def test_objective_impact_reaches_downstream_decision_stack_objects(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = build_impact_runtime(Path(tmp))

            impact = run_json_cli(
                "show-impact",
                "--ai-dir",
                str(ai_dir),
                "--object-id",
                "OBJ-001",
                "--change-kind",
                "changed",
                "--max-depth",
                "4",
            )

            self.assertEqual(
                ["DEC-001", "ACT-001", "DEC-002", "RISK-001", "VER-001"],
                object_ids(impact, "affected_objects"),
            )
            self.assertEqual(
                ["OBJ-001", "DEC-001", "ACT-001", "VER-001"],
                next(path["node_ids"] for path in impact["paths"] if path["target_object_id"] == "VER-001"),
            )
            self.assertEqual(
                ["OBJ-001", "DEC-001", "ACT-001", "RISK-001"],
                next(path["node_ids"] for path in impact["paths"] if path["target_object_id"] == "RISK-001"),
            )

    def test_constraint_impact_reaches_downstream_decision_stack_objects(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = build_impact_runtime(Path(tmp))

            impact = run_json_cli(
                "show-impact",
                "--ai-dir",
                str(ai_dir),
                "--object-id",
                "CON-001",
                "--change-kind",
                "changed",
                "--max-depth",
                "4",
            )
            candidates = run_json_cli(
                "show-invalidation-candidates",
                "--ai-dir",
                str(ai_dir),
                "--object-id",
                "CON-001",
                "--change-kind",
                "changed",
                "--max-depth",
                "4",
            )

            self.assertEqual(
                ["DEC-001", "ACT-001", "DEC-002", "RISK-001", "VER-001"],
                object_ids(impact, "affected_objects"),
            )
            self.assertEqual(
                ["DEC-001", "ACT-001", "DEC-002", "RISK-001", "VER-001"],
                candidate_target_ids(candidates),
            )
            self.assertEqual(
                ["CON-001", "DEC-001", "ACT-001", "VER-001"],
                next(path["node_ids"] for path in impact["paths"] if path["target_object_id"] == "VER-001"),
            )
            self.assertEqual(
                ["CON-001", "DEC-001", "ACT-001", "RISK-001"],
                next(path["node_ids"] for path in impact["paths"] if path["target_object_id"] == "RISK-001"),
            )

    def test_decision_stack_cli_preserves_upstream_and_downstream_influence_paths(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = build_impact_runtime(Path(tmp))

            stack = run_json_cli(
                "show-decision-stack",
                "--ai-dir",
                str(ai_dir),
                "--object-id",
                "DEC-001",
                "--upstream-depth",
                "1",
                "--downstream-depth",
                "3",
            )

            self.assertEqual({"root_object_id", "nodes", "edges"}, set(stack))
            self.assertEqual("DEC-001", stack["root_object_id"])
            self.assertTrue(
                {
                    "OBJ-001",
                    "CON-001",
                    "ACT-001",
                    "VER-001",
                    "DEC-002",
                    "RISK-001",
                }.issubset(object_ids(stack, "nodes"))
            )
            self.assertTrue(
                {
                    "L-OBJ-001-constrains-DEC-001",
                    "L-CON-001-constrains-DEC-001",
                    "L-ACT-001-addresses-DEC-001",
                    "L-VER-001-verifies-ACT-001",
                    "L-DEC-002-depends-on-DEC-001",
                    "L-ACT-001-mitigates-RISK-001",
                }.issubset(edge_ids(stack))
            )


if __name__ == "__main__":
    unittest.main()
