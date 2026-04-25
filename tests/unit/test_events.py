from __future__ import annotations

import unittest
from copy import deepcopy

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

    def test_proposal_issued_requires_non_empty_text_fields(self) -> None:
        payload = {
            "proposal": {
                "proposal_id": "P-001",
                "origin_session_id": "S-001",
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
        }

        for field in ("question", "recommendation", "why", "if_not"):
            with self.subTest(field=field):
                candidate = deepcopy(payload)
                candidate["proposal"][field] = ""
                with self.assertRaisesRegex(EventValidationError, field):
                    build_event(
                        sequence=1,
                        session_id="S-001",
                        event_type="proposal_issued",
                        project_version_after=4,
                        payload=candidate,
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

    def test_reason_events_require_non_empty_reason(self) -> None:
        with self.assertRaisesRegex(EventValidationError, "decision_deferred.payload.reason"):
            build_event(
                sequence=1,
                session_id="S-001",
                event_type="decision_deferred",
                project_version_after=4,
                payload={"decision_id": "D-001", "reason": ""},
                timestamp="2026-04-23T12:00:00Z",
            )

        with self.assertRaisesRegex(EventValidationError, "proposal_rejected.payload.reason"):
            build_event(
                sequence=1,
                session_id="S-001",
                event_type="proposal_rejected",
                project_version_after=4,
                payload={
                    "proposal_id": "P-001",
                    "origin_session_id": "S-001",
                    "target_type": "decision",
                    "target_id": "D-001",
                    "reason": "",
                },
                timestamp="2026-04-23T12:00:00Z",
            )

        with self.assertRaisesRegex(EventValidationError, "decision_invalidated.payload.reason"):
            build_event(
                sequence=1,
                session_id="S-001",
                event_type="decision_invalidated",
                project_version_after=4,
                payload={
                    "decision_id": "D-001",
                    "invalidated_by_decision_id": "D-002",
                    "reason": "",
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

    def test_session_closed_requires_closed_at(self) -> None:
        with self.assertRaisesRegex(EventValidationError, "closed_at"):
            build_event(
                sequence=1,
                session_id="S-001",
                event_type="session_closed",
                project_version_after=1,
                payload={"closed_at": None},
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

    def test_event_session_id_must_not_be_empty(self) -> None:
        with self.assertRaisesRegex(EventValidationError, "event.session_id"):
            build_event(
                sequence=1,
                session_id="",
                event_type="project_initialized",
                project_version_after=1,
                payload={
                    "project": {
                        "name": "Demo",
                        "objective": "Test",
                        "current_milestone": "MVP",
                        "stop_rule": "Resolve blockers",
                    }
                },
                timestamp="2026-04-23T12:00:00Z",
            )

    def test_session_created_requires_non_empty_id_and_timestamps(self) -> None:
        with self.assertRaisesRegex(EventValidationError, "session.id"):
            build_event(
                sequence=1,
                session_id="S-001",
                event_type="session_created",
                project_version_after=1,
                payload={
                    "session": {
                        "id": "",
                        "started_at": "2026-04-23T12:00:00Z",
                        "last_seen_at": "2026-04-23T12:00:00Z",
                        "bound_context_hint": "demo",
                    }
                },
                timestamp="2026-04-23T12:00:00Z",
            )
        with self.assertRaisesRegex(EventValidationError, "started_at"):
            build_event(
                sequence=1,
                session_id="S-001",
                event_type="session_created",
                project_version_after=1,
                payload={
                    "session": {
                        "id": "S-001",
                        "started_at": "",
                        "last_seen_at": "2026-04-23T12:00:00Z",
                        "bound_context_hint": "demo",
                    }
                },
                timestamp="2026-04-23T12:00:00Z",
            )

    def test_decision_discovered_requires_non_empty_id_and_title(self) -> None:
        with self.assertRaisesRegex(EventValidationError, "decision.id"):
            build_event(
                sequence=1,
                session_id="S-001",
                event_type="decision_discovered",
                project_version_after=1,
                payload={"decision": {"id": "", "title": "Decision"}},
                timestamp="2026-04-23T12:00:00Z",
            )
        with self.assertRaisesRegex(EventValidationError, "decision.title"):
            build_event(
                sequence=1,
                session_id="S-001",
                event_type="decision_discovered",
                project_version_after=1,
                payload={"decision": {"id": "D-001", "title": ""}},
                timestamp="2026-04-23T12:00:00Z",
            )


if __name__ == "__main__":
    unittest.main()
