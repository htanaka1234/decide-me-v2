from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.interview import advance_session
from decide_me.lifecycle import create_session
from decide_me.protocol import discover_decision
from decide_me.store import bootstrap_runtime, load_runtime, runtime_paths


class InterviewTests(unittest.TestCase):
    def test_advance_session_issues_object_link_proposal_and_active_ids(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Exercise object-based interview flow.",
                current_milestone="Phase 5-4",
            )
            session_id = create_session(str(ai_dir), context="Auth thread")["session"]["id"]
            discover_decision(
                str(ai_dir),
                session_id,
                {
                    "id": "D-auth",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should users sign in?",
                },
            )

            turn = advance_session(str(ai_dir), session_id, repo_root=tmp)

            self.assertEqual("question", turn["status"])
            self.assertEqual("D-auth", turn["decision_id"])
            self.assertTrue(turn["proposal_id"].startswith("P-"))
            for label in ("Decision:", "Proposal:", "Question:", "Recommendation:", "Why:", "If not:"):
                self.assertIn(label, turn["message"])

            bundle = load_runtime(runtime_paths(ai_dir))
            session = bundle["sessions"][session_id]
            project_state = bundle["project_state"]
            links = project_state["links"]
            legacy_binding_key = "decision" + "_ids"

            self.assertNotIn(legacy_binding_key, session["session"])
            self.assertIn("D-auth", session["session"]["related_object_ids"])
            self.assertEqual(turn["proposal_id"], session["working_state"]["active_proposal_id"])
            self.assertTrue(session["working_state"]["active_question_id"].startswith("Q-"))
            self.assertTrue(
                any(
                    link["source_object_id"] == turn["proposal_id"]
                    and link["relation"] == "addresses"
                    and link["target_object_id"] == "D-auth"
                    for link in links
                )
            )
            self.assertTrue(
                any(
                    link["source_object_id"] == turn["proposal_id"]
                    and link["relation"] == "recommends"
                    for link in links
                )
            )


if __name__ == "__main__":
    unittest.main()
