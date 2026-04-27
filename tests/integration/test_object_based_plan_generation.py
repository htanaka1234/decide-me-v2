from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.lifecycle import close_session, create_session
from decide_me.planner import generate_plan
from decide_me.protocol import discover_decision, resolve_by_evidence
from decide_me.store import bootstrap_runtime, rebuild_and_persist, validate_runtime


class ObjectBasedPlanGenerationIntegrationTests(unittest.TestCase):
    def test_generate_plan_uses_object_ids_and_links(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Generate an object-native plan.",
                current_milestone="Phase 5-5",
            )
            session_id = create_session(str(ai_dir), context="Auth")["session"]["id"]
            discover_decision(
                str(ai_dir),
                session_id,
                {
                    "id": "D-auth",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "resolvable_by": "codebase",
                    "question": "How should users sign in?",
                },
            )
            resolve_by_evidence(
                str(ai_dir),
                session_id,
                decision_id="D-auth",
                source="docs",
                summary="Magic links are already supported by the current architecture.",
                evidence=["docs/auth.md"],
            )
            close_session(str(ai_dir), session_id)

            plan = generate_plan(str(ai_dir), [session_id])

            self.assertEqual("action-plan", plan["status"])
            self.assertEqual(
                {
                    "readiness",
                    "goals",
                    "workstreams",
                    "actions",
                    "implementation_ready_actions",
                    "blockers",
                    "risks",
                    "evidence",
                    "source_object_ids",
                    "source_link_ids",
                },
                set(plan["action_plan"]),
            )
            self.assertNotIn("action" + "_slices", plan["action_plan"])
            self.assertNotIn("evidence" + "_refs", plan["action_plan"])
            self.assertEqual(["D-auth"], [item["decision_id"] for item in plan["action_plan"]["actions"]])
            self.assertEqual(["docs/auth.md"], [item["ref"] for item in plan["action_plan"]["evidence"]])
            self.assertIn("D-auth", plan["action_plan"]["source_object_ids"])
            self.assertTrue(
                any(link_id.endswith("-supports-D-auth") for link_id in plan["action_plan"]["source_link_ids"])
            )
            self.assertEqual([], validate_runtime(ai_dir))

            rebuilt = rebuild_and_persist(ai_dir)
            self.assertEqual(
                ["D-auth"],
                rebuilt["sessions"][session_id]["close_summary"]["object_ids"]["decisions"],
            )


if __name__ == "__main__":
    unittest.main()
