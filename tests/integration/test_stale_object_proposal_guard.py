from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.interview import advance_session, handle_reply
from decide_me.lifecycle import create_session
from decide_me.protocol import discover_decision
from decide_me.store import bootstrap_runtime, load_runtime, runtime_paths, validate_runtime


class StaleObjectProposalGuardTests(unittest.TestCase):
    def test_plain_ok_rejects_stale_proposal_but_explicit_accept_is_allowed(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Exercise stale proposal guard.",
                current_milestone="Phase 5-4",
            )
            session_id = create_session(str(ai_dir), context="Stale guard")["session"]["id"]
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
            proposal_id = turn["proposal_id"]
            discover_decision(
                str(ai_dir),
                session_id,
                {
                    "id": "D-audit",
                    "title": "Audit export",
                    "priority": "P1",
                    "frontier": "later",
                    "domain": "data",
                    "question": "How should audit export work?",
                },
            )

            with self.assertRaisesRegex(ValueError, f"Use Accept {proposal_id}"):
                handle_reply(str(ai_dir), session_id, "OK", repo_root=tmp)

            result = handle_reply(str(ai_dir), session_id, f"Accept {proposal_id}", repo_root=tmp)

            self.assertEqual("accepted", result["status"])
            self.assertEqual([], validate_runtime(ai_dir))
            bundle = load_runtime(runtime_paths(ai_dir))
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            links = bundle["project_state"]["links"]

            self.assertEqual("accepted", objects["D-auth"]["status"])
            self.assertEqual("accepted", objects[proposal_id]["status"])
            self.assertTrue(
                any(
                    link["source_object_id"] == "D-auth"
                    and link["relation"] == "accepts"
                    and link["target_object_id"] == proposal_id
                    for link in links
                )
            )


if __name__ == "__main__":
    unittest.main()
