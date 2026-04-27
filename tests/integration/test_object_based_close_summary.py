from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.lifecycle import close_session, create_session
from decide_me.protocol import accept_proposal, discover_decision, issue_proposal
from decide_me.store import bootstrap_runtime, load_runtime, read_event_log, rebuild_and_persist, runtime_paths, validate_runtime


class ObjectBasedCloseSummaryIntegrationTests(unittest.TestCase):
    def test_close_session_records_action_object_and_addresses_link(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            session_id = _accepted_decision_runtime(ai_dir)

            closed = close_session(str(ai_dir), session_id)

            close_summary = closed["close_summary"]
            action_ids = close_summary["object_ids"]["actions"]
            self.assertEqual(1, len(action_ids))
            self.assertNotIn("candidate_action_slices", close_summary)

            bundle = load_runtime(runtime_paths(ai_dir))
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            links = {link["id"]: link for link in bundle["project_state"]["links"]}
            action_id = action_ids[0]
            link_id = f"L-{action_id}-addresses-D-auth"

            self.assertEqual("action", objects[action_id]["type"])
            self.assertIn(link_id, close_summary["link_ids"])
            self.assertEqual("addresses", links[link_id]["relation"])
            self.assertEqual("D-auth", links[link_id]["target_object_id"])

            events = read_event_log(runtime_paths(ai_dir))
            action_event_index = next(
                index
                for index, event in enumerate(events)
                if event["event_type"] == "object_recorded"
                and event["payload"]["object"]["id"] == action_id
            )
            close_summary_index = next(
                index for index, event in enumerate(events) if event["event_type"] == "close_summary_generated"
            )
            self.assertLess(action_event_index, close_summary_index)
            self.assertEqual([], validate_runtime(ai_dir))

            rebuilt = rebuild_and_persist(ai_dir)
            self.assertEqual(close_summary, rebuilt["sessions"][session_id]["close_summary"])


def _accepted_decision_runtime(ai_dir: Path) -> str:
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Plan object-native close summaries.",
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
    return session_id


if __name__ == "__main__":
    unittest.main()
