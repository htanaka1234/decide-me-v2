from __future__ import annotations

from copy import deepcopy
import unittest

from decide_me.events import build_event
from decide_me.projections import apply_events_to_bundle, rebuild_projections
from tests.helpers.typed_metadata import metadata_for_object_type


class ProjectionTests(unittest.TestCase):
    def test_object_events_project_objects_and_links(self) -> None:
        events = _base_events()
        events.extend(
            [
                _event(
                    3,
                    "S-001",
                    "object_recorded",
                    {"object": _object("O-decision", "E-test-3")},
                ),
                _event(
                    4,
                    "S-001",
                    "object_updated",
                    {
                        "object_id": "O-decision",
                        "patch": {"title": "Choose auth now", "metadata": {"priority": "P0"}},
                    },
                ),
                _event(
                    5,
                    "S-001",
                    "object_status_changed",
                    _status("O-decision", "unresolved", "accepted", 5),
                ),
                _event(
                    6,
                    "S-001",
                    "object_recorded",
                    {"object": _object("O-evidence", "E-test-6", object_type="evidence")},
                ),
                _event(
                    7,
                    "S-001",
                    "object_linked",
                    {"link": _link("L-evidence-supports-decision", "E-test-7")},
                ),
            ]
        )

        bundle = rebuild_projections(events)
        objects = {item["id"]: item for item in bundle["project_state"]["objects"]}
        links = {item["id"]: item for item in bundle["project_state"]["links"]}

        self.assertEqual("Choose auth now", objects["O-decision"]["title"])
        self.assertEqual("accepted", objects["O-decision"]["status"])
        self.assertEqual("P0", objects["O-decision"]["metadata"]["priority"])
        self.assertIn("L-evidence-supports-decision", links)

    def test_object_unlinked_removes_link_from_projection(self) -> None:
        events = [
            *_base_events(),
            _event(3, "S-001", "object_recorded", {"object": _object("O-decision", "E-test-3")}),
            _event(4, "S-001", "object_recorded", {"object": _object("O-evidence", "E-test-4", object_type="evidence")}),
            _event(5, "S-001", "object_linked", {"link": _link("L-evidence-supports-decision", "E-test-5")}),
            _event(6, "S-001", "object_unlinked", {"link_id": "L-evidence-supports-decision"}),
        ]

        bundle = rebuild_projections(events)

        self.assertNotIn(
            "L-evidence-supports-decision",
            {item["id"] for item in bundle["project_state"]["links"]},
        )

    def test_incremental_projection_matches_rebuild(self) -> None:
        events = [
            *_base_events(),
            _event(3, "S-001", "object_recorded", {"object": _object("O-decision", "E-test-3")}),
            _event(4, "S-001", "object_status_changed", _status("O-decision", "unresolved", "accepted", 4)),
        ]

        rebuilt = rebuild_projections(events)
        incremental = apply_events_to_bundle(deepcopy(rebuild_projections(events[:2])), events[2:])

        self.assertEqual(rebuilt, incremental)

    def test_status_change_rejects_from_status_mismatch(self) -> None:
        events = [
            *_base_events(),
            _event(3, "S-001", "object_recorded", {"object": _object("O-decision", "E-test-3")}),
            _event(4, "S-001", "object_status_changed", _status("O-decision", "proposed", "accepted", 4)),
        ]

        with self.assertRaisesRegex(ValueError, "from_status|expected"):
            rebuild_projections(events)


def _base_events() -> list[dict]:
    return [
        _event(
            1,
            "SYSTEM",
            "project_initialized",
            {
                "project": {
                    "name": "Demo",
                    "objective": "Plan it.",
                    "current_milestone": "MVP",
                    "stop_rule": "Resolve blockers.",
                }
            },
        ),
        _event(
            2,
            "S-001",
            "session_created",
            {
                "session": {
                    "id": "S-001",
                    "started_at": "2026-04-23T12:01:00Z",
                    "last_seen_at": "2026-04-23T12:01:00Z",
                    "bound_context_hint": "Test session",
                }
            },
        ),
    ]


def _event(sequence: int, session_id: str, event_type: str, payload: dict) -> dict:
    return build_event(
        tx_id=f"T-test-{sequence}",
        tx_index=1,
        tx_size=1,
        event_id=f"E-test-{sequence}",
        session_id=session_id,
        event_type=event_type,
        payload=payload,
        timestamp=f"2026-04-23T12:{sequence:02d}:00Z",
        project_head="H-before",
    )


def _status(object_id: str, from_status: str, to_status: str, sequence: int) -> dict:
    return {
        "object_id": object_id,
        "from_status": from_status,
        "to_status": to_status,
        "reason": "Test status change.",
        "changed_at": f"2026-04-23T12:{sequence:02d}:00Z",
    }


def _object(object_id: str, event_id: str, *, object_type: str = "decision") -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": object_id,
        "body": "Body",
        "status": "active" if object_type != "decision" else "unresolved",
        "created_at": "2026-04-23T12:00:00Z",
        "updated_at": None,
        "source_event_ids": [event_id],
        "metadata": metadata_for_object_type(object_type),
    }


def _link(link_id: str, event_id: str) -> dict:
    return {
        "id": link_id,
        "source_object_id": "O-evidence",
        "relation": "supports",
        "target_object_id": "O-decision",
        "rationale": "Evidence supports it.",
        "created_at": "2026-04-23T12:00:00Z",
        "source_event_ids": [event_id],
    }


if __name__ == "__main__":
    unittest.main()
