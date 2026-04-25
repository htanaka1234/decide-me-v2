from __future__ import annotations

import unittest

from decide_me.events import build_event
from decide_me.projections import rebuild_projections


class ProjectionTests(unittest.TestCase):
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
                        "based_on_project_version": 3,
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
