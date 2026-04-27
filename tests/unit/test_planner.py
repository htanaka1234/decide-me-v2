from __future__ import annotations

import unittest

from decide_me.planner import assemble_action_plan, detect_conflicts


class PlannerTests(unittest.TestCase):
    def test_detects_accepted_answer_conflict_from_object_links(self) -> None:
        project_state = _project_state()
        session_a = _session("S-001", ["L-D-001-accepts-P-001", "L-P-001-recommends-O-001"])
        session_b = _session("S-002", ["L-D-001-accepts-P-002", "L-P-002-recommends-O-002"])

        conflicts = detect_conflicts([session_a, session_b], project_state)

        self.assertEqual(1, len(conflicts))
        self.assertEqual("accepted-answer-mismatch", conflicts[0]["kind"])

    def test_assembles_actions_without_action_slices(self) -> None:
        project_state = _project_state()
        session = _session(
            "S-001",
            ["L-D-001-accepts-P-001", "L-P-001-recommends-O-001", "L-O-action-addresses-D-001"],
            action_ids=["O-action"],
        )

        action_plan = assemble_action_plan([session], project_state)

        self.assertIn("actions", action_plan)
        self.assertIn("implementation_ready_actions", action_plan)
        self.assertNotIn("action_slices", action_plan)
        self.assertEqual(["O-action"], [item["id"] for item in action_plan["actions"]])


def _session(session_id: str, link_ids: list[str], *, action_ids: list[str] | None = None) -> dict:
    return {
        "session": {"id": session_id},
        "close_summary": {
            "work_item": {
                "title": "Auth",
                "statement": "Choose auth.",
                "objective_object_id": "O-project-objective",
            },
            "readiness": "ready",
            "object_ids": {
                "decisions": ["D-001"],
                "accepted_decisions": ["D-001"],
                "deferred_decisions": [],
                "blockers": [],
                "risks": [],
                "actions": action_ids or [],
                "evidence": [],
                "verifications": [],
                "revisit_triggers": [],
            },
            "link_ids": link_ids,
            "generated_at": "2026-04-23T12:00:00Z",
        },
    }


def _project_state() -> dict:
    return {
        "objects": [
            _object("O-project-objective", "objective", "MVP"),
            _object("D-001", "decision", "Auth mode", status="accepted", metadata={"domain": "technical"}),
            _object("P-001", "proposal", "Magic link", status="accepted"),
            _object("O-001", "option", "Use magic links."),
            _object("P-002", "proposal", "Password", status="accepted"),
            _object("O-002", "option", "Use passwords."),
            _object(
                "O-action",
                "action",
                "Auth mode",
                body="Use magic links.",
                metadata={
                    "decision_id": "D-001",
                    "responsibility": "technical",
                    "priority": "P0",
                    "implementation_ready": True,
                },
            ),
        ],
        "links": [
            _link("L-D-001-accepts-P-001", "D-001", "accepts", "P-001"),
            _link("L-P-001-recommends-O-001", "P-001", "recommends", "O-001"),
            _link("L-D-001-accepts-P-002", "D-001", "accepts", "P-002"),
            _link("L-P-002-recommends-O-002", "P-002", "recommends", "O-002"),
            _link("L-O-action-addresses-D-001", "O-action", "addresses", "D-001"),
        ],
    }


def _object(
    object_id: str,
    object_type: str,
    title: str,
    *,
    body: str | None = None,
    status: str = "active",
    metadata: dict | None = None,
) -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": title,
        "body": body,
        "status": status,
        "created_at": "2026-04-23T12:00:00Z",
        "updated_at": None,
        "source_event_ids": ["E-001"],
        "metadata": metadata or {},
    }


def _link(link_id: str, source: str, relation: str, target: str) -> dict:
    return {
        "id": link_id,
        "source_object_id": source,
        "relation": relation,
        "target_object_id": target,
        "rationale": None,
        "created_at": "2026-04-23T12:00:00Z",
        "source_event_ids": ["E-001"],
    }


if __name__ == "__main__":
    unittest.main()
