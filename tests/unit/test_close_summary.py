from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.lifecycle import close_session, create_session
from decide_me.protocol import accept_proposal, discover_decision, issue_proposal
from decide_me.store import bootstrap_runtime, load_runtime, runtime_paths


class CloseSummaryTests(unittest.TestCase):
    def test_close_summary_is_object_native(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Plan the milestone.",
                current_milestone="MVP",
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

            closed = close_session(str(ai_dir), session_id)
            close_summary = closed["close_summary"]

            for legacy_key in (
                "accepted_decisions",
                "deferred_decisions",
                "unresolved_blockers",
                "unresolved_risks",
                "candidate_workstreams",
                "candidate_action_slices",
                "evidence_refs",
            ):
                self.assertNotIn(legacy_key, close_summary)
            self.assertEqual(["D-auth"], close_summary["object_ids"]["accepted_decisions"])
            self.assertEqual(1, len(close_summary["object_ids"]["actions"]))
            self.assertTrue(close_summary["link_ids"])

            bundle = load_runtime(runtime_paths(ai_dir))
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            action_id = close_summary["object_ids"]["actions"][0]
            self.assertEqual("action", objects[action_id]["type"])


if __name__ == "__main__":
    unittest.main()
