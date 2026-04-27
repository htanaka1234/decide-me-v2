from __future__ import annotations

import unittest
from copy import deepcopy

from decide_me.validate import StateValidationError, validate_project_state


class ProjectStateValidationTests(unittest.TestCase):
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
        }
    )


if __name__ == "__main__":
    unittest.main()
