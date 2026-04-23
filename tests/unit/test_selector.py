from __future__ import annotations

import unittest

from decide_me.projections import default_project_state, default_session_state
from decide_me.selector import proposal_is_stale, select_next_decision


class SelectorTests(unittest.TestCase):
    def test_select_next_decision_prioritizes_p0_now(self) -> None:
        project_state = default_project_state()
        project_state["decisions"] = [
            {
                "id": "D-200",
                "title": "Later question",
                "kind": "choice",
                "domain": "technical",
                "priority": "P1",
                "frontier": "later",
                "status": "unresolved",
                "resolvable_by": "human",
                "reversibility": "reversible",
                "depends_on": [],
                "blocked_by": [],
                "question": None,
                "context": None,
                "options": [],
                "recommendation": {},
                "accepted_answer": {},
                "resolved_by_evidence": {},
                "evidence_refs": [],
                "revisit_triggers": [],
                "notes": [],
                "bundle_id": None,
            },
            {
                "id": "D-001",
                "title": "Now blocker",
                "kind": "choice",
                "domain": "technical",
                "priority": "P0",
                "frontier": "now",
                "status": "unresolved",
                "resolvable_by": "human",
                "reversibility": "reversible",
                "depends_on": [],
                "blocked_by": [],
                "question": None,
                "context": None,
                "options": [],
                "recommendation": {},
                "accepted_answer": {},
                "resolved_by_evidence": {},
                "evidence_refs": [],
                "revisit_triggers": [],
                "notes": [],
                "bundle_id": None,
            },
        ]

        selected = select_next_decision(project_state)
        self.assertIsNotNone(selected)
        self.assertEqual("D-001", selected["id"])

    def test_proposal_is_stale_on_project_version_change(self) -> None:
        project_state = default_project_state()
        project_state["state"]["project_version"] = 3
        session_state = default_session_state("S-001", "2026-04-23T12:00:00Z", "demo")
        session_state["working_state"]["active_proposal"] = {
            "proposal_id": "P-001",
            "target_type": "decision",
            "target_id": "D-001",
            "recommendation_version": 1,
            "based_on_project_version": 2,
            "is_active": True,
            "activated_at": "2026-04-23T12:00:00Z",
            "inactive_reason": None,
            "question_id": "Q-001",
            "question": "Question?",
            "recommendation": "Use option A.",
            "why": "Reason.",
            "if_not": "Cost increases.",
        }

        stale, reason = proposal_is_stale(project_state, session_state)
        self.assertTrue(stale)
        self.assertEqual("project-version-changed", reason)


if __name__ == "__main__":
    unittest.main()
