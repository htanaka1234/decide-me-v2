from __future__ import annotations

import unittest
from copy import deepcopy

from decide_me.events import EventValidationError, build_event as runtime_build_event, validate_event


def build_event(
    *,
    sequence: int = 1,
    session_id: str,
    event_type: str,
    project_version_after: int = 1,
    payload: dict,
    timestamp: str | None = None,
) -> dict:
    return runtime_build_event(
        tx_id=f"T-test-{sequence}",
        tx_index=1,
        tx_size=1,
        event_id=f"E-test-{sequence}",
        session_id=session_id,
        event_type=event_type,
        payload=payload,
        timestamp=timestamp,
        project_head=f"H-{project_version_after}",
    )


class EventTests(unittest.TestCase):
    def test_validate_rejects_legacy_project_version_after_field(self) -> None:
        event = build_event(
            sequence=1,
            session_id="SYSTEM",
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
        event["project_version_after"] = 1

        with self.assertRaisesRegex(EventValidationError, "unsupported fields: project_version_after"):
            validate_event(event)

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

    def test_validate_accepts_transaction_rejected_event(self) -> None:
        event = build_event(
            sequence=1,
            session_id="S-001",
            event_type="transaction_rejected",
            project_version_after=4,
            payload={
                "kept_tx_id": "T-keep",
                "rejected_tx_ids": ["T-reject"],
                "reason": "User selected the first transaction.",
                "resolved_at": "2026-04-23T12:00:00Z",
                "conflict_kind": "competing-active-proposals",
                "conflict_summary": "proposal_issued while proposal P-001 is still active",
            },
            timestamp="2026-04-23T12:00:00Z",
        )

        validate_event(event)

    def test_transaction_rejected_rejects_empty_and_self_references(self) -> None:
        payload = {
            "kept_tx_id": "T-keep",
            "rejected_tx_ids": [],
            "reason": "Resolve conflict.",
            "resolved_at": "2026-04-23T12:00:00Z",
            "conflict_kind": "competing-active-proposals",
            "conflict_summary": "summary",
        }

        with self.assertRaisesRegex(EventValidationError, "rejected_tx_ids"):
            build_event(
                sequence=1,
                session_id="S-001",
                event_type="transaction_rejected",
                project_version_after=4,
                payload=payload,
                timestamp="2026-04-23T12:00:00Z",
            )

        payload["rejected_tx_ids"] = ["T-keep"]
        with self.assertRaisesRegex(EventValidationError, "kept_tx_id"):
            build_event(
                sequence=1,
                session_id="S-001",
                event_type="transaction_rejected",
                project_version_after=4,
                payload=payload,
                timestamp="2026-04-23T12:00:00Z",
            )

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
                        "based_on_project_head": "H-3",
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
                "based_on_project_head": "H-3",
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

    def test_plan_generated_requires_non_empty_session_ids(self) -> None:
        with self.assertRaisesRegex(EventValidationError, "non-empty list"):
            build_event(
                sequence=1,
                session_id="SYSTEM",
                event_type="plan_generated",
                project_version_after=1,
                payload={"session_ids": "S-001", "status": "action-plan"},
                timestamp="2026-04-23T12:00:00Z",
            )

        with self.assertRaisesRegex(EventValidationError, "non-empty list"):
            build_event(
                sequence=1,
                session_id="SYSTEM",
                event_type="plan_generated",
                project_version_after=1,
                payload={"session_ids": [], "status": "action-plan"},
                timestamp="2026-04-23T12:00:00Z",
            )

        with self.assertRaisesRegex(EventValidationError, "session_ids"):
            build_event(
                sequence=1,
                session_id="SYSTEM",
                event_type="plan_generated",
                project_version_after=1,
                payload={"session_ids": [" "], "status": "action-plan"},
                timestamp="2026-04-23T12:00:00Z",
            )

    def test_plan_generated_requires_known_status(self) -> None:
        with self.assertRaisesRegex(EventValidationError, "status"):
            build_event(
                sequence=1,
                session_id="SYSTEM",
                event_type="plan_generated",
                project_version_after=1,
                payload={"session_ids": ["S-001"], "status": "empty"},
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
        with self.assertRaisesRegex(EventValidationError, "started_at"):
            build_event(
                sequence=1,
                session_id="S-001",
                event_type="session_created",
                project_version_after=1,
                payload={
                    "session": {
                        "id": "S-001",
                        "started_at": "not-time",
                        "last_seen_at": "2026-04-23T12:00:00Z",
                        "bound_context_hint": "demo",
                    }
                },
                timestamp="2026-04-23T12:00:00Z",
            )
        with self.assertRaisesRegex(EventValidationError, "last_seen_at"):
            build_event(
                sequence=1,
                session_id="S-001",
                event_type="session_created",
                project_version_after=1,
                payload={
                    "session": {
                        "id": "S-001",
                        "started_at": "2026-04-23T12:00:00Z",
                        "last_seen_at": "not-time",
                        "bound_context_hint": "demo",
                    }
                },
                timestamp="2026-04-23T12:00:00Z",
            )

    def test_event_payloads_reject_invalid_timestamps(self) -> None:
        with self.assertRaisesRegex(EventValidationError, "resumed_at"):
            build_event(
                sequence=1,
                session_id="S-001",
                event_type="session_resumed",
                project_version_after=1,
                payload={"resumed_at": "not-time"},
                timestamp="2026-04-23T12:00:00Z",
            )

        proposal_payload = {
            "proposal": {
                "proposal_id": "P-001",
                "origin_session_id": "S-001",
                "target_type": "decision",
                "target_id": "D-001",
                "recommendation_version": 1,
                "based_on_project_head": "H-1",
                "question_id": "Q-001",
                "question": "Question?",
                "recommendation": "Use it.",
                "why": "Reason.",
                "if_not": "Alternative.",
                "is_active": True,
                "activated_at": "not-time",
                "inactive_reason": None,
            }
        }
        with self.assertRaisesRegex(EventValidationError, "activated_at"):
            build_event(
                sequence=1,
                session_id="S-001",
                event_type="proposal_issued",
                project_version_after=1,
                payload=proposal_payload,
                timestamp="2026-04-23T12:00:00Z",
            )

        with self.assertRaisesRegex(EventValidationError, "accepted_at"):
            build_event(
                sequence=1,
                session_id="S-001",
                event_type="proposal_accepted",
                project_version_after=1,
                payload={
                    "proposal_id": "P-001",
                    "origin_session_id": "S-001",
                    "target_type": "decision",
                    "target_id": "D-001",
                    "accepted_answer": {
                        "summary": "Use it.",
                        "accepted_at": "not-time",
                        "accepted_via": "explicit",
                        "proposal_id": "P-001",
                    },
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
