from __future__ import annotations

import unittest

from decide_me.events import EventValidationError, build_event


class LegacyEventTypesRejectedIntegrationTests(unittest.TestCase):
    def test_deleted_event_types_are_unsupported(self) -> None:
        for event_type in (
            "decision_discovered",
            "decision_enriched",
            "question_asked",
            "proposal_issued",
            "proposal_accepted",
            "proposal_rejected",
            "decision_deferred",
            "decision_resolved_by_evidence",
            "decision_invalidated",
            "compatibility_backfilled",
            "classification_updated",
            "session_linked",
            "semantic_conflict_resolved",
        ):
            with self.subTest(event_type=event_type):
                with self.assertRaisesRegex(EventValidationError, f"unsupported event_type: {event_type}"):
                    build_event(
                        tx_id="T-legacy",
                        tx_index=1,
                        tx_size=1,
                        event_id="E-legacy",
                        session_id="S-001",
                        event_type=event_type,
                        payload={},
                        timestamp="2026-04-23T12:00:00Z",
                    )


if __name__ == "__main__":
    unittest.main()
