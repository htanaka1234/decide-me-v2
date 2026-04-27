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

    def test_session_scoped_selection_does_not_fallback_on_empty_related_objects(self) -> None:
        project_state = default_project_state()
        project_state["objects"] = [_decision("D-001", priority="P0", frontier="now", title="Now blocker")]

        selected = select_next_decision(project_state, related_object_ids=[], scope="session")

        self.assertIsNone(selected)

    def test_proposal_is_stale_on_project_head_change(self) -> None:
        project_state = default_project_state()
        project_state["state"]["project_head"] = "H-3"
        _add_proposal(project_state, decision_status="proposed")
        session_state = default_session_state("S-001", "2026-04-23T12:00:00Z", "demo")
        session_state["session"]["related_object_ids"] = ["D-001", "P-001", "O-option-001"]
        session_state["working_state"]["active_question_id"] = "Q-001"
        session_state["working_state"]["active_proposal_id"] = "P-001"
        session_state["working_state"]["last_seen_project_head"] = "H-2"

        stale, reason = proposal_is_stale(project_state, session_state)
        self.assertTrue(stale)
        self.assertEqual("project-head-changed", reason)

    def test_proposal_is_stale_on_decision_invalidation(self) -> None:
        project_state = default_project_state()
        _add_proposal(project_state, decision_status="invalidated")
        project_state["state"]["project_head"] = "H-2"
        session_state = default_session_state("S-001", "2026-04-23T12:00:00Z", "demo")
        session_state["session"]["related_object_ids"] = ["D-001", "P-001", "O-option-001"]
        session_state["working_state"]["active_question_id"] = "Q-001"
        session_state["working_state"]["active_proposal_id"] = "P-001"
        session_state["working_state"]["last_seen_project_head"] = "H-2"

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


def _add_proposal(project_state: dict, *, decision_status: str) -> None:
    project_state["objects"] = [
        _decision("D-001", priority="P0", frontier="now", status=decision_status),
        {
            "id": "O-option-001",
            "type": "option",
            "title": "Use option A.",
            "body": None,
            "status": "active",
            "created_at": "2026-04-23T12:00:00Z",
            "updated_at": None,
            "source_event_ids": ["E-001"],
            "metadata": {},
        },
        {
            "id": "P-001",
            "type": "proposal",
            "title": "Use option A.",
            "body": "Reason.",
            "status": "active",
            "created_at": "2026-04-23T12:00:00Z",
            "updated_at": None,
            "source_event_ids": ["E-001"],
            "metadata": {
                "origin_session_id": "S-001",
                "question_id": "Q-001",
                "question": "Question?",
                "why": "Reason.",
                "if_not": "Cost increases.",
            },
        },
    ]
    project_state["links"] = [
        {
            "id": "L-P-001-addresses-D-001",
            "source_object_id": "P-001",
            "relation": "addresses",
            "target_object_id": "D-001",
            "rationale": "Question?",
            "created_at": "2026-04-23T12:00:00Z",
            "source_event_ids": ["E-001"],
        },
        {
            "id": "L-P-001-recommends-O-option-001",
            "source_object_id": "P-001",
            "relation": "recommends",
            "target_object_id": "O-option-001",
            "rationale": "Reason.",
            "created_at": "2026-04-23T12:00:00Z",
            "source_event_ids": ["E-001"],
        },
    ]


if __name__ == "__main__":
    unittest.main()
