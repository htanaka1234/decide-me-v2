from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.helpers.legacy_term_policy import format_findings, json_payload_legacy_term_findings
from tests.helpers.runtime_flow import (
    assert_domain_neutral_event_types,
    complete_ok_runtime,
    event_types,
    load_bundle,
)


class FullObjectRuntimeFlowSmokeTests(unittest.TestCase):
    def test_cli_flow_reaches_valid_object_native_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"

            result = complete_ok_runtime(ai_dir, Path(tmp))

            self.assertEqual("question", result["question_turn"]["status"])
            self.assertEqual("accepted", result["accepted"]["status"])
            self.assertEqual("closed", result["closed"]["session"]["lifecycle"]["status"])
            self.assertEqual("action-plan", result["plan"]["status"])
            self.assertTrue(result["validation"]["ok"])
            self.assertEqual([], result["validation"]["issues"])

            bundle = load_bundle(ai_dir)
            self.assertTrue(bundle["project_state"]["objects"])
            self.assertTrue(bundle["project_state"]["links"])
            object_types = {obj["type"] for obj in bundle["project_state"]["objects"]}
            self.assertTrue({"decision", "proposal", "option", "action"}.issubset(object_types))
            relations = {link["relation"] for link in bundle["project_state"]["links"]}
            self.assertTrue({"addresses", "recommends", "accepts"}.issubset(relations))
            assert_domain_neutral_event_types(self, ai_dir)
            emitted = event_types(ai_dir)
            self.assertIn("object_recorded", emitted)
            self.assertIn("object_linked", emitted)
            self.assertIn("session_question_asked", emitted)
            self.assertIn("session_answer_recorded", emitted)
            self.assertIn("close_summary_generated", emitted)
            self.assertIn("plan_generated", emitted)

            self.assertEqual(
                [],
                format_findings(json_payload_legacy_term_findings(result["plan"], "generated plan")),
            )
            self.assertTrue(result["plan"]["action_plan"]["actions"])
            self.assertEqual([], result["plan"]["action_plan"]["implementation_ready_actions"])
            self.assertEqual("needs_approval", result["plan"]["action_plan"]["actions"][0]["safety_gate"]["gate_status"])
            self.assertNotIn("action" + "_slices", result["plan"]["action_plan"])


if __name__ == "__main__":
    unittest.main()
