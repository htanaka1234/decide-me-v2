from __future__ import annotations

from copy import deepcopy
import unittest

from decide_me.events import build_event as runtime_build_event
from decide_me.projections import apply_events_to_bundle, project_heads_by_event_id, rebuild_projections


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


def close_summary_with_slices(
    *,
    title: str = "Shared slice",
    statement: str = "Shared slice",
    decisions: list[tuple[str, str, str]],
    workstream_name: str = "technical-workstream",
) -> dict:
    accepted = [
        {
            "id": decision_id,
            "title": decision_title,
            "kind": "choice",
            "domain": "technical",
            "priority": "P0",
            "status": "accepted",
            "resolvable_by": "human",
            "evidence_source": None,
            "evidence_refs": [evidence_ref],
            "accepted_answer": f"Accept {decision_title}.",
        }
        for decision_id, decision_title, evidence_ref in decisions
    ]
    action_slices = [
        {
            "decision_id": decision_id,
            "name": decision_title,
            "summary": f"Implement {decision_title}.",
            "responsibility": "technical",
            "priority": "P0",
            "status": "accepted",
            "kind": "choice",
            "resolvable_by": "human",
            "reversibility": "reversible",
            "implementation_ready": True,
            "evidence_backed": True,
            "evidence_source": None,
            "evidence_refs": [evidence_ref],
            "next_step": f"Drive {decision_title} to completion.",
        }
        for decision_id, decision_title, evidence_ref in decisions
    ]
    decision_ids = [decision_id for decision_id, _, _ in decisions]
    return {
        "work_item_title": title,
        "work_item_statement": statement,
        "goal": "Test conflict suppression",
        "readiness": "ready",
        "accepted_decisions": accepted,
        "deferred_decisions": [],
        "unresolved_blockers": [],
        "unresolved_risks": [],
        "candidate_workstreams": [
            {
                "name": workstream_name,
                "summary": "Advance technical decisions for the current milestone.",
                "scope": decision_ids,
                "accepted_count": len(decision_ids),
                "implementation_ready_scope": decision_ids,
            }
        ],
        "candidate_action_slices": action_slices,
        "evidence_refs": [evidence_ref for _, _, evidence_ref in decisions],
        "generated_at": "2026-04-23T12:04:00Z",
    }


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
                payload={"decision": {"id": "D-001", "requirement_id": "R-001", "title": "Auth mode"}},
                timestamp="2026-04-23T12:02:00Z",
            ),
        ]

        first = rebuild_projections(events)
        second = rebuild_projections(events)
        self.assertEqual(first, second)

    def test_discovered_requirement_id_projects_and_incremental_matches_full_rebuild(self) -> None:
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
                payload={"decision": {"id": "D-001", "requirement_id": "R-001", "title": "Auth mode"}},
                timestamp="2026-04-23T12:02:00Z",
            ),
        ]

        full = rebuild_projections(events)
        incremental = apply_events_to_bundle(deepcopy(rebuild_projections(events[:2])), events[2:])

        decisions = {
            item["id"]: item
            for item in full["project_state"]["objects"]
            if item["type"] == "decision"
        }
        self.assertEqual("R-001", decisions["D-001"]["metadata"]["requirement_id"])
        self.assertNotIn("decisions", full["project_state"])
        self.assertEqual(full, incremental)

    def test_incremental_apply_matches_full_rebuild_project_head(self) -> None:
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
                payload={"decision": {"id": "D-001", "requirement_id": "R-001", "title": "Auth mode"}},
                timestamp="2026-04-23T12:02:00Z",
            ),
        ]

        full = rebuild_projections(events)
        incremental = apply_events_to_bundle(deepcopy(rebuild_projections(events[:2])), events[2:])

        self.assertEqual(full["project_state"]["state"], incremental["project_state"]["state"])
        self.assertEqual(full, incremental)

    def test_proposal_projection_preserves_explicit_based_on_project_head(self) -> None:
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
                payload={"decision": {"id": "D-001", "requirement_id": "R-001", "title": "Auth mode"}},
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
                        "based_on_project_head": "H-explicit",
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
        ]

        full = rebuild_projections(events)
        incremental = apply_events_to_bundle(deepcopy(rebuild_projections(events[:3])), events[3:])

        self.assertEqual(
            "H-explicit",
            full["sessions"]["S-001"]["working_state"]["active_proposal"]["based_on_project_head"],
        )
        self.assertEqual(
            "H-explicit",
            next(
                item
                for item in full["project_state"]["objects"]
                if item["id"] == "P-001"
            )["metadata"]["based_on_project_head"],
        )
        self.assertEqual(full, incremental)

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
                payload={"decision": {"id": "D-001", "requirement_id": "R-001", "title": "Auth mode"}},
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

    def test_options_are_linked_to_decision(self) -> None:
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
                payload={
                    "decision": {
                        "id": "D-001",
                        "requirement_id": "R-001",
                        "title": "Auth mode",
                        "options": [{"summary": "Magic links", "rationale": "Small surface."}],
                    }
                },
                timestamp="2026-04-23T12:02:00Z",
            ),
        ]

        bundle = rebuild_projections(events)
        option_ids = {
            item["id"]
            for item in bundle["project_state"]["objects"]
            if item["type"] == "option"
        }
        addresses_links = [
            link
            for link in bundle["project_state"]["links"]
            if link["relation"] == "addresses" and link["target_object_id"] == "D-001"
        ]

        self.assertEqual(1, len(option_ids))
        self.assertEqual(option_ids, {link["source_object_id"] for link in addresses_links})

    def test_missing_dependency_endpoint_link_is_skipped(self) -> None:
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
                payload={
                    "decision": {
                        "id": "D-001",
                        "requirement_id": "R-001",
                        "title": "Auth mode",
                        "depends_on": ["D-missing"],
                    }
                },
                timestamp="2026-04-23T12:02:00Z",
            ),
        ]

        bundle = rebuild_projections(events)

        self.assertEqual([], bundle["project_state"]["links"])

    def test_semantic_conflict_resolution_suppresses_losing_action_slice_context(self) -> None:
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
                session_id="S-winner",
                event_type="session_created",
                project_version_after=2,
                payload={
                    "session": {
                        "id": "S-winner",
                        "started_at": "2026-04-23T12:01:00Z",
                        "last_seen_at": "2026-04-23T12:01:00Z",
                        "bound_context_hint": "Winner thread",
                    }
                },
                timestamp="2026-04-23T12:01:00Z",
            ),
            build_event(
                sequence=3,
                session_id="S-loser",
                event_type="session_created",
                project_version_after=3,
                payload={
                    "session": {
                        "id": "S-loser",
                        "started_at": "2026-04-23T12:02:00Z",
                        "last_seen_at": "2026-04-23T12:02:00Z",
                        "bound_context_hint": "Loser thread",
                    }
                },
                timestamp="2026-04-23T12:02:00Z",
            ),
            build_event(
                sequence=4,
                session_id="S-loser",
                event_type="close_summary_generated",
                project_version_after=4,
                payload={
                    "close_summary": close_summary_with_slices(
                        title="Shared slice",
                        statement="Shared slice",
                        decisions=[
                            ("D-shared", "Shared slice", "ref:shared"),
                            ("D-extra", "Extra slice", "ref:extra"),
                        ],
                    )
                },
                timestamp="2026-04-23T12:04:00Z",
            ),
            build_event(
                sequence=5,
                session_id="S-loser",
                event_type="session_closed",
                project_version_after=5,
                payload={"closed_at": "2026-04-23T12:05:00Z"},
                timestamp="2026-04-23T12:05:00Z",
            ),
            build_event(
                sequence=6,
                session_id="S-winner",
                event_type="semantic_conflict_resolved",
                project_version_after=6,
                payload={
                    "conflict_id": "C-action",
                    "winning_session_id": "S-winner",
                    "rejected_session_ids": ["S-loser"],
                    "scope": {
                        "kind": "action_slice",
                        "name": "Shared slice",
                        "session_ids": ["S-loser", "S-winner"],
                    },
                    "reason": "Keep winner slice.",
                    "resolved_at": "2026-04-23T12:06:00Z",
                },
                timestamp="2026-04-23T12:06:00Z",
            ),
        ]

        bundle = rebuild_projections(events)
        loser = bundle["sessions"]["S-loser"]
        close_summary = loser["close_summary"]

        self.assertEqual("Loser thread", close_summary["work_item_title"])
        self.assertNotEqual("Shared slice", loser["summary"]["latest_summary"])
        self.assertEqual(["D-extra"], [item["id"] for item in close_summary["accepted_decisions"]])
        self.assertEqual(["Extra slice"], [item["name"] for item in close_summary["candidate_action_slices"]])
        self.assertEqual(["D-extra"], close_summary["candidate_workstreams"][0]["scope"])
        self.assertEqual(["D-extra"], close_summary["candidate_workstreams"][0]["implementation_ready_scope"])
        self.assertEqual(["ref:extra"], close_summary["evidence_refs"])
        self.assertEqual("ready", close_summary["readiness"])

        self.assertNotIn("session_graph", bundle["project_state"])
        self.assertEqual(
            ["C-action"],
            [item["conflict_id"] for item in bundle["project_state"]["graph"]["resolved_conflicts"]],
        )

    def test_semantic_conflict_resolution_suppresses_losing_workstream_only(self) -> None:
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
                session_id="S-winner",
                event_type="session_created",
                project_version_after=2,
                payload={
                    "session": {
                        "id": "S-winner",
                        "started_at": "2026-04-23T12:01:00Z",
                        "last_seen_at": "2026-04-23T12:01:00Z",
                        "bound_context_hint": "Winner thread",
                    }
                },
                timestamp="2026-04-23T12:01:00Z",
            ),
            build_event(
                sequence=3,
                session_id="S-loser",
                event_type="session_created",
                project_version_after=3,
                payload={
                    "session": {
                        "id": "S-loser",
                        "started_at": "2026-04-23T12:02:00Z",
                        "last_seen_at": "2026-04-23T12:02:00Z",
                        "bound_context_hint": "Loser thread",
                    }
                },
                timestamp="2026-04-23T12:02:00Z",
            ),
            build_event(
                sequence=4,
                session_id="S-loser",
                event_type="close_summary_generated",
                project_version_after=4,
                payload={
                    "close_summary": close_summary_with_slices(
                        decisions=[("D-shared", "Shared slice", "ref:shared")],
                        workstream_name="ops-workstream",
                    )
                },
                timestamp="2026-04-23T12:04:00Z",
            ),
            build_event(
                sequence=5,
                session_id="S-loser",
                event_type="session_closed",
                project_version_after=5,
                payload={"closed_at": "2026-04-23T12:05:00Z"},
                timestamp="2026-04-23T12:05:00Z",
            ),
            build_event(
                sequence=6,
                session_id="S-winner",
                event_type="semantic_conflict_resolved",
                project_version_after=6,
                payload={
                    "conflict_id": "C-workstream",
                    "winning_session_id": "S-winner",
                    "rejected_session_ids": ["S-loser"],
                    "scope": {
                        "kind": "workstream",
                        "name": "ops-workstream",
                        "session_ids": ["S-loser", "S-winner"],
                    },
                    "reason": "Keep winner workstream.",
                    "resolved_at": "2026-04-23T12:06:00Z",
                },
                timestamp="2026-04-23T12:06:00Z",
            ),
        ]

        bundle = rebuild_projections(events)
        close_summary = bundle["sessions"]["S-loser"]["close_summary"]

        self.assertEqual(["D-shared"], [item["id"] for item in close_summary["accepted_decisions"]])
        self.assertEqual(["Shared slice"], [item["name"] for item in close_summary["candidate_action_slices"]])
        self.assertEqual([], close_summary["candidate_workstreams"])
        self.assertNotIn("session_graph", bundle["project_state"])
        self.assertEqual(
            ["C-workstream"],
            [item["conflict_id"] for item in bundle["project_state"]["graph"]["resolved_conflicts"]],
        )


if __name__ == "__main__":
    unittest.main()
