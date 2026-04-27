from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.lifecycle import close_session, create_session
from decide_me.planner import generate_plan
from decide_me.protocol import accept_proposal, discover_decision, issue_proposal
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
            issue_proposal(
                str(ai_dir),
                session_id,
                decision_id="D-auth",
                question="Use magic links?",
                recommendation="Use magic links.",
                why="Smallest viable auth scope.",
                if_not="Passwords add reset flows.",
            )
            accept_proposal(str(ai_dir), session_id)
            close_session(str(ai_dir), session_id)

            plan = generate_plan(str(ai_dir), [session_id])

            self.assertEqual("action-plan", plan["status"])
            self.assertIn("actions", plan["action_plan"])
            self.assertIn("implementation_ready_actions", plan["action_plan"])
            self.assertNotIn("action_slices", plan["action_plan"])
            self.assertEqual(["D-auth"], [item["decision_id"] for item in plan["action_plan"]["actions"]])
            self.assertEqual([], validate_runtime(ai_dir))

            rebuilt = rebuild_and_persist(ai_dir)
            self.assertEqual(
                ["D-auth"],
                rebuilt["sessions"][session_id]["close_summary"]["object_ids"]["accepted_decisions"],
            )


if __name__ == "__main__":
    unittest.main()
