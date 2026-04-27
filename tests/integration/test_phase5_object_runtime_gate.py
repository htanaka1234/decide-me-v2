from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.helpers.legacy_term_policy import (
    LEGACY_PLAN_TERMS,
    LEGACY_PROJECT_STATE_TERMS,
    format_findings,
    json_payload_legacy_term_findings,
)
from tests.helpers.runtime_flow import complete_ok_runtime, events


class Phase5ObjectRuntimeGateTests(unittest.TestCase):
    def test_close_summary_and_plan_use_only_object_native_contracts(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            result = complete_ok_runtime(ai_dir, Path(tmp))

            close_summary = result["closed"]["close_summary"]
            self.assertEqual(
                {"work_item", "readiness", "object_ids", "link_ids", "generated_at"},
                set(close_summary),
            )
            self.assertTrue(close_summary["object_ids"]["decisions"])
            self.assertTrue(close_summary["object_ids"]["actions"])
            self.assertTrue(close_summary["link_ids"])
            self.assertEqual(
                [],
                format_findings(json_payload_legacy_term_findings(close_summary, "close summary")),
            )

            action_plan = result["plan"]["action_plan"]
            self.assertIn("actions", action_plan)
            self.assertIn("implementation_ready_actions", action_plan)
            for term in LEGACY_PLAN_TERMS:
                self.assertNotIn(term, action_plan)
            self.assertEqual(
                [],
                format_findings(json_payload_legacy_term_findings(action_plan, "action plan")),
            )

    def test_project_initialized_event_omits_stale_seed_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            complete_ok_runtime(ai_dir, Path(tmp))
            first_event = events(ai_dir)[0]
            stale_seed_key = next(term for term in LEGACY_PROJECT_STATE_TERMS if term.startswith("default"))

            self.assertEqual("project_initialized", first_event["event_type"])
            self.assertNotIn(
                stale_seed_key,
                first_event["payload"],
            )


if __name__ == "__main__":
    unittest.main()
