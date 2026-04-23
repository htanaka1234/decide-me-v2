from __future__ import annotations

import unittest
from copy import deepcopy

from decide_me.projections import default_decision, default_project_state, default_session_state
from decide_me.taxonomy import default_taxonomy_state
from decide_me.validate import StateValidationError, validate_projection_bundle


class ProjectionValidationTests(unittest.TestCase):
    def test_rejects_unknown_session_decision_reference(self) -> None:
        bundle = _valid_bundle()
        bundle["sessions"]["S-001"]["session"]["decision_ids"] = ["D-missing"]

        with self.assertRaisesRegex(StateValidationError, "unknown decision"):
            validate_projection_bundle(bundle)

    def test_rejects_active_proposal_not_owned_by_session(self) -> None:
        bundle = _valid_bundle()
        session = bundle["sessions"]["S-001"]
        session["working_state"]["active_proposal"] = _active_proposal(
            proposal_id="P-001",
            origin_session_id="S-other",
            decision_id="D-001",
        )

        with self.assertRaisesRegex(StateValidationError, "wrong origin_session_id"):
            validate_projection_bundle(bundle)

    def test_rejects_active_proposal_target_not_bound_to_session(self) -> None:
        bundle = _valid_bundle()
        decision = default_decision("D-002", "Unbound")
        decision["status"] = "proposed"
        decision["recommendation"]["proposal_id"] = "P-002"
        bundle["project_state"]["decisions"].append(decision)
        session = bundle["sessions"]["S-001"]
        session["summary"]["active_decision_id"] = "D-002"
        session["working_state"]["active_proposal"] = _active_proposal(
            proposal_id="P-002",
            origin_session_id="S-001",
            decision_id="D-002",
        )

        with self.assertRaisesRegex(StateValidationError, "not bound"):
            validate_projection_bundle(bundle)

    def test_rejects_unknown_taxonomy_tag_reference(self) -> None:
        bundle = _valid_bundle()
        bundle["sessions"]["S-001"]["classification"]["assigned_tags"] = ["tag:missing"]

        with self.assertRaisesRegex(StateValidationError, "unknown taxonomy"):
            validate_projection_bundle(bundle)

    def test_rejects_invalidated_decision_in_close_summary(self) -> None:
        bundle = _valid_bundle()
        replacement = default_decision("D-002", "Replacement")
        replacement["status"] = "accepted"
        bundle["project_state"]["decisions"].append(replacement)
        invalidated = bundle["project_state"]["decisions"][0]
        invalidated["status"] = "invalidated"
        invalidated["invalidated_by"] = {
            "decision_id": "D-002",
            "reason": "Superseded.",
            "invalidated_at": "2026-04-23T12:00:00Z",
        }
        session = bundle["sessions"]["S-001"]
        session["session"]["decision_ids"] = []
        session["close_summary"]["accepted_decisions"] = [{"id": "D-001"}]

        with self.assertRaisesRegex(StateValidationError, "non-visible decision"):
            validate_projection_bundle(bundle)

    def test_rejects_accepted_answer_proposal_mismatch(self) -> None:
        bundle = _valid_bundle()
        decision = bundle["project_state"]["decisions"][0]
        decision["status"] = "accepted"
        decision["recommendation"]["proposal_id"] = "P-001"
        decision["accepted_answer"]["proposal_id"] = "P-other"

        with self.assertRaisesRegex(StateValidationError, "accepted_answer.proposal_id"):
            validate_projection_bundle(bundle)


def _valid_bundle() -> dict:
    now = "2026-04-23T12:00:00Z"
    project_state = default_project_state()
    project_state["decisions"] = [default_decision("D-001", "Decision")]
    session = default_session_state("S-001", now, "demo")
    session["session"]["decision_ids"] = ["D-001"]
    return {
        "project_state": project_state,
        "taxonomy_state": default_taxonomy_state(now=now),
        "sessions": {"S-001": session},
    }


def _active_proposal(*, proposal_id: str, origin_session_id: str, decision_id: str) -> dict:
    proposal = deepcopy(default_session_state("S-template", "2026-04-23T12:00:00Z")["working_state"]["active_proposal"])
    proposal.update(
        {
            "proposal_id": proposal_id,
            "origin_session_id": origin_session_id,
            "target_type": "decision",
            "target_id": decision_id,
            "recommendation_version": 1,
            "based_on_project_version": 1,
            "is_active": True,
            "activated_at": "2026-04-23T12:00:00Z",
            "inactive_reason": None,
            "question_id": "Q-001",
            "question": "Question?",
            "recommendation": "Use it.",
            "why": "Because.",
            "if_not": "Risk.",
        }
    )
    return proposal


if __name__ == "__main__":
    unittest.main()
