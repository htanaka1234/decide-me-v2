from __future__ import annotations

import unittest

from decide_me.events import build_event, validate_event


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


if __name__ == "__main__":
    unittest.main()
