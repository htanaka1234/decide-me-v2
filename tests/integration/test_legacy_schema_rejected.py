from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator


class LegacySchemaRejectedTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas" / "project-state.schema.json"
        self.validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))

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


def _valid_project_state() -> dict:
    payload = {
        "schema_version": 10,
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
    }
    return deepcopy(payload)


if __name__ == "__main__":
    unittest.main()

