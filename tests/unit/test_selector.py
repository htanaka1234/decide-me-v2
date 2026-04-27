from __future__ import annotations

import unittest

from decide_me.projections import default_project_state, default_session_state
from decide_me.selector import proposal_is_stale, select_next_decision


class SelectorTests(unittest.TestCase):
    def test_select_next_decision_prioritizes_p0_now(self) -> None:
        project_state = default_project_state()
        project_state["objects"] = [
            _decision("D-200", priority="P1", frontier="later", title="Later question"),
            _decision("D-001", priority="P0", frontier="now", title="Now blocker"),
        ]

        selected = select_next_decision(project_state)
        self.assertIsNotNone(selected)
        self.assertEqual("D-001", selected["id"])

    def test_select_next_decision_skips_invalidated_target(self) -> None:
        project_state = default_project_state()
        project_state["objects"] = [
            _decision("D-000", priority="P0", frontier="now", status="invalidated", title="Superseded blocker"),
            _decision("D-001", priority="P1", frontier="now", title="Visible blocker"),
        ]
        project_state["links"] = [
            {
                "id": "L-D-001-depends_on-D-000",
                "source_object_id": "D-001",
                "relation": "depends_on",
                "target_object_id": "D-000",
                "rationale": None,
                "created_at": "2026-04-23T12:00:00Z",
                "source_event_ids": ["E-001"],
            }
        ]

        selected = select_next_decision(project_state)
        self.assertIsNotNone(selected)
        self.assertEqual("D-001", selected["id"])

    def test_session_scoped_selection_does_not_fallback_on_empty_decision_ids(self) -> None:
        project_state = default_project_state()
        project_state["objects"] = [_decision("D-001", priority="P0", frontier="now", title="Now blocker")]

        selected = select_next_decision(project_state, decision_ids=[], scope="session")

        self.assertIsNone(selected)

    def test_proposal_is_stale_on_project_head_change(self) -> None:
        project_state = default_project_state()
        project_state["state"]["project_head"] = "H-3"
        session_state = default_session_state("S-001", "2026-04-23T12:00:00Z", "demo")
        session_state["working_state"]["active_proposal"] = {
            "proposal_id": "P-001",
            "origin_session_id": "S-001",
            "target_type": "decision",
            "target_id": "D-001",
            "recommendation_version": 1,
            "based_on_project_head": "H-2",
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
        self.assertEqual("project-head-changed", reason)

    def test_proposal_is_stale_on_decision_invalidation(self) -> None:
        project_state = default_project_state()
        project_state["objects"] = [_decision("D-001", priority="P0", frontier="now", status="invalidated")]
        project_state["state"]["project_head"] = "H-2"
        session_state = default_session_state("S-001", "2026-04-23T12:00:00Z", "demo")
        session_state["working_state"]["active_proposal"] = {
            "proposal_id": "P-001",
            "origin_session_id": "S-001",
            "target_type": "decision",
            "target_id": "D-001",
            "recommendation_version": 1,
            "based_on_project_head": "H-2",
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
        self.assertEqual("decision-invalidated", reason)


def _decision(
    decision_id: str,
    *,
    priority: str,
    frontier: str,
    status: str = "unresolved",
    title: str = "Auth mode",
) -> dict:
    return {
        "id": decision_id,
        "type": "decision",
        "title": title,
        "body": None,
        "status": status,
        "created_at": "2026-04-23T12:00:00Z",
        "updated_at": None,
        "source_event_ids": ["E-001"],
        "metadata": {
            "requirement_id": f"R-{decision_id.split('-')[-1]}",
            "kind": "choice",
            "domain": "technical",
            "priority": priority,
            "frontier": frontier,
            "resolvable_by": "human",
            "reversibility": "reversible",
        },
    }


if __name__ == "__main__":
    unittest.main()
