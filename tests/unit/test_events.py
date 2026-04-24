from __future__ import annotations

import unittest

from decide_me.events import EventValidationError, build_event, validate_event


class EventTests(unittest.TestCase):
    def test_validate_accepts_decision_invalidated_event(self) -> None:
        event = build_event(
            sequence=1,
            session_id="S-001",
            event_type="decision_invalidated",
            project_version_after=4,
            payload={
                "decision_id": "D-001",
                "invalidated_by_decision_id": "D-002",
                "reason": "Superseded by the later decision.",
            },
            timestamp="2026-04-23T12:00:00Z",
        )

        validate_event(event)

    def test_proposal_issued_requires_origin_session_id(self) -> None:
        with self.assertRaisesRegex(EventValidationError, "origin_session_id"):
            build_event(
                sequence=1,
                session_id="S-001",
                event_type="proposal_issued",
                project_version_after=4,
                payload={
                    "proposal": {
                        "proposal_id": "P-001",
                        "target_type": "decision",
                        "target_id": "D-001",
                        "recommendation_version": 1,
                        "based_on_project_version": 3,
                        "question_id": "Q-001",
                        "question": "Question?",
                        "recommendation": "Use it.",
                        "why": "Reason.",
                        "if_not": "Alternative.",
                        "is_active": True,
                        "activated_at": "2026-04-23T12:00:00Z",
                        "inactive_reason": None,
                    }
                },
                timestamp="2026-04-23T12:00:00Z",
            )

    def test_proposal_acceptance_origin_must_match_event_session(self) -> None:
        with self.assertRaisesRegex(EventValidationError, "must match"):
            build_event(
                sequence=1,
                session_id="S-002",
                event_type="proposal_accepted",
                project_version_after=4,
                payload={
                    "proposal_id": "P-001",
                    "origin_session_id": "S-001",
                    "target_type": "decision",
                    "target_id": "D-001",
                    "accepted_answer": {
                        "summary": "Use it.",
                        "accepted_at": "2026-04-23T12:00:00Z",
                        "accepted_via": "explicit",
                        "proposal_id": "P-001",
                    },
                },
                timestamp="2026-04-23T12:00:00Z",
            )

    def test_decision_resolved_by_evidence_requires_list_refs(self) -> None:
        with self.assertRaisesRegex(EventValidationError, "evidence_refs must be a list"):
            build_event(
                sequence=1,
                session_id="S-001",
                event_type="decision_resolved_by_evidence",
                project_version_after=4,
                payload={
                    "decision_id": "D-001",
                    "source": "codebase",
                    "summary": "Found it.",
                    "evidence_refs": "app/auth.py",
                },
                timestamp="2026-04-23T12:00:00Z",
            )

    def test_decision_discovered_rejects_terminal_status(self) -> None:
        with self.assertRaisesRegex(EventValidationError, "status"):
            build_event(
                sequence=1,
                session_id="S-001",
                event_type="decision_discovered",
                project_version_after=4,
                payload={"decision": {"id": "D-001", "title": "Decision", "status": "accepted"}},
                timestamp="2026-04-23T12:00:00Z",
            )


if __name__ == "__main__":
    unittest.main()
