from __future__ import annotations

import unittest

from decide_me.events import EventValidationError, build_event, validate_event
from tests.helpers.legacy_term_policy import LEGACY_EVENT_TYPE_TERMS, LEGACY_PROJECT_STATE_TERMS


class EventTests(unittest.TestCase):
    def test_legacy_event_types_are_rejected(self) -> None:
        for event_type in LEGACY_EVENT_TYPE_TERMS:
            with self.subTest(event_type=event_type):
                with self.assertRaisesRegex(EventValidationError, f"unsupported event_type: {event_type}"):
                    _event(event_type=event_type, payload={})

    def test_project_initialized_rejects_stale_seed_payload(self) -> None:
        stale_seed_key = next(term for term in LEGACY_PROJECT_STATE_TERMS if term.startswith("default"))

        with self.assertRaisesRegex(EventValidationError, stale_seed_key):
            _event(
                event_type="project_initialized",
                session_id="SYSTEM",
                payload={
                    "project": _project_payload(),
                    stale_seed_key: [],
                },
            )

    def test_object_recorded_accepts_object_schema_shape(self) -> None:
        event = _event(
            event_type="object_recorded",
            payload={"object": _object("O-001", event_id="E-test-1")},
        )

        validate_event(event)

    def test_object_recorded_rejects_missing_required_object_fields(self) -> None:
        obj = _object("O-001", event_id="E-test-1")
        obj.pop("metadata")

        with self.assertRaisesRegex(EventValidationError, "metadata"):
            _event(event_type="object_recorded", payload={"object": obj})

    def test_object_updated_rejects_runtime_managed_patch_fields(self) -> None:
        for field in ("id", "type", "status", "links"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(EventValidationError, f"unsupported fields: {field}"):
                    _event(
                        event_type="object_updated",
                        payload={"object_id": "O-001", "patch": {field: "blocked"}},
                    )

    def test_object_status_changed_accepts_audited_status_transition(self) -> None:
        event = _event(
            event_type="object_status_changed",
            payload={
                "object_id": "O-001",
                "from_status": "unresolved",
                "to_status": "accepted",
                "reason": "Accepted by explicit reply.",
                "changed_at": "2026-04-23T12:00:00Z",
            },
        )

        validate_event(event)

    def test_object_status_changed_rejects_legacy_status_payload(self) -> None:
        with self.assertRaisesRegex(EventValidationError, "from_status"):
            _event(
                event_type="object_status_changed",
                payload={"object_id": "O-001", "status": "accepted"},
            )

    def test_object_linked_accepts_link_schema_shape(self) -> None:
        event = _event(
            event_type="object_linked",
            payload={"link": _link("L-001", event_id="E-test-1")},
        )

        validate_event(event)

    def test_session_answer_recorded_requires_answer_shape(self) -> None:
        with self.assertRaisesRegex(EventValidationError, "answered_at"):
            _event(
                event_type="session_answer_recorded",
                payload={
                    "question_id": "Q-001",
                    "target_object_id": "O-001",
                    "answer": {"summary": "Use it.", "answered_via": "explicit"},
                },
            )

    def test_session_answer_recorded_allows_null_question_id_for_defer(self) -> None:
        event = _event(
            event_type="session_answer_recorded",
            payload={
                "question_id": None,
                "target_object_id": "O-001",
                "answer": {
                    "summary": "Blocked pending signoff.",
                    "answered_at": "2026-04-23T12:00:00Z",
                    "answered_via": "defer",
                },
            },
        )

        validate_event(event)

    def test_session_answer_recorded_rejects_null_question_id_for_non_defer(self) -> None:
        with self.assertRaisesRegex(EventValidationError, "may be null only"):
            _event(
                event_type="session_answer_recorded",
                payload={
                    "question_id": None,
                    "target_object_id": "O-001",
                    "answer": {
                        "summary": "Use it.",
                        "answered_at": "2026-04-23T12:00:00Z",
                        "answered_via": "explicit",
                    },
                },
            )

    def test_transaction_rejected_remains_valid(self) -> None:
        event = _event(
            event_type="transaction_rejected",
            payload={
                "kept_tx_id": "T-keep",
                "rejected_tx_ids": ["T-reject"],
                "reason": "Keep the first transaction.",
                "resolved_at": "2026-04-23T12:00:00Z",
                "conflict_kind": "duplicate-object-recording",
                "conflict_summary": "duplicate object_recorded id: O-001",
            },
        )

        validate_event(event)

    def test_session_created_accepts_domain_pack_classification(self) -> None:
        event = _event(
            event_type="session_created",
            payload={
                "session": {
                    "id": "S-001",
                    "started_at": "2026-04-23T12:00:00Z",
                    "last_seen_at": "2026-04-23T12:00:00Z",
                    "bound_context_hint": "Research context",
                    "classification": _classification_payload(),
                }
            },
        )

        validate_event(event)

    def test_session_created_rejects_invalid_domain_pack_classification(self) -> None:
        cases = (
            ("domain_pack_id", "Research"),
            ("domain_pack_digest", "DP-nothex"),
        )
        for key, value in cases:
            with self.subTest(key=key):
                classification = _classification_payload()
                classification[key] = value

                with self.assertRaisesRegex(EventValidationError, key):
                    _event(
                        event_type="session_created",
                        payload={
                            "session": {
                                "id": "S-001",
                                "started_at": "2026-04-23T12:00:00Z",
                                "last_seen_at": "2026-04-23T12:00:00Z",
                                "bound_context_hint": "Research context",
                                "classification": classification,
                            }
                        },
                    )


def _event(*, event_type: str, payload: dict, session_id: str = "S-001") -> dict:
    return build_event(
        tx_id="T-test-1",
        tx_index=1,
        tx_size=1,
        event_id="E-test-1",
        session_id=session_id,
        event_type=event_type,
        payload=payload,
        timestamp="2026-04-23T12:00:00Z",
        project_head="H-before",
    )


def _object(object_id: str, *, event_id: str) -> dict:
    return {
        "id": object_id,
        "type": "decision",
        "title": "Choose auth",
        "body": "Pick the MVP auth shape.",
        "status": "unresolved",
        "created_at": "2026-04-23T12:00:00Z",
        "updated_at": None,
        "source_event_ids": [event_id],
        "metadata": {},
    }


def _link(link_id: str, *, event_id: str) -> dict:
    return {
        "id": link_id,
        "source_object_id": "O-source",
        "relation": "supports",
        "target_object_id": "O-target",
        "rationale": "Evidence supports the decision.",
        "created_at": "2026-04-23T12:00:00Z",
        "source_event_ids": [event_id],
    }


def _project_payload() -> dict:
    return {
        "name": "Demo",
        "objective": "Plan the milestone.",
        "current_milestone": "Phase 5",
        "stop_rule": "Resolve blockers.",
    }


def _classification_payload() -> dict:
    return {
        "domain": "data",
        "abstraction_level": None,
        "domain_pack_id": "research",
        "domain_pack_version": "0.1.0",
        "domain_pack_digest": "DP-123456789abc",
        "assigned_tags": [],
        "search_terms": [],
        "source_refs": [],
        "updated_at": "2026-04-23T12:00:00Z",
    }


if __name__ == "__main__":
    unittest.main()
