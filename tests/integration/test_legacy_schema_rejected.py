from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, RefResolver


class LegacySchemaRejectedTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_root = Path(__file__).resolve().parents[2] / "schemas"
        schema_path = schema_root / "project-state.schema.json"
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        object_schema = json.loads((schema_root / "object.schema.json").read_text(encoding="utf-8"))
        link_schema = json.loads((schema_root / "link.schema.json").read_text(encoding="utf-8"))
        resolver = RefResolver.from_schema(
            self.schema,
            store={
                object_schema["$id"]: object_schema,
                link_schema["$id"]: link_schema,
            },
        )
        self.validator = Draft202012Validator(self.schema, resolver=resolver)

    def test_accepts_domain_neutral_project_state_shape(self) -> None:
        self.validator.validate(_valid_project_state())

    def test_rejects_legacy_top_level_decisions_projection(self) -> None:
        payload = _valid_project_state()
        payload["decisions"] = []

        errors = list(self.validator.iter_errors(payload))

        self.assertTrue(errors)
        self.assertTrue(any(error.validator == "additionalProperties" for error in errors))

    def test_rejects_legacy_top_level_proposals_projection(self) -> None:
        payload = _valid_project_state()
        payload["proposals"] = []

        errors = list(self.validator.iter_errors(payload))

        self.assertTrue(errors)
        self.assertTrue(any(error.validator == "additionalProperties" for error in errors))

    def test_rejects_legacy_top_level_action_slices_projection(self) -> None:
        payload = _valid_project_state()
        payload["action_slices"] = []

        errors = list(self.validator.iter_errors(payload))

        self.assertTrue(errors)
        self.assertTrue(any(error.validator == "additionalProperties" for error in errors))

    def test_rejects_legacy_state_without_objects_and_links(self) -> None:
        payload = _valid_project_state()
        payload.pop("objects")
        payload.pop("links")
        payload["decisions"] = []

        errors = list(self.validator.iter_errors(payload))

        self.assertTrue(errors)
        self.assertTrue(any(error.validator == "required" for error in errors))
        self.assertTrue(any(error.validator == "additionalProperties" for error in errors))

    def test_schema_declares_project_updated_at_date_time_format(self) -> None:
        self.assertEqual("date-time", self.schema["properties"]["state"]["properties"]["updated_at"]["format"])


def _valid_project_state() -> dict:
    payload = {
        "schema_version": 12,
        "project": {
            "name": "Demo",
            "objective": "Plan the current milestone.",
            "current_milestone": "Phase 5",
            "stop_rule": "Resolve P0 blockers.",
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
            "by_type": {
                "objective": 1,
                "evidence": 1,
            },
            "by_status": {
                "active": 2,
            },
            "by_relation": {
                "supports": 1,
            },
        },
        "objects": [
            {
                "id": "O-objective",
                "type": "objective",
                "title": "Milestone objective",
                "body": "Plan Phase 5.",
                "status": "active",
                "created_at": "2026-04-23T12:00:00Z",
                "updated_at": None,
                "source_event_ids": ["E-001"],
                "metadata": {},
            },
            {
                "id": "O-evidence",
                "type": "evidence",
                "title": "Existing tests",
                "body": "The schema tests define the target contract.",
                "status": "active",
                "created_at": "2026-04-23T12:00:00Z",
                "updated_at": None,
                "source_event_ids": ["E-001"],
                "metadata": {
                    "source": "tests",
                },
            },
        ],
        "links": [
            {
                "id": "L-evidence-supports-objective",
                "source_object_id": "O-evidence",
                "relation": "supports",
                "target_object_id": "O-objective",
                "rationale": "Tests describe accepted behavior.",
                "created_at": "2026-04-23T12:00:00Z",
                "source_event_ids": ["E-001"],
            }
        ],
        "graph": {
            "nodes": [
                {
                    "object_id": "O-objective",
                    "object_type": "objective",
                    "layer": "purpose",
                    "status": "active",
                    "title": "Milestone objective",
                    "is_frontier": False,
                    "is_invalidated": False,
                },
                {
                    "object_id": "O-evidence",
                    "object_type": "evidence",
                    "layer": "verification",
                    "status": "active",
                    "title": "Existing tests",
                    "is_frontier": False,
                    "is_invalidated": False,
                },
            ],
            "edges": [
                {
                    "link_id": "L-evidence-supports-objective",
                    "source_object_id": "O-evidence",
                    "relation": "supports",
                    "target_object_id": "O-objective",
                    "source_layer": "verification",
                    "target_layer": "purpose",
                }
            ],
            "resolved_conflicts": [],
            "inferred_candidates": [],
        },
    }
    return deepcopy(payload)


if __name__ == "__main__":
    unittest.main()
