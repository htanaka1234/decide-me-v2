from __future__ import annotations

import unittest
from copy import deepcopy

from decide_me.events import build_event as runtime_build_event
from decide_me.projections import default_project_state, rebuild_projections
from decide_me.validate import StateValidationError, validate_project_state, validate_projection_bundle


class ProjectStateValidationTests(unittest.TestCase):
    def test_default_state_validates_as_uninitialized_skeleton(self) -> None:
        validate_project_state(default_project_state())

    def test_empty_rebuild_project_state_validates_as_skeleton(self) -> None:
        bundle = rebuild_projections([])

        validate_project_state(bundle["project_state"])

    def test_accepts_object_link_project_state(self) -> None:
        validate_project_state(_valid_project_state())

    def test_rejects_top_level_decisions(self) -> None:
        payload = _valid_project_state()
        payload["decisions"] = []

        with self.assertRaisesRegex(StateValidationError, "top-level decisions"):
            validate_project_state(payload)

    def test_rejects_duplicate_object_ids(self) -> None:
        payload = _valid_project_state()
        payload["objects"].append(deepcopy(payload["objects"][0]))
        payload["counts"]["object_total"] += 1
        payload["counts"]["by_type"]["decision"] = 2
        payload["counts"]["by_status"]["unresolved"] = 2

        with self.assertRaisesRegex(StateValidationError, "duplicate object id"):
            validate_project_state(payload)

    def test_rejects_missing_link_source_endpoint(self) -> None:
        payload = _valid_project_state()
        payload["links"][0]["source_object_id"] = "D-missing"

        with self.assertRaisesRegex(StateValidationError, "source_object_id"):
            validate_project_state(payload)

    def test_rejects_missing_link_target_endpoint(self) -> None:
        payload = _valid_project_state()
        payload["links"][0]["target_object_id"] = "D-missing"

        with self.assertRaisesRegex(StateValidationError, "target_object_id"):
            validate_project_state(payload)

    def test_rejects_invalid_relation(self) -> None:
        payload = _valid_project_state()
        payload["links"][0]["relation"] = "duplicates"

        with self.assertRaisesRegex(StateValidationError, "relation"):
            validate_project_state(payload)

    def test_rejects_stale_counts(self) -> None:
        payload = _valid_project_state()
        payload["counts"]["link_total"] = 0

        with self.assertRaisesRegex(StateValidationError, "counts"):
            validate_project_state(payload)

    def test_rejects_null_project_fields_after_events(self) -> None:
        payload = _valid_project_state()
        payload["project"]["name"] = None

        with self.assertRaisesRegex(StateValidationError, "project_state.project.name"):
            validate_project_state(payload)

    def test_projection_bundle_rejects_stale_sessions_index(self) -> None:
        bundle = rebuild_projections(
            [
                _event(
                    sequence=1,
                    session_id="SYSTEM",
                    event_type="project_initialized",
                    payload={
                        "project": {
                            "name": "Demo",
                            "objective": "Plan Phase 5-2.",
                            "current_milestone": "Phase 5-2",
                            "stop_rule": "Resolve blockers.",
                        }
                    },
                    timestamp="2026-04-23T12:00:00Z",
                ),
                _event(
                    sequence=2,
                    session_id="S-001",
                    event_type="session_created",
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
            ]
        )
        validate_projection_bundle(bundle)
        bundle["project_state"]["sessions_index"]["S-001"]["last_seen_at"] = "2026-04-23T12:30:00Z"

        with self.assertRaisesRegex(StateValidationError, "sessions_index does not match sessions"):
            validate_projection_bundle(bundle)


def _valid_project_state() -> dict:
    return deepcopy(
        {
            "schema_version": 10,
            "project": {
                "name": "Demo",
                "objective": "Plan Phase 5-2.",
                "current_milestone": "Phase 5-2",
                "stop_rule": "Resolve blockers.",
            },
            "state": {
                "project_head": "H-001",
                "event_count": 1,
                "updated_at": "2026-04-23T12:00:00Z",
                "last_event_id": "E-001",
            },
            "protocol": {
                "plain_ok_scope": "same-session-active-proposal-only",
                "proposal_expiry_rules": ["project-head-changed", "session-boundary"],
                "close_policy": "generate-close-summary-on-close",
            },
            "sessions_index": {},
            "counts": {
                "object_total": 2,
                "link_total": 1,
                "by_type": {"decision": 1, "proposal": 1},
                "by_status": {"unresolved": 1, "active": 1},
                "by_relation": {"recommends": 1},
            },
            "objects": [
                {
                    "id": "D-001",
                    "type": "decision",
                    "title": "Auth mode",
                    "body": None,
                    "status": "unresolved",
                    "created_at": "2026-04-23T12:00:00Z",
                    "updated_at": None,
                    "source_event_ids": ["E-001"],
                    "metadata": {
                        "requirement_id": "R-001",
                        "kind": "choice",
                        "domain": "technical",
                        "priority": "P0",
                        "frontier": "now",
                        "resolvable_by": "human",
                        "reversibility": "reversible",
                    },
                },
                {
                    "id": "P-001",
                    "type": "proposal",
                    "title": "Use magic links.",
                    "body": "Smallest auth surface.",
                    "status": "active",
                    "created_at": "2026-04-23T12:00:00Z",
                    "updated_at": None,
                    "source_event_ids": ["E-001"],
                    "metadata": {},
                },
            ],
            "links": [
                {
                    "id": "L-P-001-recommends-D-001",
                    "source_object_id": "P-001",
                    "relation": "recommends",
                    "target_object_id": "D-001",
                    "rationale": "Smallest auth surface.",
                    "created_at": "2026-04-23T12:00:00Z",
                    "source_event_ids": ["E-001"],
                }
            ],
            "graph": {
                "nodes": [],
                "edges": [],
                "resolved_conflicts": [],
                "inferred_candidates": [],
            },
        }
    )


def _event(
    *,
    sequence: int,
    session_id: str,
    event_type: str,
    payload: dict,
    timestamp: str,
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
        project_head=f"H-{sequence}",
    )


if __name__ == "__main__":
    unittest.main()
