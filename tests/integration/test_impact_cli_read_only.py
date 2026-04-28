from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jsonschema import Draft202012Validator

from tests.helpers.impact_runtime import (
    build_impact_runtime,
    candidate_target_ids,
    edge_ids,
    event_hash_snapshot,
    load_schema,
    object_ids,
    run_json_cli,
    runtime_state_snapshot,
)


class ImpactCliReadOnlyTests(unittest.TestCase):
    def test_impact_cli_commands_return_json_without_runtime_state_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = build_impact_runtime(Path(tmp))
            commands = [
                (
                    "show-impact",
                    (
                        "show-impact",
                        "--ai-dir",
                        str(ai_dir),
                        "--object-id",
                        "CON-001",
                        "--change-kind",
                        "changed",
                        "--max-depth",
                        "4",
                    ),
                ),
                (
                    "show-invalidation-candidates",
                    (
                        "show-invalidation-candidates",
                        "--ai-dir",
                        str(ai_dir),
                        "--object-id",
                        "CON-001",
                        "--change-kind",
                        "changed",
                        "--max-depth",
                        "4",
                    ),
                ),
                (
                    "show-decision-stack",
                    (
                        "show-decision-stack",
                        "--ai-dir",
                        str(ai_dir),
                        "--object-id",
                        "DEC-001",
                        "--upstream-depth",
                        "1",
                        "--downstream-depth",
                        "3",
                    ),
                ),
            ]

            for command_name, args in commands:
                with self.subTest(command=command_name):
                    event_before = event_hash_snapshot(ai_dir)
                    runtime_before = runtime_state_snapshot(ai_dir)

                    payload = run_json_cli(*args)

                    self.assertEqual(event_before, event_hash_snapshot(ai_dir))
                    self.assertEqual(runtime_before, runtime_state_snapshot(ai_dir))
                    if command_name == "show-impact":
                        self._assert_impact_payload(payload)
                    elif command_name == "show-invalidation-candidates":
                        self._assert_candidate_payload(payload)
                    else:
                        self._assert_bounded_graph_payload(payload)

    def _assert_impact_payload(self, payload: dict) -> None:
        schema = load_schema("schemas/impact-analysis.schema.json")
        self.assertEqual([], list(Draft202012Validator(schema).iter_errors(payload)))
        self.assertEqual("CON-001", payload["root_object_id"])
        self.assertEqual("changed", payload["change_kind"])
        self.assertEqual(
            ["DEC-001", "ACT-001", "DEC-002", "RISK-001", "VER-001"],
            object_ids(payload, "affected_objects"),
        )
        self.assertEqual(5, payload["summary"]["affected_count"])
        self.assertEqual("high", payload["summary"]["highest_severity"])

    def _assert_candidate_payload(self, payload: dict) -> None:
        schema = load_schema("schemas/invalidation-candidates.schema.json")
        self.assertEqual([], list(Draft202012Validator(schema).iter_errors(payload)))
        self.assertEqual("CON-001", payload["root_object_id"])
        self.assertEqual(
            ["DEC-001", "ACT-001", "DEC-002", "RISK-001", "VER-001"],
            candidate_target_ids(payload),
        )
        by_target = {candidate["target_object_id"]: candidate for candidate in payload["candidates"]}
        self.assertEqual("revalidate", by_target["DEC-001"]["candidate_kind"])
        self.assertTrue(by_target["DEC-001"]["requires_human_approval"])
        self.assertEqual("explicit_acceptance", by_target["DEC-001"]["approval_threshold"])
        self.assertEqual("manual", by_target["DEC-001"]["materialization_status"])
        self.assertEqual("revise", by_target["ACT-001"]["candidate_kind"])
        self.assertEqual("none", by_target["ACT-001"]["approval_threshold"])
        self.assertEqual("manual", by_target["ACT-001"]["materialization_status"])
        self.assertEqual("review", by_target["DEC-002"]["candidate_kind"])
        self.assertEqual("revalidate", by_target["RISK-001"]["candidate_kind"])
        self.assertEqual("revalidate", by_target["VER-001"]["candidate_kind"])

    def _assert_bounded_graph_payload(self, payload: dict) -> None:
        self.assertEqual({"root_object_id", "nodes", "edges"}, set(payload))
        self.assertEqual("DEC-001", payload["root_object_id"])
        self.assertTrue(
            {
                "CON-001",
                "DEC-001",
                "ACT-001",
                "VER-001",
                "RISK-001",
                "DEC-002",
            }.issubset(object_ids(payload, "nodes"))
        )
        self.assertTrue(
            {
                "L-CON-001-constrains-DEC-001",
                "L-ACT-001-addresses-DEC-001",
                "L-VER-001-verifies-ACT-001",
                "L-ACT-001-mitigates-RISK-001",
                "L-DEC-002-depends-on-DEC-001",
            }.issubset(edge_ids(payload))
        )


if __name__ == "__main__":
    unittest.main()
