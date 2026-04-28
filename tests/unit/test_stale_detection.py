from __future__ import annotations

import unittest
from copy import deepcopy

from decide_me.stale_detection import (
    detect_revisit_due,
    detect_stale_assumptions,
    detect_stale_evidence,
    detect_verification_gaps,
)
from tests.helpers.typed_metadata import (
    assumption_metadata,
    evidence_metadata,
    revisit_trigger_metadata,
    verification_metadata,
)


NOW = "2026-04-28T12:00:00Z"
PAST = "2026-04-27T12:00:00Z"
FUTURE = "2026-04-29T12:00:00Z"


class StaleDetectionTests(unittest.TestCase):
    def test_expired_assumption_is_reported_but_null_and_future_are_not(self) -> None:
        project_state = _project_state(
            objects=[
                _object("AS-001", "assumption", assumption_metadata(expires_at=PAST, owner="owner")),
                _object("AS-002", "assumption", assumption_metadata(expires_at=FUTURE)),
                _object("AS-003", "assumption", assumption_metadata(expires_at=None)),
                _object("D-001", "decision"),
            ],
            links=[_link("L-AS-001-constrains-D-001", "AS-001", "constrains", "D-001")],
        )

        payload = detect_stale_assumptions(project_state, now=NOW)

        self.assertEqual("stale_assumptions", payload["diagnostic_type"])
        self.assertEqual(["AS-001"], [item["object_id"] for item in payload["items"]])
        item = payload["items"][0]
        self.assertEqual("expires_at_elapsed", item["stale_reason"])
        self.assertEqual(["D-001"], item["related_object_ids"])
        self.assertEqual(["L-AS-001-constrains-D-001"], item["related_link_ids"])

    def test_expired_or_explicitly_stale_evidence_is_reported(self) -> None:
        project_state = _project_state(
            objects=[
                _object("D-001", "decision", status="accepted"),
                _object("D-002", "decision"),
                _object("E-001", "evidence", evidence_metadata(valid_until=PAST, freshness="current")),
                _object("E-002", "evidence", evidence_metadata(source_ref="docs/stale.md", freshness="stale")),
                _object("E-003", "evidence", evidence_metadata(source_ref="docs/current.md", valid_until=FUTURE)),
            ],
            links=[
                _link("L-E-001-supports-D-001", "E-001", "supports", "D-001"),
                _link("L-E-002-verifies-D-002", "E-002", "verifies", "D-002"),
                _link("L-E-003-supports-D-001", "E-003", "supports", "D-001"),
            ],
        )

        payload = detect_stale_evidence(project_state, now=NOW)

        self.assertEqual(["E-001", "E-002"], [item["object_id"] for item in payload["items"]])
        by_id = {item["object_id"]: item for item in payload["items"]}
        self.assertEqual(["valid_until_elapsed"], by_id["E-001"]["stale_reasons"])
        self.assertEqual(["freshness_stale"], by_id["E-002"]["stale_reasons"])
        self.assertEqual(["D-001"], by_id["E-001"]["affected_decision_ids"])
        self.assertEqual(["D-002"], by_id["E-002"]["affected_decision_ids"])
        self.assertEqual(2, payload["summary"]["affected_decision_count"])

    def test_verification_gap_reports_completed_action_as_high_severity(self) -> None:
        project_state = _project_state(
            objects=[
                _object("A-001", "action", status="completed"),
                _object("A-002", "action"),
                _object("A-003", "action"),
                _object("V-001", "verification", verification_metadata()),
                _object("E-001", "evidence", evidence_metadata()),
            ],
            links=[
                _link("L-V-001-verifies-A-002", "V-001", "verifies", "A-002"),
                _link("L-E-001-supports-A-003", "E-001", "supports", "A-003"),
            ],
        )

        payload = detect_verification_gaps(project_state, now=NOW)

        self.assertEqual(["A-001"], [item["object_id"] for item in payload["items"]])
        self.assertEqual("high", payload["items"][0]["gap_severity"])
        self.assertEqual({"high": 1}, payload["summary"]["by_gap_severity"])

    def test_live_action_without_verification_is_medium_severity_gap(self) -> None:
        payload = detect_verification_gaps(
            _project_state(objects=[_object("A-001", "action")], links=[]),
            now=NOW,
        )

        self.assertEqual(["A-001"], [item["object_id"] for item in payload["items"]])
        self.assertEqual("medium", payload["items"][0]["gap_severity"])

    def test_due_revisit_trigger_is_reported_but_null_and_future_are_not(self) -> None:
        project_state = _project_state(
            objects=[
                _object(
                    "RT-001",
                    "revisit_trigger",
                    revisit_trigger_metadata(due_at=PAST, target_object_ids=["D-001"]),
                ),
                _object(
                    "RT-002",
                    "revisit_trigger",
                    revisit_trigger_metadata(due_at=FUTURE, target_object_ids=["D-001"]),
                ),
                _object(
                    "RT-003",
                    "revisit_trigger",
                    revisit_trigger_metadata(due_at=None, target_object_ids=["D-001"]),
                ),
                _object("D-001", "decision"),
            ],
            links=[_link("L-RT-001-revisits-D-001", "RT-001", "revisits", "D-001")],
        )

        payload = detect_revisit_due(project_state, now=NOW)

        self.assertEqual(["RT-001"], [item["object_id"] for item in payload["items"]])
        item = payload["items"][0]
        self.assertEqual("due_at_elapsed", item["due_reason"])
        self.assertEqual(["D-001"], item["target_object_ids"])
        self.assertEqual(["L-RT-001-revisits-D-001"], item["related_link_ids"])

    def test_invalid_now_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "now must be ISO-8601/RFC3339-like"):
            detect_stale_assumptions(_project_state(objects=[], links=[]), now="not-a-time")


def _project_state(*, objects: list[dict], links: list[dict]) -> dict:
    return {
        "schema_version": 12,
        "state": {
            "project_head": "H-test",
            "event_count": len(objects) + len(links),
            "updated_at": "2026-04-28T00:00:00Z",
            "last_event_id": "E-last",
        },
        "objects": deepcopy(objects),
        "links": deepcopy(links),
    }


def _object(
    object_id: str,
    object_type: str,
    metadata: dict | None = None,
    *,
    status: str = "active",
) -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": object_id,
        "body": None,
        "status": status,
        "created_at": "2026-04-28T00:00:00Z",
        "updated_at": None,
        "source_event_ids": ["E-create"],
        "metadata": {} if metadata is None else deepcopy(metadata),
    }


def _link(link_id: str, source: str, relation: str, target: str) -> dict:
    return {
        "id": link_id,
        "source_object_id": source,
        "relation": relation,
        "target_object_id": target,
        "rationale": "Stale detection fixture link.",
        "created_at": "2026-04-28T00:00:00Z",
        "source_event_ids": ["E-link"],
    }


if __name__ == "__main__":
    unittest.main()
