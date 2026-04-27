from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.interview import advance_session
from decide_me.lifecycle import create_session
from decide_me.object_views import proposal_view
from decide_me.projections import default_project_state
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

    def test_proposal_view_rejects_missing_decision_address(self) -> None:
        project_state = _proposal_project_state(address_targets=[])

        with self.assertRaisesRegex(ValueError, "exactly one addresses link"):
            proposal_view(project_state, "P-001")

    def test_proposal_view_rejects_multiple_decision_addresses(self) -> None:
        project_state = _proposal_project_state(address_targets=["D-001", "D-002"])

        with self.assertRaisesRegex(ValueError, "exactly one addresses link"):
            proposal_view(project_state, "P-001")

    def test_proposal_view_rejects_non_decision_address(self) -> None:
        project_state = _proposal_project_state(address_targets=["O-option-001"])

        with self.assertRaisesRegex(ValueError, "non-decision"):
            proposal_view(project_state, "P-001")


def _proposal_project_state(*, address_targets: list[str]) -> dict:
    project_state = default_project_state()
    project_state["objects"] = [
        _object("D-001", "decision", status="proposed"),
        _object("D-002", "decision", status="proposed"),
        _object("O-option-001", "option", title="Use option.", status="active"),
        _object("P-001", "proposal", title="Use option.", status="active"),
    ]
    project_state["links"] = [
        {
            "id": f"L-P-001-addresses-{target}",
            "source_object_id": "P-001",
            "relation": "addresses",
            "target_object_id": target,
            "rationale": "Question?",
            "created_at": "2026-04-23T12:00:00Z",
            "source_event_ids": ["E-001"],
        }
        for target in address_targets
    ]
    project_state["links"].append(
        {
            "id": "L-P-001-recommends-O-option-001",
            "source_object_id": "P-001",
            "relation": "recommends",
            "target_object_id": "O-option-001",
            "rationale": "Reason.",
            "created_at": "2026-04-23T12:00:00Z",
            "source_event_ids": ["E-001"],
        }
    )
    return project_state


def _object(object_id: str, object_type: str, *, title: str | None = None, status: str) -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": title or object_id,
        "body": None,
        "status": status,
        "created_at": "2026-04-23T12:00:00Z",
        "updated_at": None,
        "source_event_ids": ["E-001"],
        "metadata": {},
    }


if __name__ == "__main__":
    unittest.main()
