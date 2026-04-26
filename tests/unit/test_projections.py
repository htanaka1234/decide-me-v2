from __future__ import annotations

from copy import deepcopy
import unittest

from decide_me.events import build_event as runtime_build_event
from decide_me.projections import project_heads_by_event_id, rebuild_projections


def build_event(
    *,
    sequence: int,
    session_id: str,
    event_type: str,
    project_version_after: int,
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


class ProjectionTests(unittest.TestCase):
    def test_project_head_changes_when_payload_changes_with_same_event_id(self) -> None:
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
        changed = deepcopy(event)
        changed["payload"]["project"]["objective"] = "Changed"

        self.assertNotEqual(
            project_heads_by_event_id([event])[event["event_id"]],
            project_heads_by_event_id([changed])[changed["event_id"]],
        )

    def test_project_head_ignores_proposal_based_on_project_head_value(self) -> None:
        event = build_event(
            sequence=1,
            session_id="S-001",
            event_type="proposal_issued",
            project_version_after=1,
            payload={
                "proposal": {
                    "proposal_id": "P-001",
                    "origin_session_id": "S-001",
                    "target_type": "decision",
                    "target_id": "D-001",
                    "recommendation_version": 1,
                    "based_on_project_head": "H-before",
                    "question_id": "Q-001",
                    "question": "Use magic links?",
                    "recommendation": "Use magic links.",
                    "why": "Smaller MVP surface area.",
                    "if_not": "Passwords expand auth scope.",
                    "is_active": True,
                    "activated_at": "2026-04-23T12:03:00Z",
                    "inactive_reason": None,
                }
            },
            timestamp="2026-04-23T12:03:00Z",
        )
        changed = deepcopy(event)
        changed["payload"]["proposal"]["based_on_project_head"] = "H-after"

        self.assertEqual(
            project_heads_by_event_id([event])[event["event_id"]],
            project_heads_by_event_id([changed])[changed["event_id"]],
        )

    def test_rebuild_is_idempotent(self) -> None:
        events = [
            build_event(
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
            ),
            build_event(
                sequence=2,
                session_id="S-001",
                event_type="session_created",
                project_version_after=2,
                payload={
                    "session": {
                        "id": "S-001",
                        "started_at": "2026-04-23T12:01:00Z",
                        "last_seen_at": "2026-04-23T12:01:00Z",
                        "bound_context_hint": "demo",
                    }
                },
                timestamp="2026-04-23T12:01:00Z",
            ),
            build_event(
                sequence=3,
                session_id="S-001",
                event_type="decision_discovered",
                project_version_after=3,
                payload={"decision": {"id": "D-001", "title": "Auth mode"}},
                timestamp="2026-04-23T12:02:00Z",
            ),
        ]

        first = rebuild_projections(events)
        second = rebuild_projections(events)
        self.assertEqual(first, second)

    def test_proposal_accepted_without_reason_uses_answer_summary_for_session_summary(self) -> None:
        events = [
            build_event(
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
            ),
            build_event(
                sequence=2,
                session_id="S-001",
                event_type="session_created",
                project_version_after=2,
                payload={
                    "session": {
                        "id": "S-001",
                        "started_at": "2026-04-23T12:01:00Z",
                        "last_seen_at": "2026-04-23T12:01:00Z",
                        "bound_context_hint": "demo",
                    }
                },
                timestamp="2026-04-23T12:01:00Z",
            ),
            build_event(
                sequence=3,
                session_id="S-001",
                event_type="decision_discovered",
                project_version_after=3,
                payload={"decision": {"id": "D-001", "title": "Auth mode"}},
                timestamp="2026-04-23T12:02:00Z",
            ),
            build_event(
                sequence=4,
                session_id="S-001",
                event_type="proposal_issued",
                project_version_after=4,
                payload={
                    "proposal": {
                        "proposal_id": "P-001",
                        "origin_session_id": "S-001",
                        "target_type": "decision",
                        "target_id": "D-001",
                        "recommendation_version": 1,
                        "based_on_project_head": "H-4",
                        "question_id": "Q-001",
                        "question": "Use magic links?",
                        "recommendation": "Use magic links.",
                        "why": "Smaller MVP surface area.",
                        "if_not": "Passwords expand auth scope.",
                        "is_active": True,
                        "activated_at": "2026-04-23T12:03:00Z",
                        "inactive_reason": None,
                    }
                },
                timestamp="2026-04-23T12:03:00Z",
            ),
            build_event(
                sequence=5,
                session_id="S-001",
                event_type="proposal_accepted",
                project_version_after=5,
                payload={
                    "proposal_id": "P-001",
                    "origin_session_id": "S-001",
                    "target_type": "decision",
                    "target_id": "D-001",
                    "accepted_answer": {
                        "summary": "Use passwords.",
                        "accepted_at": "2026-04-23T12:04:00Z",
                        "accepted_via": "explicit",
                        "proposal_id": "P-001",
                    },
                },
                timestamp="2026-04-23T12:04:00Z",
            ),
        ]

        bundle = rebuild_projections(events)

        self.assertEqual("Use passwords.", bundle["sessions"]["S-001"]["summary"]["latest_summary"])


if __name__ == "__main__":
    unittest.main()
