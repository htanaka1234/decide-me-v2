from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.interview import advance_session, handle_reply
from decide_me.lifecycle import create_session
from decide_me.protocol import discover_decision
from decide_me.store import (
    bootstrap_runtime,
    load_runtime,
    read_event_log,
    rebuild_and_persist,
    runtime_paths,
    validate_runtime,
)


class ObjectBasedOkAcceptanceTests(unittest.TestCase):
    def test_plain_ok_accepts_only_active_proposal_and_rebuild_preserves_state(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            session_id = _bootstrap_session(ai_dir)
            _discover_auth_decision(ai_dir, session_id)
            turn = advance_session(str(ai_dir), session_id, repo_root=tmp)
            proposal_id = turn["proposal_id"]

            result = handle_reply(str(ai_dir), session_id, "OK", repo_root=tmp)

            self.assertEqual("accepted", result["status"])
            self.assertEqual([], validate_runtime(ai_dir))

            bundle = load_runtime(runtime_paths(ai_dir))
            session = bundle["sessions"][session_id]
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            links = bundle["project_state"]["links"]
            legacy_binding_key = "decision" + "_ids"

            self.assertNotIn(legacy_binding_key, session["session"])
            self.assertIsNone(session["working_state"]["active_question_id"])
            self.assertIsNone(session["working_state"]["active_proposal_id"])
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

            rebuilt = rebuild_and_persist(ai_dir)
            rebuilt_session = rebuilt["sessions"][session_id]
            rebuilt_objects = {obj["id"]: obj for obj in rebuilt["project_state"]["objects"]}
            self.assertIsNone(rebuilt_session["working_state"]["active_proposal_id"])
            self.assertEqual("accepted", rebuilt_objects["D-auth"]["status"])
            self.assertEqual("accepted", rebuilt_objects[proposal_id]["status"])

    def test_rejected_proposal_cannot_be_accepted_again_by_plain_ok(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            session_id = _bootstrap_session(ai_dir)
            _discover_auth_decision(ai_dir, session_id)
            turn = advance_session(str(ai_dir), session_id, repo_root=tmp)
            proposal_id = turn["proposal_id"]

            rejected = handle_reply(str(ai_dir), session_id, f"Reject {proposal_id}: prefer SSO", repo_root=tmp)

            self.assertEqual("rejected", rejected["status"])
            with self.assertRaisesRegex(ValueError, "no active proposal"):
                handle_reply(str(ai_dir), session_id, "OK", repo_root=tmp)

            bundle = load_runtime(runtime_paths(ai_dir))
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            self.assertEqual("rejected", objects[proposal_id]["status"])
            self.assertEqual("unresolved", objects["D-auth"]["status"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_defer_active_proposal_records_answer_and_inactivates_proposal(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            session_id = _bootstrap_session(ai_dir)
            _discover_auth_decision(ai_dir, session_id)
            turn = advance_session(str(ai_dir), session_id, repo_root=tmp)
            proposal_id = turn["proposal_id"]
            reason = "Blocked pending legal signoff."

            result = handle_reply(str(ai_dir), session_id, f"Defer D-auth: {reason}", repo_root=tmp)

            self.assertEqual("deferred", result["status"])
            self.assertEqual([], validate_runtime(ai_dir))
            bundle = load_runtime(runtime_paths(ai_dir))
            session = bundle["sessions"][session_id]
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            events = read_event_log(runtime_paths(ai_dir))
            defer_answers = [
                event["payload"]["answer"]
                for event in events
                if event["event_type"] == "session_answer_recorded"
                and event["payload"]["target_object_id"] == "D-auth"
            ]

            self.assertEqual("deferred", objects["D-auth"]["status"])
            self.assertEqual("inactive", objects[proposal_id]["status"])
            self.assertIsNone(session["working_state"]["active_question_id"])
            self.assertIsNone(session["working_state"]["active_proposal_id"])
            self.assertEqual(
                [{"summary": reason, "answered_at": defer_answers[0]["answered_at"], "answered_via": "defer"}],
                defer_answers,
            )

    def test_defer_without_active_proposal_records_null_question_answer(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            session_id = _bootstrap_session(ai_dir)
            _discover_auth_decision(ai_dir, session_id)
            reason = "Blocked pending legal signoff."

            result = handle_reply(str(ai_dir), session_id, f"Defer D-auth: {reason}", repo_root=tmp)

            self.assertEqual("deferred", result["status"])
            self.assertEqual([], validate_runtime(ai_dir))
            bundle = load_runtime(runtime_paths(ai_dir))
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            events = read_event_log(runtime_paths(ai_dir))
            defer_answer_events = [
                event
                for event in events
                if event["event_type"] == "session_answer_recorded"
                and event["payload"]["target_object_id"] == "D-auth"
            ]

            self.assertEqual("deferred", objects["D-auth"]["status"])
            self.assertEqual(1, len(defer_answer_events))
            self.assertIsNone(defer_answer_events[0]["payload"]["question_id"])
            self.assertEqual("defer", defer_answer_events[0]["payload"]["answer"]["answered_via"])
            rebuilt = rebuild_and_persist(ai_dir)
            rebuilt_objects = {obj["id"]: obj for obj in rebuilt["project_state"]["objects"]}
            self.assertEqual("deferred", rebuilt_objects["D-auth"]["status"])


def _bootstrap_session(ai_dir: Path) -> str:
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Exercise object OK acceptance.",
        current_milestone="Phase 5-4",
    )
    return create_session(str(ai_dir), context="Object OK acceptance")["session"]["id"]


def _discover_auth_decision(ai_dir: Path, session_id: str) -> None:
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


if __name__ == "__main__":
    unittest.main()
