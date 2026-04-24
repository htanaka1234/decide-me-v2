from __future__ import annotations

import unittest
from copy import deepcopy

from decide_me.events import build_event
from decide_me.projections import default_decision, default_project_state, default_session_state
from decide_me.taxonomy import default_taxonomy_state
from decide_me.validate import StateValidationError, validate_event_log, validate_projection_bundle


class ProjectionValidationTests(unittest.TestCase):
    def test_rejects_unknown_session_decision_reference(self) -> None:
        bundle = _valid_bundle()
        bundle["sessions"]["S-001"]["session"]["decision_ids"] = ["D-missing"]

        with self.assertRaisesRegex(StateValidationError, "unknown decision"):
            validate_projection_bundle(bundle)

    def test_rejects_active_proposal_not_owned_by_session(self) -> None:
        bundle = _valid_bundle()
        session = bundle["sessions"]["S-001"]
        session["working_state"]["active_proposal"] = _active_proposal(
            proposal_id="P-001",
            origin_session_id="S-other",
            decision_id="D-001",
        )

        with self.assertRaisesRegex(StateValidationError, "wrong origin_session_id"):
            validate_projection_bundle(bundle)

    def test_rejects_active_proposal_target_not_bound_to_session(self) -> None:
        bundle = _valid_bundle()
        decision = default_decision("D-002", "Unbound")
        decision["status"] = "proposed"
        decision["recommendation"]["proposal_id"] = "P-002"
        bundle["project_state"]["decisions"].append(decision)
        session = bundle["sessions"]["S-001"]
        session["summary"]["active_decision_id"] = "D-002"
        session["working_state"]["active_proposal"] = _active_proposal(
            proposal_id="P-002",
            origin_session_id="S-001",
            decision_id="D-002",
        )

        with self.assertRaisesRegex(StateValidationError, "not bound"):
            validate_projection_bundle(bundle)

    def test_rejects_unknown_taxonomy_tag_reference(self) -> None:
        bundle = _valid_bundle()
        bundle["sessions"]["S-001"]["classification"]["assigned_tags"] = ["tag:missing"]

        with self.assertRaisesRegex(StateValidationError, "unknown taxonomy"):
            validate_projection_bundle(bundle)

    def test_rejects_invalidated_decision_in_close_summary(self) -> None:
        bundle = _valid_bundle()
        replacement = default_decision("D-002", "Replacement")
        replacement["status"] = "accepted"
        replacement["accepted_answer"]["summary"] = "Use the replacement."
        replacement["accepted_answer"]["accepted_via"] = "explicit"
        bundle["project_state"]["decisions"].append(replacement)
        invalidated = bundle["project_state"]["decisions"][0]
        invalidated["status"] = "invalidated"
        invalidated["invalidated_by"] = {
            "decision_id": "D-002",
            "reason": "Superseded.",
            "invalidated_at": "2026-04-23T12:00:00Z",
        }
        session = bundle["sessions"]["S-001"]
        session["session"]["decision_ids"] = []
        session["close_summary"]["accepted_decisions"] = [{"id": "D-001"}]

        with self.assertRaisesRegex(StateValidationError, "non-visible decision"):
            validate_projection_bundle(bundle)

    def test_rejects_accepted_answer_proposal_mismatch(self) -> None:
        bundle = _valid_bundle()
        decision = bundle["project_state"]["decisions"][0]
        decision["status"] = "accepted"
        decision["recommendation"]["proposal_id"] = "P-001"
        decision["accepted_answer"]["summary"] = "Use it."
        decision["accepted_answer"]["accepted_via"] = "explicit"
        decision["accepted_answer"]["proposal_id"] = "P-other"

        with self.assertRaisesRegex(StateValidationError, "accepted_answer.proposal_id"):
            validate_projection_bundle(bundle)

    def test_rejects_proposed_decision_without_active_proposal(self) -> None:
        bundle = _valid_bundle()
        decision = bundle["project_state"]["decisions"][0]
        decision["status"] = "proposed"
        decision["recommendation"]["proposal_id"] = "P-001"

        with self.assertRaisesRegex(StateValidationError, "active proposal targets"):
            validate_projection_bundle(bundle)

    def test_rejects_invalid_decision_enum_values(self) -> None:
        bundle = _valid_bundle()
        decision = bundle["project_state"]["decisions"][0]
        decision["priority"] = "PX"

        with self.assertRaisesRegex(StateValidationError, "priority"):
            validate_projection_bundle(bundle)

    def test_rejects_status_payload_mismatch(self) -> None:
        bundle = _valid_bundle()
        decision = bundle["project_state"]["decisions"][0]
        decision["status"] = "accepted"

        with self.assertRaisesRegex(StateValidationError, "accepted_answer.summary"):
            validate_projection_bundle(bundle)

        bundle = _valid_bundle()
        decision = bundle["project_state"]["decisions"][0]
        decision["status"] = "unresolved"
        decision["accepted_answer"]["summary"] = "Use it."

        with self.assertRaisesRegex(StateValidationError, "must not have accepted_answer.summary"):
            validate_projection_bundle(bundle)

    def test_rejects_resolved_by_evidence_unknown_source(self) -> None:
        bundle = _valid_bundle()
        decision = bundle["project_state"]["decisions"][0]
        decision["status"] = "resolved-by-evidence"
        decision["accepted_answer"]["summary"] = "Use it."
        decision["accepted_answer"]["accepted_via"] = "evidence"
        decision["resolved_by_evidence"]["summary"] = "Found it."
        decision["resolved_by_evidence"]["source"] = "aliens"

        with self.assertRaisesRegex(StateValidationError, "resolved_by_evidence.source"):
            validate_projection_bundle(bundle)

    def test_rejects_empty_project_fields(self) -> None:
        bundle = _valid_bundle()
        bundle["project_state"]["project"]["objective"] = " "

        with self.assertRaisesRegex(StateValidationError, "non-empty string"):
            validate_projection_bundle(bundle)

    def test_event_log_must_start_with_project_initialized(self) -> None:
        event = build_event(
            sequence=1,
            session_id="S-001",
            event_type="session_created",
            project_version_after=1,
            payload={
                "session": {
                    "id": "S-001",
                    "started_at": "2026-04-23T12:00:00Z",
                    "last_seen_at": "2026-04-23T12:00:00Z",
                    "bound_context_hint": "demo",
                }
            },
            timestamp="2026-04-23T12:00:00Z",
        )

        with self.assertRaisesRegex(StateValidationError, "start with project_initialized"):
            validate_event_log([event])

    def test_event_log_rejects_mismatched_event_id_sequence(self) -> None:
        event = build_event(
            sequence=2,
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

        with self.assertRaisesRegex(StateValidationError, "does not match sequence"):
            validate_event_log([event])

    def test_event_log_rejects_duplicate_project_initialized(self) -> None:
        first = build_event(
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
        second = build_event(
            sequence=2,
            session_id="SYSTEM",
            event_type="project_initialized",
            project_version_after=2,
            payload={
                "project": {
                    "name": "Demo 2",
                    "objective": "Test",
                    "current_milestone": "MVP",
                    "stop_rule": "Resolve blockers",
                }
            },
            timestamp="2026-04-23T12:01:00Z",
        )

        with self.assertRaisesRegex(StateValidationError, "exactly one"):
            validate_event_log([first, second])

    def test_event_log_rejects_duplicate_decision_discovered_ids(self) -> None:
        initialized = _project_initialized(1)
        first_session = _session_created(2, "S-001")
        second_session = _session_created(3, "S-002")
        first = _decision_discovered(4, "S-001", "D-001")
        second = _decision_discovered(5, "S-002", "D-001")

        with self.assertRaisesRegex(StateValidationError, "duplicate decision_discovered"):
            validate_event_log([initialized, first_session, second_session, first, second])

    def test_event_log_rejects_unknown_session_id(self) -> None:
        initialized = _project_initialized(1)
        discovered = _decision_discovered(2, "S-missing", "D-001")

        with self.assertRaisesRegex(StateValidationError, "unknown session"):
            validate_event_log([initialized, discovered])

    def test_event_log_rejects_session_created_id_mismatch(self) -> None:
        initialized = _project_initialized(1)
        mismatched = build_event(
            sequence=2,
            session_id="S-outer",
            event_type="session_created",
            project_version_after=2,
            payload={
                "session": {
                    "id": "S-inner",
                    "started_at": "2026-04-23T12:01:00Z",
                    "last_seen_at": "2026-04-23T12:01:00Z",
                    "bound_context_hint": "demo",
                }
            },
            timestamp="2026-04-23T12:01:00Z",
        )

        with self.assertRaisesRegex(StateValidationError, "must match"):
            validate_event_log([initialized, mismatched])

    def test_event_log_rejects_decision_refs_before_discovery(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        proposal = _proposal_issued(3, "S-001", "D-never")

        with self.assertRaisesRegex(StateValidationError, "undiscovered decision D-never"):
            validate_event_log([initialized, session, proposal])

    def test_event_log_rejects_deferred_and_accepted_undiscovered_decisions(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        deferred = build_event(
            sequence=3,
            session_id="S-001",
            event_type="decision_deferred",
            project_version_after=3,
            payload={"decision_id": "D-never", "reason": "Later."},
            timestamp="2026-04-23T12:02:00Z",
        )

        with self.assertRaisesRegex(StateValidationError, "undiscovered decision D-never"):
            validate_event_log([initialized, session, deferred])

        accepted = build_event(
            sequence=3,
            session_id="S-001",
            event_type="proposal_accepted",
            project_version_after=3,
            payload={
                "proposal_id": "P-001",
                "origin_session_id": "S-001",
                "target_type": "decision",
                "target_id": "D-never",
                "accepted_answer": {
                    "summary": "Use it.",
                    "accepted_at": "2026-04-23T12:02:00Z",
                    "accepted_via": "explicit",
                    "proposal_id": "P-001",
                },
            },
            timestamp="2026-04-23T12:02:00Z",
        )

        with self.assertRaisesRegex(StateValidationError, "undiscovered decision D-never"):
            validate_event_log([initialized, session, accepted])


def _project_initialized(sequence: int) -> dict:
    return build_event(
        sequence=sequence,
        session_id="SYSTEM",
        event_type="project_initialized",
        project_version_after=sequence,
        payload={
            "project": {
                "name": "Demo",
                "objective": "Test",
                "current_milestone": "MVP",
                "stop_rule": "Resolve blockers",
            }
        },
        timestamp=f"2026-04-23T12:{sequence - 1:02d}:00Z",
    )


def _session_created(sequence: int, session_id: str) -> dict:
    return build_event(
        sequence=sequence,
        session_id=session_id,
        event_type="session_created",
        project_version_after=sequence,
        payload={
            "session": {
                "id": session_id,
                "started_at": f"2026-04-23T12:{sequence - 1:02d}:00Z",
                "last_seen_at": f"2026-04-23T12:{sequence - 1:02d}:00Z",
                "bound_context_hint": "demo",
            }
        },
        timestamp=f"2026-04-23T12:{sequence - 1:02d}:00Z",
    )


def _decision_discovered(sequence: int, session_id: str, decision_id: str) -> dict:
    return build_event(
        sequence=sequence,
        session_id=session_id,
        event_type="decision_discovered",
        project_version_after=sequence,
        payload={"decision": {"id": decision_id, "title": "Decision"}},
        timestamp=f"2026-04-23T12:{sequence - 1:02d}:00Z",
    )


def _proposal_issued(sequence: int, session_id: str, decision_id: str) -> dict:
    return build_event(
        sequence=sequence,
        session_id=session_id,
        event_type="proposal_issued",
        project_version_after=sequence,
        payload={
            "proposal": {
                "proposal_id": "P-001",
                "origin_session_id": session_id,
                "target_type": "decision",
                "target_id": decision_id,
                "recommendation_version": 1,
                "based_on_project_version": sequence - 1,
                "question_id": "Q-001",
                "question": "Question?",
                "recommendation": "Use it.",
                "why": "Because.",
                "if_not": "Risk.",
                "is_active": True,
                "activated_at": f"2026-04-23T12:{sequence - 1:02d}:00Z",
                "inactive_reason": None,
            }
        },
        timestamp=f"2026-04-23T12:{sequence - 1:02d}:00Z",
    )


def _valid_bundle() -> dict:
    now = "2026-04-23T12:00:00Z"
    project_state = default_project_state()
    project_state["project"] = {
        "name": "Demo",
        "objective": "Test",
        "current_milestone": "MVP",
        "stop_rule": "Resolve blockers",
    }
    project_state["decisions"] = [default_decision("D-001", "Decision")]
    session = default_session_state("S-001", now, "demo")
    session["session"]["decision_ids"] = ["D-001"]
    return {
        "project_state": project_state,
        "taxonomy_state": default_taxonomy_state(now=now),
        "sessions": {"S-001": session},
    }


def _active_proposal(*, proposal_id: str, origin_session_id: str, decision_id: str) -> dict:
    proposal = deepcopy(default_session_state("S-template", "2026-04-23T12:00:00Z")["working_state"]["active_proposal"])
    proposal.update(
        {
            "proposal_id": proposal_id,
            "origin_session_id": origin_session_id,
            "target_type": "decision",
            "target_id": decision_id,
            "recommendation_version": 1,
            "based_on_project_version": 1,
            "is_active": True,
            "activated_at": "2026-04-23T12:00:00Z",
            "inactive_reason": None,
            "question_id": "Q-001",
            "question": "Question?",
            "recommendation": "Use it.",
            "why": "Because.",
            "if_not": "Risk.",
        }
    )
    return proposal


if __name__ == "__main__":
    unittest.main()
