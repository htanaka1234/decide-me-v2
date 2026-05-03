from __future__ import annotations

import unittest

from decide_me.events import build_event
from decide_me.validate import StateValidationError, validate_event_log
from tests.helpers.typed_metadata import metadata_for_object_type


class EventLogValidationTests(unittest.TestCase):
    def test_accepts_object_link_question_answer_flow(self) -> None:
        events = [
            *_base_events(),
            _event(3, "S-001", "object_recorded", {"object": _object("O-decision", "E-test-3")}),
            _event(4, "S-001", "object_recorded", {"object": _object("O-evidence", "E-test-4", object_type="evidence")}),
            _event(5, "S-001", "object_linked", {"link": _link("L-evidence-supports-decision", "E-test-5")}),
            _event(
                6,
                "S-001",
                "session_question_asked",
                {"question_id": "Q-001", "target_object_id": "O-decision", "question": "Use it?"},
            ),
            _event(
                7,
                "S-001",
                "session_answer_recorded",
                {
                    "question_id": "Q-001",
                    "target_object_id": "O-decision",
                    "answer": {
                        "summary": "Use it.",
                        "answered_at": "2026-04-23T12:07:00Z",
                        "answered_via": "explicit",
                    },
                },
            ),
        ]

        validate_event_log(events)

    def test_accepts_null_question_id_for_defer_answer(self) -> None:
        events = [
            *_base_events(),
            _event(3, "S-001", "object_recorded", {"object": _object("O-decision", "E-test-3")}),
            _event(
                4,
                "S-001",
                "session_answer_recorded",
                {
                    "question_id": None,
                    "target_object_id": "O-decision",
                    "answer": {
                        "summary": "Blocked pending signoff.",
                        "answered_at": "2026-04-23T12:04:00Z",
                        "answered_via": "defer",
                    },
                },
            ),
        ]

        validate_event_log(events)

    def test_rejects_unknown_non_null_question_id_for_answer(self) -> None:
        events = [
            *_base_events(),
            _event(3, "S-001", "object_recorded", {"object": _object("O-decision", "E-test-3")}),
            _event(
                4,
                "S-001",
                "session_answer_recorded",
                {
                    "question_id": "Q-missing",
                    "target_object_id": "O-decision",
                    "answer": {
                        "summary": "Use it.",
                        "answered_at": "2026-04-23T12:04:00Z",
                        "answered_via": "explicit",
                    },
                },
            ),
        ]

        with self.assertRaisesRegex(StateValidationError, "unknown pending question Q-missing"):
            validate_event_log(events)

    def test_rejects_duplicate_object_recorded_ids(self) -> None:
        events = [
            *_base_events(),
            _event(3, "S-001", "object_recorded", {"object": _object("O-dup", "E-test-3")}),
            _event(4, "S-001", "object_recorded", {"object": _object("O-dup", "E-test-4")}),
        ]

        with self.assertRaisesRegex(StateValidationError, "duplicate object_recorded id: O-dup"):
            validate_event_log(events)

    def test_rejects_object_updated_that_makes_typed_metadata_invalid(self) -> None:
        events = [
            *_base_events(),
            _event(3, "S-001", "object_recorded", {"object": _object("RISK-001", "E-test-3", object_type="risk")}),
            _event(4, "S-001", "object_updated", {"object_id": "RISK-001", "patch": {"metadata": {"risk_tier": "severe"}}}),
        ]

        with self.assertRaisesRegex(StateValidationError, "risk object RISK-001.metadata.risk_tier"):
            validate_event_log(events)

    def test_status_and_metadata_updates_validate_after_complete_transaction(self) -> None:
        events = [
            *_base_events(),
            _event(3, "S-001", "object_recorded", {"object": _object("D-001", "E-test-3")}),
            _event(
                4,
                "S-001",
                "object_status_changed",
                _status("D-001", "unresolved", "invalidated", 4),
                tx_id="T-invalidates",
                tx_index=1,
                tx_size=2,
            ),
            _event(
                5,
                "S-001",
                "object_updated",
                {
                    "object_id": "D-001",
                    "patch": {
                        "metadata": {
                            "invalidated_by": {
                                "decision_id": "D-root",
                                "invalidated_at": "2026-04-23T12:05:00Z",
                            }
                        }
                    },
                },
                tx_id="T-invalidates",
                tx_index=2,
                tx_size=2,
            ),
        ]

        validate_event_log(events)

    def test_rejects_missing_object_references(self) -> None:
        cases = [
            _event(3, "S-001", "object_updated", {"object_id": "O-missing", "patch": {"title": "No"}}),
            _event(3, "S-001", "object_status_changed", _status("O-missing", "unresolved", "accepted", 3)),
            _event(
                3,
                "S-001",
                "session_question_asked",
                {"question_id": "Q-001", "target_object_id": "O-missing", "question": "Use it?"},
            ),
        ]
        for event in cases:
            with self.subTest(event_type=event["event_type"]):
                with self.assertRaisesRegex(StateValidationError, "unknown object"):
                    validate_event_log([*_base_events(), event])

    def test_rejects_status_change_from_status_mismatch(self) -> None:
        events = [
            *_base_events(),
            _event(3, "S-001", "object_recorded", {"object": _object("O-decision", "E-test-3")}),
            _event(4, "S-001", "object_status_changed", _status("O-decision", "proposed", "accepted", 4)),
        ]

        with self.assertRaisesRegex(StateValidationError, "from_status mismatch"):
            validate_event_log(events)

    def test_rejects_link_with_missing_source_or_target(self) -> None:
        events = [
            *_base_events(),
            _event(3, "S-001", "object_recorded", {"object": _object("O-decision", "E-test-3")}),
            _event(4, "S-001", "object_linked", {"link": _link("L-bad", "E-test-4")}),
        ]

        with self.assertRaisesRegex(StateValidationError, "source_object_id references unknown object"):
            validate_event_log(events)

    def test_rejects_duplicate_active_link_ids(self) -> None:
        events = [
            *_base_events(),
            _event(3, "S-001", "object_recorded", {"object": _object("O-decision", "E-test-3")}),
            _event(4, "S-001", "object_recorded", {"object": _object("O-evidence", "E-test-4", object_type="evidence")}),
            _event(5, "S-001", "object_linked", {"link": _link("L-dup", "E-test-5")}),
            _event(6, "S-001", "object_linked", {"link": _link("L-dup", "E-test-6")}),
        ]

        with self.assertRaisesRegex(StateValidationError, "duplicate active link id: L-dup"):
            validate_event_log(events)

    def test_rejects_unknown_or_repeated_unlink(self) -> None:
        with self.assertRaisesRegex(StateValidationError, "unknown or inactive link L-missing"):
            validate_event_log([*_base_events(), _event(3, "S-001", "object_unlinked", {"link_id": "L-missing"})])

        events = [
            *_base_events(),
            _event(3, "S-001", "object_recorded", {"object": _object("O-decision", "E-test-3")}),
            _event(4, "S-001", "object_recorded", {"object": _object("O-evidence", "E-test-4", object_type="evidence")}),
            _event(5, "S-001", "object_linked", {"link": _link("L-001", "E-test-5")}),
            _event(6, "S-001", "object_unlinked", {"link_id": "L-001"}),
            _event(7, "S-001", "object_unlinked", {"link_id": "L-001"}),
        ]

        with self.assertRaisesRegex(StateValidationError, "unknown or inactive link L-001"):
            validate_event_log(events)

    def test_transaction_rejected_control_event_still_validates(self) -> None:
        events = [
            *_base_events(),
            _event(3, "S-001", "object_recorded", {"object": _object("O-kept", "E-test-3")}, tx_id="T-keep"),
            _event(
                4,
                "S-001",
                "transaction_rejected",
                {
                    "kept_tx_id": "T-keep",
                    "rejected_tx_ids": ["T-reject"],
                    "reason": "Keep this object.",
                    "resolved_at": "2026-04-23T12:04:00Z",
                    "conflict_kind": "duplicate-object-recording",
                    "conflict_summary": "duplicate object_recorded id: O-kept",
                },
                tx_id="T-control",
            ),
        ]

        validate_event_log(events)


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


def _event(
    sequence: int,
    session_id: str,
    event_type: str,
    payload: dict,
    *,
    tx_id: str | None = None,
    tx_index: int = 1,
    tx_size: int = 1,
) -> dict:
    return build_event(
        tx_id=tx_id or f"T-test-{sequence}",
        tx_index=tx_index,
        tx_size=tx_size,
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
