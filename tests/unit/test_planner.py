from __future__ import annotations

import unittest

from decide_me.planner import assemble_action_plan, detect_conflicts
from tests.helpers.typed_metadata import evidence_metadata, metadata_for_object_type


class PlannerTests(unittest.TestCase):
    def test_detects_accepted_proposal_conflict_from_object_links(self) -> None:
        project_state = _project_state()
        session_a = _session("S-001", ["L-D-001-accepts-P-001", "L-P-001-recommends-O-001"])
        session_b = _session("S-002", ["L-D-001-accepts-P-002", "L-P-002-recommends-O-002"])

        conflicts = detect_conflicts([session_a, session_b], project_state)

        self.assertEqual(1, len(conflicts))
        self.assertEqual("decision-accepted-proposal-mismatch", conflicts[0]["kind"])
        self.assertEqual("accepted_proposal", conflicts[0]["scope"]["kind"])
        self.assertEqual(["P-001", "P-002"], conflicts[0]["scope"]["proposal_ids"])

    def test_assembles_actions_without_legacy_embedded_actions(self) -> None:
        project_state = _project_state()
        session = _session(
            "S-001",
            [
                "L-D-001-accepts-P-001",
                "L-P-001-recommends-O-001",
                "L-E-001-supports-D-001",
                "L-O-action-addresses-D-001",
            ],
            action_ids=["O-action"],
            evidence_ids=["E-001"],
        )

        action_plan = assemble_action_plan([session], project_state)

        self.assertEqual(
            {
                "readiness",
                "goals",
                "workstreams",
                "actions",
                "implementation_ready_actions",
                "blockers",
                "risks",
                "evidence",
                "source_object_ids",
                "source_link_ids",
            },
            set(action_plan),
        )
        self.assertNotIn("action" + "_slices", action_plan)
        self.assertNotIn("evidence" + "_refs", action_plan)
        self.assertEqual(["O-action"], [item["id"] for item in action_plan["actions"]])
        self.assertEqual(["E-001"], [item["id"] for item in action_plan["evidence"]])
        self.assertEqual("docs/auth.md", action_plan["evidence"][0]["ref"])
        self.assertIn("D-001", action_plan["source_object_ids"])
        self.assertIn("O-action", action_plan["source_object_ids"])
        self.assertIn("L-O-action-addresses-D-001", action_plan["source_link_ids"])


def _session(
    session_id: str,
    link_ids: list[str],
    *,
    action_ids: list[str] | None = None,
    evidence_ids: list[str] | None = None,
) -> dict:
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
                "blockers": [],
                "risks": [],
                "actions": action_ids or [],
                "evidence": evidence_ids or [],
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
                "E-001",
                "evidence",
                "Auth docs",
                body="Magic links fit the current architecture.",
                metadata=evidence_metadata(source_ref="docs/auth.md", summary="Magic links fit the current architecture."),
            ),
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
            _link("L-E-001-supports-D-001", "E-001", "supports", "D-001"),
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
        "metadata": metadata if metadata is not None else metadata_for_object_type(object_type),
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
