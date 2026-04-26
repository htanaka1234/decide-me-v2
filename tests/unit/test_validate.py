from __future__ import annotations

import unittest
from copy import deepcopy

from decide_me.events import EventValidationError, build_event as runtime_build_event
from decide_me.projections import default_decision, default_project_state, default_session_state
from decide_me.taxonomy import default_taxonomy_state
from decide_me.validate import StateValidationError, validate_event_log, validate_projection_bundle


def build_event(
    *,
    sequence: int,
    session_id: str,
    event_type: str,
    project_head_after: int,
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
        project_head=f"H-{project_head_after}",
    )


class ProjectionValidationTests(unittest.TestCase):
    def test_rejects_unknown_session_decision_reference(self) -> None:
        bundle = _valid_bundle()
        bundle["sessions"]["S-001"]["session"]["decision_ids"] = ["D-missing"]

        with self.assertRaisesRegex(StateValidationError, "unknown decision"):
            validate_projection_bundle(bundle)

    def test_rejects_visible_decision_unbound_to_any_session(self) -> None:
        bundle = _valid_bundle()
        bundle["sessions"]["S-001"]["session"]["decision_ids"] = []

        with self.assertRaisesRegex(StateValidationError, "not bound to any session"):
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

    def test_rejects_active_proposal_with_inactive_reason(self) -> None:
        bundle = _valid_bundle()
        decision = bundle["project_state"]["decisions"][0]
        decision["status"] = "proposed"
        decision["recommendation"]["proposal_id"] = "P-001"
        session = bundle["sessions"]["S-001"]
        session["summary"]["active_decision_id"] = "D-001"
        active = _active_proposal(
            proposal_id="P-001",
            origin_session_id="S-001",
            decision_id="D-001",
        )
        active["inactive_reason"] = "session-boundary"
        session["working_state"]["active_proposal"] = active

        with self.assertRaisesRegex(StateValidationError, "must not have inactive_reason"):
            validate_projection_bundle(bundle)

    def test_rejects_inactive_proposal_without_inactive_reason(self) -> None:
        bundle = _valid_bundle()
        session = bundle["sessions"]["S-001"]
        inactive = _active_proposal(
            proposal_id="P-001",
            origin_session_id="S-001",
            decision_id="D-001",
        )
        inactive["is_active"] = False
        inactive["inactive_reason"] = None
        session["working_state"]["active_proposal"] = inactive

        with self.assertRaisesRegex(StateValidationError, "inactive proposal must have inactive_reason"):
            validate_projection_bundle(bundle)

    def test_rejects_current_question_without_active_proposal(self) -> None:
        bundle = _valid_bundle()
        session = bundle["sessions"]["S-001"]
        session["summary"]["current_question_preview"] = "Dangling?"
        session["summary"]["active_decision_id"] = "D-001"
        session["working_state"]["current_question_id"] = "Q-001"
        session["working_state"]["current_question"] = "Dangling?"

        with self.assertRaisesRegex(StateValidationError, "without active proposal"):
            validate_projection_bundle(bundle)

    def test_rejects_current_question_mismatched_to_active_proposal(self) -> None:
        bundle = _valid_bundle()
        decision = bundle["project_state"]["decisions"][0]
        decision["status"] = "proposed"
        decision["recommendation"]["proposal_id"] = "P-001"
        session = bundle["sessions"]["S-001"]
        active = _active_proposal(
            proposal_id="P-001",
            origin_session_id="S-001",
            decision_id="D-001",
        )
        session["working_state"]["active_proposal"] = active
        session["working_state"]["current_question_id"] = "Q-other"
        session["working_state"]["current_question"] = active["question"]
        session["summary"]["current_question_preview"] = active["question"]
        session["summary"]["active_decision_id"] = "D-001"

        with self.assertRaisesRegex(StateValidationError, "current_question_id"):
            validate_projection_bundle(bundle)

    def test_rejects_invalid_projection_timestamps(self) -> None:
        bundle = _valid_bundle()
        bundle["sessions"]["S-001"]["session"]["last_seen_at"] = "not-time"

        with self.assertRaisesRegex(StateValidationError, "last_seen_at"):
            validate_projection_bundle(bundle)

        bundle = _valid_bundle()
        bundle["project_state"]["state"]["updated_at"] = "not-time"

        with self.assertRaisesRegex(StateValidationError, "project_state.state.updated_at"):
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
        replacement["recommendation"]["proposal_id"] = "P-002"
        replacement["accepted_answer"]["summary"] = "Use the replacement."
        replacement["accepted_answer"]["accepted_at"] = "2026-04-23T12:00:00Z"
        replacement["accepted_answer"]["accepted_via"] = "explicit"
        replacement["accepted_answer"]["proposal_id"] = "P-002"
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

    def test_rejects_resolved_conflict_scope_left_in_close_summary(self) -> None:
        bundle = _valid_bundle()
        decision = bundle["project_state"]["decisions"][0]
        decision["status"] = "accepted"
        decision["recommendation"]["proposal_id"] = "P-001"
        decision["accepted_answer"]["summary"] = "Use the losing slice."
        decision["accepted_answer"]["accepted_at"] = "2026-04-23T12:00:00Z"
        decision["accepted_answer"]["accepted_via"] = "explicit"
        decision["accepted_answer"]["proposal_id"] = "P-001"
        session = bundle["sessions"]["S-001"]
        session["close_summary"]["accepted_decisions"] = [
            {
                "id": "D-001",
                "title": "Shared slice",
                "kind": "choice",
                "domain": "technical",
                "priority": "P0",
                "status": "accepted",
                "resolvable_by": "human",
                "evidence_source": None,
                "evidence_refs": [],
                "accepted_answer": "Use the losing slice.",
            }
        ]
        session["close_summary"]["candidate_action_slices"] = [
            {
                "decision_id": "D-001",
                "name": "Shared slice",
                "summary": "Implement shared slice.",
                "responsibility": "technical",
                "priority": "P0",
                "status": "accepted",
                "kind": "choice",
                "resolvable_by": "human",
                "reversibility": "reversible",
                "implementation_ready": True,
                "evidence_backed": False,
                "evidence_source": None,
                "evidence_refs": [],
                "next_step": "Drive shared slice.",
            }
        ]
        session["close_summary"]["candidate_workstreams"] = [
            {
                "name": "technical-workstream",
                "summary": "Advance technical decisions for the current milestone.",
                "scope": ["D-001"],
                "accepted_count": 1,
                "implementation_ready_scope": ["D-001"],
            }
        ]
        bundle["project_state"]["session_graph"]["resolved_conflicts"] = [
            {
                "conflict_id": "C-action",
                "winning_session_id": "S-winner",
                "rejected_session_ids": ["S-001"],
                "scope": {
                    "kind": "action_slice",
                    "name": "Shared slice",
                    "session_ids": ["S-001", "S-winner"],
                },
                "suppressed_context": {
                    "session_ids": ["S-001"],
                    "decision_ids": ["D-001"],
                    "action_slice_names": ["Shared slice"],
                    "workstream_names": [],
                    "hidden_strings": ["Shared slice", "Use the losing slice."],
                },
                "reason": "Use the winner.",
                "resolved_at": "2026-04-23T12:00:00Z",
                "event_id": "E-resolution",
            }
        ]

        with self.assertRaisesRegex(StateValidationError, "leaves rejected scope"):
            validate_projection_bundle(bundle)

    def test_rejects_invalidated_decision_with_non_final_invalidator(self) -> None:
        bundle = _valid_bundle()
        replacement = default_decision("D-002", "Replacement")
        bundle["project_state"]["decisions"].append(replacement)
        invalidated = bundle["project_state"]["decisions"][0]
        invalidated["status"] = "invalidated"
        invalidated["invalidated_by"] = {
            "decision_id": "D-002",
            "reason": "Superseded.",
            "invalidated_at": "2026-04-23T12:00:00Z",
        }
        bundle["sessions"]["S-001"]["session"]["decision_ids"] = []

        with self.assertRaisesRegex(StateValidationError, "non-final decision D-002"):
            validate_projection_bundle(bundle)

    def test_rejects_accepted_answer_proposal_mismatch(self) -> None:
        bundle = _valid_bundle()
        decision = bundle["project_state"]["decisions"][0]
        decision["status"] = "accepted"
        decision["recommendation"]["proposal_id"] = "P-001"
        decision["accepted_answer"]["summary"] = "Use it."
        decision["accepted_answer"]["accepted_at"] = "2026-04-23T12:00:00Z"
        decision["accepted_answer"]["accepted_via"] = "explicit"
        decision["accepted_answer"]["proposal_id"] = "P-other"

        with self.assertRaisesRegex(StateValidationError, "accepted_answer.proposal_id"):
            validate_projection_bundle(bundle)

    def test_rejects_accepted_decision_without_proposal_id(self) -> None:
        bundle = _valid_bundle()
        decision = bundle["project_state"]["decisions"][0]
        decision["status"] = "accepted"
        decision["recommendation"]["proposal_id"] = "P-001"
        decision["accepted_answer"]["summary"] = "Use it."
        decision["accepted_answer"]["accepted_at"] = "2026-04-23T12:00:00Z"
        decision["accepted_answer"]["accepted_via"] = "explicit"

        with self.assertRaisesRegex(StateValidationError, "accepted_answer.proposal_id"):
            validate_projection_bundle(bundle)

    def test_rejects_accepted_decision_without_accepted_at(self) -> None:
        bundle = _valid_bundle()
        decision = bundle["project_state"]["decisions"][0]
        decision["status"] = "accepted"
        decision["recommendation"]["proposal_id"] = "P-001"
        decision["accepted_answer"]["summary"] = "Use it."
        decision["accepted_answer"]["accepted_via"] = "explicit"
        decision["accepted_answer"]["proposal_id"] = "P-001"

        with self.assertRaisesRegex(StateValidationError, "accepted_answer.accepted_at"):
            validate_projection_bundle(bundle)

    def test_rejects_proposed_decision_without_active_proposal(self) -> None:
        bundle = _valid_bundle()
        decision = bundle["project_state"]["decisions"][0]
        decision["status"] = "proposed"
        decision["recommendation"]["proposal_id"] = "P-001"

        with self.assertRaisesRegex(StateValidationError, "active proposal targets"):
            validate_projection_bundle(bundle)

    def test_rejects_proposed_decision_with_terminal_payloads(self) -> None:
        bundle = _valid_bundle()
        decision = bundle["project_state"]["decisions"][0]
        decision["status"] = "proposed"
        decision["accepted_answer"]["summary"] = "Should not be here."

        with self.assertRaisesRegex(StateValidationError, "accepted_answer.summary"):
            validate_projection_bundle(bundle)

        bundle = _valid_bundle()
        decision = bundle["project_state"]["decisions"][0]
        decision["status"] = "proposed"
        decision["resolved_by_evidence"]["summary"] = "Should not be here."

        with self.assertRaisesRegex(StateValidationError, "resolved_by_evidence.summary"):
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

    def test_rejects_resolved_by_evidence_without_resolved_at(self) -> None:
        bundle = _valid_bundle()
        decision = bundle["project_state"]["decisions"][0]
        decision["status"] = "resolved-by-evidence"
        decision["accepted_answer"]["summary"] = "Found it."
        decision["accepted_answer"]["accepted_via"] = "evidence"
        decision["resolved_by_evidence"]["summary"] = "Found it."
        decision["resolved_by_evidence"]["source"] = "docs"

        with self.assertRaisesRegex(StateValidationError, "resolved_by_evidence.resolved_at"):
            validate_projection_bundle(bundle)

    def test_rejects_resolved_by_evidence_accepted_summary_mismatch(self) -> None:
        bundle = _valid_bundle()
        decision = bundle["project_state"]["decisions"][0]
        decision["status"] = "resolved-by-evidence"
        decision["accepted_answer"]["summary"] = "Different."
        decision["accepted_answer"]["accepted_via"] = "evidence"
        decision["resolved_by_evidence"]["summary"] = "Found it."
        decision["resolved_by_evidence"]["source"] = "docs"
        decision["resolved_by_evidence"]["resolved_at"] = "2026-04-23T12:00:00Z"

        with self.assertRaisesRegex(StateValidationError, "accepted_answer.summary"):
            validate_projection_bundle(bundle)

    def test_rejects_empty_project_fields(self) -> None:
        bundle = _valid_bundle()
        bundle["project_state"]["project"]["objective"] = " "

        with self.assertRaisesRegex(StateValidationError, "non-empty string"):
            validate_projection_bundle(bundle)

    def test_rejects_stale_close_summary_readiness(self) -> None:
        bundle = _valid_bundle()
        session = bundle["sessions"]["S-001"]
        session["close_summary"]["readiness"] = "blocked"

        with self.assertRaisesRegex(StateValidationError, "close_summary.readiness"):
            validate_projection_bundle(bundle)

    def test_rejects_closed_session_without_generated_close_summary(self) -> None:
        bundle = _valid_bundle()
        session = bundle["sessions"]["S-001"]
        session["session"]["lifecycle"]["status"] = "closed"
        session["session"]["lifecycle"]["closed_at"] = "2026-04-23T12:01:00Z"

        with self.assertRaisesRegex(StateValidationError, "close_summary.generated_at"):
            validate_projection_bundle(bundle)

    def test_rejects_closed_session_without_closed_at(self) -> None:
        bundle = _valid_bundle()
        session = bundle["sessions"]["S-001"]
        session["session"]["lifecycle"]["status"] = "closed"
        session["close_summary"]["generated_at"] = "2026-04-23T12:01:00Z"

        with self.assertRaisesRegex(StateValidationError, "lifecycle.closed_at"):
            validate_projection_bundle(bundle)

    def test_event_log_must_start_with_project_initialized(self) -> None:
        event = build_event(
            sequence=1,
            session_id="S-001",
            event_type="session_created",
            project_head_after=1,
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

    def test_event_log_rejects_invalid_event_timestamp(self) -> None:
        event = {
            "event_id": "E--000001",
            "tx_id": "T-test-1",
            "tx_index": 1,
            "tx_size": 1,
            "ts": "",
            "session_id": "SYSTEM",
            "event_type": "project_initialized",
            "payload": {
                "project": {
                    "name": "Demo",
                    "objective": "Test",
                    "current_milestone": "MVP",
                    "stop_rule": "Resolve blockers",
                }
            },
        }

        with self.assertRaisesRegex(EventValidationError, "event.ts"):
            validate_event_log([event])

        event["ts"] = "not-time"
        event["event_id"] = "E-nottime-000001"

        with self.assertRaisesRegex(EventValidationError, "event.ts"):
            validate_event_log([event])

    def test_event_log_rejects_duplicate_tx_index(self) -> None:
        first = build_event(
            sequence=1,
            session_id="SYSTEM",
            event_type="project_initialized",
            project_head_after=1,
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
        second = deepcopy(first)
        second["event_id"] = "E-test-2"

        with self.assertRaisesRegex(StateValidationError, "duplicate tx_index"):
            validate_event_log([first, second])

    def test_event_log_rejects_tx_size_mismatch(self) -> None:
        event = build_event(
            sequence=1,
            session_id="SYSTEM",
            event_type="project_initialized",
            project_head_after=1,
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
        event["tx_size"] = 2

        with self.assertRaisesRegex(StateValidationError, "tx_size does not match event count"):
            validate_event_log([event])

    def test_event_log_rejects_duplicate_project_initialized(self) -> None:
        first = build_event(
            sequence=1,
            session_id="SYSTEM",
            event_type="project_initialized",
            project_head_after=1,
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
            project_head_after=2,
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

    def test_event_log_rejects_session_scoped_event_with_system_session_id(self) -> None:
        initialized = _project_initialized(1)
        discovered = _decision_discovered(2, "SYSTEM", "D-001")

        with self.assertRaisesRegex(StateValidationError, "decision_discovered must not use SYSTEM"):
            validate_event_log([initialized, discovered])

    def test_event_log_rejects_other_session_scoped_events_with_system_session_id(self) -> None:
        cases = {
            "session_created": [_project_initialized(1), _session_created(2, "SYSTEM")],
            "session_resumed": [_project_initialized(1), _session_resumed(2, "SYSTEM")],
            "proposal_issued": [
                _project_initialized(1),
                _session_created(2, "S-001"),
                _decision_discovered(3, "S-001", "D-001"),
                _proposal_issued(4, "SYSTEM", "D-001"),
            ],
            "decision_deferred": [
                _project_initialized(1),
                _session_created(2, "S-001"),
                _decision_discovered(3, "S-001", "D-001"),
                _decision_deferred(4, "SYSTEM", "D-001"),
            ],
        }

        for event_type, events in cases.items():
            with self.subTest(event_type=event_type):
                with self.assertRaisesRegex(
                    StateValidationError, f"{event_type} must not use SYSTEM"
                ):
                    validate_event_log(events)

    def test_event_log_rejects_session_created_id_mismatch(self) -> None:
        initialized = _project_initialized(1)
        mismatched = build_event(
            sequence=2,
            session_id="S-outer",
            event_type="session_created",
            project_head_after=2,
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

    def test_event_log_accepts_session_linked_relationship(self) -> None:
        initialized = _project_initialized(1)
        parent = _session_created(2, "S-parent")
        child = _session_created(3, "S-child")
        linked = _session_linked(4, "S-parent", "S-child", "refines")

        validate_event_log([initialized, parent, child, linked])

    def test_event_log_rejects_session_linked_unknown_session(self) -> None:
        initialized = _project_initialized(1)
        child = _session_created(2, "S-child")
        linked = _session_linked(3, "S-parent", "S-child", "refines")

        with self.assertRaisesRegex(StateValidationError, "unknown parent session"):
            validate_event_log([initialized, child, linked])

    def test_event_log_rejects_session_linked_cycle(self) -> None:
        initialized = _project_initialized(1)
        first = _session_created(2, "S-first")
        second = _session_created(3, "S-second")
        first_link = _session_linked(4, "S-first", "S-second", "refines")
        cycle = _session_linked(5, "S-second", "S-first", "depends_on")

        with self.assertRaisesRegex(StateValidationError, "cycle"):
            validate_event_log([initialized, first, second, first_link, cycle])

    def test_event_log_allows_contradicts_cycle(self) -> None:
        initialized = _project_initialized(1)
        first = _session_created(2, "S-first")
        second = _session_created(3, "S-second")
        first_link = _session_linked(4, "S-first", "S-second", "refines")
        contradiction = _session_linked(5, "S-second", "S-first", "contradicts")

        validate_event_log([initialized, first, second, first_link, contradiction])

    def test_event_log_rejects_semantic_conflict_resolution_out_of_scope(self) -> None:
        initialized = _project_initialized(1)
        winner = _session_created(2, "S-winner")
        loser = _session_created(3, "S-loser")
        resolved = _semantic_conflict_resolved(4, "S-winner", ["S-loser"], ["S-winner"])

        with self.assertRaisesRegex(StateValidationError, "rejected_session_ids must be in scope"):
            validate_event_log([initialized, winner, loser, resolved])

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
            project_head_after=3,
            payload={"decision_id": "D-never", "reason": "Later."},
            timestamp="2026-04-23T12:02:00Z",
        )

        with self.assertRaisesRegex(StateValidationError, "undiscovered decision D-never"):
            validate_event_log([initialized, session, deferred])

        accepted = build_event(
            sequence=3,
            session_id="S-001",
            event_type="proposal_accepted",
            project_head_after=3,
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

    def test_event_log_rejects_proposal_response_before_issue(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        discovered = _decision_discovered(3, "S-001", "D-001")
        rejected = _proposal_rejected(4, "S-001", "D-001", "P-never")

        with self.assertRaisesRegex(StateValidationError, "unknown proposal P-never"):
            validate_event_log([initialized, session, discovered, rejected])

        accepted = _proposal_accepted(4, "S-001", "D-001", "P-never")

        with self.assertRaisesRegex(StateValidationError, "unknown proposal P-never"):
            validate_event_log([initialized, session, discovered, accepted])

    def test_event_log_rejects_proposal_response_mismatch(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        discovered = _decision_discovered(3, "S-001", "D-001")
        proposal = _proposal_issued(4, "S-001", "D-001", proposal_id="P-001")
        accepted = _proposal_accepted(5, "S-001", "D-001", "P-001", accepted_proposal_id="P-other")

        with self.assertRaisesRegex(StateValidationError, "accepted_answer.proposal_id"):
            validate_event_log([initialized, session, discovered, proposal, accepted])

        discovered_other = _decision_discovered(4, "S-001", "D-other")
        proposal = _proposal_issued(5, "S-001", "D-001", proposal_id="P-001")
        mismatched_target = _proposal_accepted(6, "S-001", "D-other", "P-001")

        with self.assertRaisesRegex(StateValidationError, "target_id"):
            validate_event_log([initialized, session, discovered, discovered_other, proposal, mismatched_target])

    def test_event_log_accepts_question_followed_by_matching_proposal(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        discovered = _decision_discovered(3, "S-001", "D-001")
        question = _question_asked(4, "S-001", "D-001")
        proposal = _proposal_issued(5, "S-001", "D-001", proposal_id="P-001")

        validate_event_log([initialized, session, discovered, question, proposal])

    def test_event_log_rejects_dangling_question_asked(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        discovered = _decision_discovered(3, "S-001", "D-001")
        question = _question_asked(4, "S-001", "D-001")

        with self.assertRaisesRegex(StateValidationError, "question_asked must be followed"):
            validate_event_log([initialized, session, discovered, question])

    def test_event_log_rejects_question_asked_not_followed_immediately_by_proposal(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        discovered = _decision_discovered(3, "S-001", "D-001")
        question = _question_asked(4, "S-001", "D-001")
        enriched = build_event(
            sequence=5,
            session_id="S-001",
            event_type="decision_enriched",
            project_head_after=5,
            payload={"decision_id": "D-001", "notes_append": ["not a proposal"]},
            timestamp="2026-04-23T12:04:00Z",
        )

        with self.assertRaisesRegex(StateValidationError, "question_asked must be followed"):
            validate_event_log([initialized, session, discovered, question, enriched])

    def test_event_log_rejects_question_proposal_mismatch(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        discovered = _decision_discovered(3, "S-001", "D-001")
        question = _question_asked(4, "S-001", "D-001", question_id="Q-other")
        proposal = _proposal_issued(5, "S-001", "D-001", proposal_id="P-001")

        with self.assertRaisesRegex(StateValidationError, "pending question_id"):
            validate_event_log([initialized, session, discovered, question, proposal])

    def test_event_log_rejects_proposal_issued_while_previous_proposal_active(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        first_decision = _decision_discovered(3, "S-001", "D-001")
        second_decision = _decision_discovered(4, "S-001", "D-002")
        first_question = _question_asked(5, "S-001", "D-001")
        first_proposal = _proposal_issued(6, "S-001", "D-001", proposal_id="P-001")
        second_question = _question_asked(7, "S-001", "D-002")
        second_proposal = _proposal_issued(8, "S-001", "D-002", proposal_id="P-002")

        with self.assertRaisesRegex(StateValidationError, "proposal_issued while proposal P-001 is still active"):
            validate_event_log(
                [
                    initialized,
                    session,
                    first_decision,
                    second_decision,
                    first_question,
                    first_proposal,
                    second_question,
                    second_proposal,
                ]
            )

    def test_event_log_rejects_defer_of_other_decision_while_proposal_active(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        first_decision = _decision_discovered(3, "S-001", "D-001")
        second_decision = _decision_discovered(4, "S-001", "D-002")
        proposal = _proposal_issued(5, "S-001", "D-001", proposal_id="P-001")
        deferred = _decision_deferred(6, "S-001", "D-002")

        with self.assertRaisesRegex(StateValidationError, "decision_deferred targets D-002"):
            validate_event_log([initialized, session, first_decision, second_decision, proposal, deferred])

    def test_event_log_rejects_evidence_resolution_of_other_decision_while_proposal_active(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        first_decision = _decision_discovered(3, "S-001", "D-001")
        second_decision = _decision_discovered(4, "S-001", "D-002")
        proposal = _proposal_issued(5, "S-001", "D-001", proposal_id="P-001")
        resolved = _decision_resolved_by_evidence(6, "S-001", "D-002")

        with self.assertRaisesRegex(StateValidationError, "decision_resolved_by_evidence targets D-002"):
            validate_event_log([initialized, session, first_decision, second_decision, proposal, resolved])

    def test_event_log_rejects_duplicate_proposal_id(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        discovered = _decision_discovered(3, "S-001", "D-001")
        first = _proposal_issued(4, "S-001", "D-001", proposal_id="P-001")
        second = _proposal_issued(5, "S-001", "D-001", proposal_id="P-001")

        with self.assertRaisesRegex(StateValidationError, "duplicate proposal_id"):
            validate_event_log([initialized, session, discovered, first, second])

    def test_event_log_rejects_closed_session_mutations(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        close_summary = _close_summary_generated(3, "S-001")
        closed = _session_closed(4, "S-001")
        discovered = _decision_discovered(5, "S-001", "D-late")

        with self.assertRaisesRegex(StateValidationError, "mutates closed session"):
            validate_event_log([initialized, session, close_summary, closed, discovered])

        classification = build_event(
            sequence=5,
            session_id="S-001",
            event_type="classification_updated",
            project_head_after=5,
            payload={
                "classification": {
                    "domain": "technical",
                    "abstraction_level": "architecture",
                    "assigned_tags": [],
                    "compatibility_tags": [],
                    "search_terms": [],
                    "source_refs": [],
                    "updated_at": "2026-04-23T12:03:00Z",
                }
            },
            timestamp="2026-04-23T12:03:00Z",
        )

        with self.assertRaisesRegex(StateValidationError, "mutates closed session"):
            validate_event_log([initialized, session, close_summary, closed, classification])

    def test_event_log_rejects_cross_session_decision_mutation(self) -> None:
        initialized = _project_initialized(1)
        session_a = _session_created(2, "S-A")
        session_b = _session_created(3, "S-B")
        discovered = _decision_discovered(4, "S-A", "D-001")
        proposal = _proposal_issued(5, "S-B", "D-001", proposal_id="P-001")

        with self.assertRaisesRegex(StateValidationError, "not bound to session S-B"):
            validate_event_log([initialized, session_a, session_b, discovered, proposal])

    def test_event_log_rejects_unbound_invalidating_decision(self) -> None:
        initialized = _project_initialized(1)
        session_a = _session_created(2, "S-A")
        session_b = _session_created(3, "S-B")
        old_decision = _decision_discovered(4, "S-A", "D-old")
        new_decision = _decision_discovered(5, "S-B", "D-new")
        invalidated = build_event(
            sequence=6,
            session_id="S-A",
            event_type="decision_invalidated",
            project_head_after=6,
            payload={
                "decision_id": "D-old",
                "invalidated_by_decision_id": "D-new",
                "reason": "Superseded.",
            },
            timestamp="2026-04-23T12:05:00Z",
        )

        with self.assertRaisesRegex(StateValidationError, "invalidating decision D-new not bound"):
            validate_event_log([initialized, session_a, session_b, old_decision, new_decision, invalidated])

    def test_event_log_rejects_non_final_invalidating_decision(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")

        unresolved = [
            initialized,
            session,
            _decision_discovered(3, "S-001", "D-old"),
            _decision_discovered(4, "S-001", "D-new"),
            _decision_invalidated(5, "S-001", "D-old", "D-new"),
        ]
        with self.assertRaisesRegex(StateValidationError, "decision_invalidated cannot target"):
            validate_event_log(unresolved)

        blocked = [
            initialized,
            session,
            _decision_discovered(3, "S-001", "D-old"),
            _decision_discovered(4, "S-001", "D-new", status="blocked"),
            _decision_invalidated(5, "S-001", "D-old", "D-new"),
        ]
        with self.assertRaisesRegex(StateValidationError, "decision_invalidated cannot target"):
            validate_event_log(blocked)

        deferred = [
            initialized,
            session,
            _decision_discovered(3, "S-001", "D-old"),
            _decision_discovered(4, "S-001", "D-new"),
            _decision_deferred(5, "S-001", "D-new"),
            _decision_invalidated(6, "S-001", "D-old", "D-new"),
        ]
        with self.assertRaisesRegex(StateValidationError, "decision_invalidated cannot target"):
            validate_event_log(deferred)

        rejected = [
            initialized,
            session,
            _decision_discovered(3, "S-001", "D-old"),
            _decision_discovered(4, "S-001", "D-new"),
            _proposal_issued(5, "S-001", "D-new", proposal_id="P-001"),
            _proposal_rejected(6, "S-001", "D-new", "P-001"),
            _decision_invalidated(7, "S-001", "D-old", "D-new"),
        ]
        with self.assertRaisesRegex(StateValidationError, "decision_invalidated cannot target"):
            validate_event_log(rejected)

    def test_event_log_allows_final_invalidating_decision(self) -> None:
        accepted = [
            _project_initialized(1),
            _session_created(2, "S-001"),
            _decision_discovered(3, "S-001", "D-old"),
            _decision_discovered(4, "S-001", "D-new"),
            _proposal_issued(5, "S-001", "D-new", proposal_id="P-001"),
            _proposal_accepted(6, "S-001", "D-new", "P-001"),
            _decision_invalidated(7, "S-001", "D-old", "D-new"),
        ]
        validate_event_log(accepted)

        resolved = [
            _project_initialized(1),
            _session_created(2, "S-001"),
            _decision_discovered(3, "S-001", "D-old"),
            _decision_discovered(4, "S-001", "D-new"),
            _decision_resolved_by_evidence(5, "S-001", "D-new"),
            _decision_invalidated(6, "S-001", "D-old", "D-new"),
        ]
        validate_event_log(resolved)

    def test_event_log_rejects_duplicate_decision_invalidated(self) -> None:
        events = [
            _project_initialized(1),
            _session_created(2, "S-001"),
            _decision_discovered(3, "S-001", "D-old"),
            _decision_discovered(4, "S-001", "D-new"),
            _proposal_issued(5, "S-001", "D-new", proposal_id="P-001"),
            _proposal_accepted(6, "S-001", "D-new", "P-001"),
            _decision_invalidated(7, "S-001", "D-old", "D-new"),
            _decision_invalidated(8, "S-001", "D-old", "D-new"),
        ]

        with self.assertRaisesRegex(StateValidationError, "already invalidated"):
            validate_event_log(events)

    def test_event_log_rejects_duplicate_proposal_accepted(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        discovered = _decision_discovered(3, "S-001", "D-001")
        proposal = _proposal_issued(4, "S-001", "D-001", proposal_id="P-001")
        first = _proposal_accepted(5, "S-001", "D-001", "P-001")
        second = _proposal_accepted(6, "S-001", "D-001", "P-001")

        with self.assertRaisesRegex(StateValidationError, "duplicate proposal_accepted"):
            validate_event_log([initialized, session, discovered, proposal, first, second])

    def test_event_log_rejects_proposal_response_after_session_resume(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        discovered = _decision_discovered(3, "S-001", "D-001")
        proposal = _proposal_issued(4, "S-001", "D-001", proposal_id="P-001")
        resumed = _session_resumed(5, "S-001")
        accepted = _proposal_accepted(6, "S-001", "D-001", "P-001")

        with self.assertRaisesRegex(StateValidationError, "inactive proposal P-001"):
            validate_event_log([initialized, session, discovered, proposal, resumed, accepted])

        rejected = _proposal_rejected(6, "S-001", "D-001", "P-001")

        with self.assertRaisesRegex(StateValidationError, "inactive proposal P-001"):
            validate_event_log([initialized, session, discovered, proposal, resumed, rejected])

    def test_event_log_rejects_duplicate_proposal_rejected(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        discovered = _decision_discovered(3, "S-001", "D-001")
        proposal = _proposal_issued(4, "S-001", "D-001", proposal_id="P-001")
        first = _proposal_rejected(5, "S-001", "D-001", "P-001")
        second = _proposal_rejected(6, "S-001", "D-001", "P-001")

        with self.assertRaisesRegex(StateValidationError, "duplicate proposal_rejected"):
            validate_event_log([initialized, session, discovered, proposal, first, second])

    def test_event_log_only_allows_immediate_rejected_proposal_acceptance(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        discovered = _decision_discovered(3, "S-001", "D-001")
        proposal = _proposal_issued(4, "S-001", "D-001", proposal_id="P-001")
        rejected = _proposal_rejected(5, "S-001", "D-001", "P-001")
        accepted = _proposal_accepted(6, "S-001", "D-001", "P-001")
        validate_event_log([initialized, session, discovered, proposal, rejected, accepted])

        enriched = build_event(
            sequence=6,
            session_id="S-001",
            event_type="decision_enriched",
            project_head_after=6,
            payload={"decision_id": "D-001", "notes_append": ["after rejection"]},
            timestamp="2026-04-23T12:05:00Z",
        )
        late_accept = _proposal_accepted(7, "S-001", "D-001", "P-001")
        with self.assertRaisesRegex(StateValidationError, "inactive proposal P-001"):
            validate_event_log([initialized, session, discovered, proposal, rejected, enriched, late_accept])

    def test_event_log_rejects_response_to_superseded_proposal(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        discovered = _decision_discovered(3, "S-001", "D-001")
        first_proposal = _proposal_issued(4, "S-001", "D-001", proposal_id="P-001")
        rejected = _proposal_rejected(5, "S-001", "D-001", "P-001")
        second_proposal = _proposal_issued(6, "S-001", "D-001", proposal_id="P-002")
        late_accept = _proposal_accepted(7, "S-001", "D-001", "P-001")

        with self.assertRaisesRegex(StateValidationError, "inactive proposal P-001"):
            validate_event_log(
                [
                    initialized,
                    session,
                    discovered,
                    first_proposal,
                    rejected,
                    second_proposal,
                    late_accept,
                ]
            )

    def test_event_log_rejects_invalid_decision_state_transitions(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        discovered = _decision_discovered(3, "S-001", "D-001")
        deferred = _decision_deferred(4, "S-001", "D-001")
        proposal = _proposal_issued(5, "S-001", "D-001", proposal_id="P-001")

        with self.assertRaisesRegex(StateValidationError, "proposal_issued cannot target"):
            validate_event_log([initialized, session, discovered, deferred, proposal])

        resolved = _decision_resolved_by_evidence(5, "S-001", "D-001")

        with self.assertRaisesRegex(StateValidationError, "decision_resolved_by_evidence cannot target"):
            validate_event_log([initialized, session, discovered, deferred, resolved])

        proposal = _proposal_issued(4, "S-001", "D-001", proposal_id="P-001")
        accepted = _proposal_accepted(5, "S-001", "D-001", "P-001")
        second_proposal = _proposal_issued(6, "S-001", "D-001", proposal_id="P-002")

        with self.assertRaisesRegex(StateValidationError, "proposal_issued cannot target"):
            validate_event_log([initialized, session, discovered, proposal, accepted, second_proposal])

        resolved = _decision_resolved_by_evidence(4, "S-001", "D-001")
        late_defer = _decision_deferred(5, "S-001", "D-001")

        with self.assertRaisesRegex(StateValidationError, "decision_deferred cannot target"):
            validate_event_log([initialized, session, discovered, resolved, late_defer])

    def test_event_log_rejects_session_closed_without_close_summary(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        closed = _session_closed(3, "S-001")

        with self.assertRaisesRegex(StateValidationError, "prior close_summary_generated"):
            validate_event_log([initialized, session, closed])

    def test_event_log_rejects_unclosed_close_summary_generated(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        close_summary = _close_summary_generated(3, "S-001")

        with self.assertRaisesRegex(StateValidationError, "close_summary_generated must be followed"):
            validate_event_log([initialized, session, close_summary])

    def test_event_log_rejects_interrupted_close_summary_close_pair(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        close_summary = _close_summary_generated(3, "S-001")
        resumed = _session_resumed(4, "S-001")
        closed = _session_closed(5, "S-001")

        with self.assertRaisesRegex(StateValidationError, "close_summary_generated must be followed"):
            validate_event_log([initialized, session, close_summary, resumed, closed])

    def test_event_log_accepts_close_summary_followed_by_session_closed(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        close_summary = _close_summary_generated(3, "S-001")
        closed = _session_closed(4, "S-001")

        validate_event_log([initialized, session, close_summary, closed])

    def test_event_log_rejects_plan_generated_for_active_session(self) -> None:
        initialized = _project_initialized(1)
        session = _session_created(2, "S-001")
        plan = _plan_generated(3, ["S-001"])

        with self.assertRaisesRegex(StateValidationError, "non-closed session"):
            validate_event_log([initialized, session, plan])


def _project_initialized(sequence: int) -> dict:
    return build_event(
        sequence=sequence,
        session_id="SYSTEM",
        event_type="project_initialized",
        project_head_after=sequence,
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
        project_head_after=sequence,
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


def _decision_discovered(sequence: int, session_id: str, decision_id: str, *, status: str | None = None) -> dict:
    decision = {"id": decision_id, "title": "Decision"}
    if status is not None:
        decision["status"] = status
    return build_event(
        sequence=sequence,
        session_id=session_id,
        event_type="decision_discovered",
        project_head_after=sequence,
        payload={"decision": decision},
        timestamp=f"2026-04-23T12:{sequence - 1:02d}:00Z",
    )


def _session_closed(sequence: int, session_id: str) -> dict:
    return build_event(
        sequence=sequence,
        session_id=session_id,
        event_type="session_closed",
        project_head_after=sequence,
        payload={"closed_at": f"2026-04-23T12:{sequence - 1:02d}:00Z"},
        timestamp=f"2026-04-23T12:{sequence - 1:02d}:00Z",
    )


def _session_resumed(sequence: int, session_id: str) -> dict:
    return build_event(
        sequence=sequence,
        session_id=session_id,
        event_type="session_resumed",
        project_head_after=sequence,
        payload={"resumed_at": f"2026-04-23T12:{sequence - 1:02d}:00Z"},
        timestamp=f"2026-04-23T12:{sequence - 1:02d}:00Z",
    )


def _session_linked(sequence: int, parent_session_id: str, child_session_id: str, relationship: str) -> dict:
    return build_event(
        sequence=sequence,
        session_id=child_session_id,
        event_type="session_linked",
        project_head_after=sequence,
        payload={
            "parent_session_id": parent_session_id,
            "child_session_id": child_session_id,
            "relationship": relationship,
            "reason": "Related sessions.",
            "linked_at": f"2026-04-23T12:{sequence - 1:02d}:00Z",
            "evidence_refs": [],
        },
        timestamp=f"2026-04-23T12:{sequence - 1:02d}:00Z",
    )


def _semantic_conflict_resolved(
    sequence: int,
    winning_session_id: str,
    rejected_session_ids: list[str],
    scope_session_ids: list[str],
) -> dict:
    return build_event(
        sequence=sequence,
        session_id=winning_session_id,
        event_type="semantic_conflict_resolved",
        project_head_after=sequence,
        payload={
            "conflict_id": "C-test",
            "winning_session_id": winning_session_id,
            "rejected_session_ids": rejected_session_ids,
            "scope": {"kind": "accepted_decision", "decision_id": "D-test", "session_ids": scope_session_ids},
            "reason": "Resolve conflict.",
            "resolved_at": f"2026-04-23T12:{sequence - 1:02d}:00Z",
        },
        timestamp=f"2026-04-23T12:{sequence - 1:02d}:00Z",
    )


def _close_summary_generated(sequence: int, session_id: str) -> dict:
    return build_event(
        sequence=sequence,
        session_id=session_id,
        event_type="close_summary_generated",
        project_head_after=sequence,
        payload={
            "close_summary": {
                "work_item_title": "Demo",
                "work_item_statement": "Demo",
                "goal": "Test",
                "readiness": "ready",
                "accepted_decisions": [],
                "deferred_decisions": [],
                "unresolved_blockers": [],
                "unresolved_risks": [],
                "candidate_workstreams": [],
                "candidate_action_slices": [],
                "evidence_refs": [],
                "generated_at": f"2026-04-23T12:{sequence - 1:02d}:00Z",
            }
        },
        timestamp=f"2026-04-23T12:{sequence - 1:02d}:00Z",
    )


def _plan_generated(sequence: int, session_ids: list[str]) -> dict:
    return build_event(
        sequence=sequence,
        session_id="SYSTEM",
        event_type="plan_generated",
        project_head_after=sequence,
        payload={"session_ids": session_ids, "status": "action-plan"},
        timestamp=f"2026-04-23T12:{sequence - 1:02d}:00Z",
    )


def _question_asked(
    sequence: int,
    session_id: str,
    decision_id: str,
    *,
    question_id: str = "Q-001",
    question: str = "Question?",
) -> dict:
    return build_event(
        sequence=sequence,
        session_id=session_id,
        event_type="question_asked",
        project_head_after=sequence,
        payload={
            "decision_id": decision_id,
            "question_id": question_id,
            "question": question,
        },
        timestamp=f"2026-04-23T12:{sequence - 1:02d}:00Z",
    )


def _proposal_issued(
    sequence: int, session_id: str, decision_id: str, *, proposal_id: str = "P-001"
) -> dict:
    return build_event(
        sequence=sequence,
        session_id=session_id,
        event_type="proposal_issued",
        project_head_after=sequence,
        payload={
            "proposal": {
                "proposal_id": proposal_id,
                "origin_session_id": session_id,
                "target_type": "decision",
                "target_id": decision_id,
                "recommendation_version": 1,
                "based_on_project_head": f"H-{sequence - 1}",
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


def _proposal_accepted(
    sequence: int,
    session_id: str,
    decision_id: str,
    proposal_id: str,
    *,
    accepted_proposal_id: str | None = None,
) -> dict:
    return build_event(
        sequence=sequence,
        session_id=session_id,
        event_type="proposal_accepted",
        project_head_after=sequence,
        payload={
            "proposal_id": proposal_id,
            "origin_session_id": session_id,
            "target_type": "decision",
            "target_id": decision_id,
            "accepted_answer": {
                "summary": "Use it.",
                "accepted_at": f"2026-04-23T12:{sequence - 1:02d}:00Z",
                "accepted_via": "explicit",
                "proposal_id": accepted_proposal_id if accepted_proposal_id is not None else proposal_id,
            },
        },
        timestamp=f"2026-04-23T12:{sequence - 1:02d}:00Z",
    )


def _decision_deferred(sequence: int, session_id: str, decision_id: str) -> dict:
    return build_event(
        sequence=sequence,
        session_id=session_id,
        event_type="decision_deferred",
        project_head_after=sequence,
        payload={"decision_id": decision_id, "reason": "Later."},
        timestamp=f"2026-04-23T12:{sequence - 1:02d}:00Z",
    )


def _decision_resolved_by_evidence(sequence: int, session_id: str, decision_id: str) -> dict:
    return build_event(
        sequence=sequence,
        session_id=session_id,
        event_type="decision_resolved_by_evidence",
        project_head_after=sequence,
        payload={
            "decision_id": decision_id,
            "source": "codebase",
            "summary": "Found it.",
            "evidence_refs": ["app/auth.py"],
        },
        timestamp=f"2026-04-23T12:{sequence - 1:02d}:00Z",
    )


def _decision_invalidated(
    sequence: int, session_id: str, decision_id: str, invalidated_by_decision_id: str
) -> dict:
    return build_event(
        sequence=sequence,
        session_id=session_id,
        event_type="decision_invalidated",
        project_head_after=sequence,
        payload={
            "decision_id": decision_id,
            "invalidated_by_decision_id": invalidated_by_decision_id,
            "reason": "Superseded.",
        },
        timestamp=f"2026-04-23T12:{sequence - 1:02d}:00Z",
    )


def _proposal_rejected(sequence: int, session_id: str, decision_id: str, proposal_id: str) -> dict:
    return build_event(
        sequence=sequence,
        session_id=session_id,
        event_type="proposal_rejected",
        project_head_after=sequence,
        payload={
            "proposal_id": proposal_id,
            "origin_session_id": session_id,
            "target_type": "decision",
            "target_id": decision_id,
            "reason": "No.",
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
    project_state["state"] = {
        "project_head": "H-1",
        "event_count": 1,
        "updated_at": now,
        "last_event_id": "E-test-1",
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
            "based_on_project_head": "H-1",
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
