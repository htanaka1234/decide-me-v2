from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, RefResolver


class ProjectStateSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_root = Path(__file__).resolve().parents[2] / "schemas"
        self.schema = json.loads((schema_root / "project-state.schema.json").read_text(encoding="utf-8"))
        self.object_schema = json.loads((schema_root / "object.schema.json").read_text(encoding="utf-8"))
        self.link_schema = json.loads((schema_root / "link.schema.json").read_text(encoding="utf-8"))
        resolver = RefResolver.from_schema(
            self.schema,
            store={
                self.object_schema["$id"]: self.object_schema,
                self.link_schema["$id"]: self.link_schema,
            },
        )
        self.validator = Draft202012Validator(self.schema, resolver=resolver)

    def test_project_state_uses_v11_object_link_shape(self) -> None:
        self.assertEqual(11, self.schema["properties"]["schema_version"]["const"])
        self.assertEqual(
            [
                "schema_version",
                "project",
                "state",
                "protocol",
                "sessions_index",
                "counts",
                "objects",
                "links",
                "graph",
            ],
            self.schema["required"],
        )
        for legacy_key in ("decisions", "default_bundles", "session_graph", "proposals", "action_slices"):
            self.assertNotIn(legacy_key, self.schema["properties"])
        self.assertEqual({"$ref": "object.schema.json"}, self.schema["properties"]["objects"]["items"])
        self.assertEqual({"$ref": "link.schema.json"}, self.schema["properties"]["links"]["items"])

    def test_accepts_valid_object_link_state(self) -> None:
        self.validator.validate(_valid_project_state())

    def test_accepts_uninitialized_skeleton(self) -> None:
        payload = _valid_project_state()
        payload["project"] = {
            "name": None,
            "objective": None,
            "current_milestone": None,
            "stop_rule": None,
        }
        payload["state"] = {
            "project_head": None,
            "event_count": 0,
            "updated_at": None,
            "last_event_id": None,
        }
        payload["counts"] = {
            "object_total": 0,
            "link_total": 0,
            "by_type": {},
            "by_status": {},
            "by_relation": {},
        }
        payload["objects"] = []
        payload["links"] = []

        self.validator.validate(payload)

    def test_rejects_null_persisted_fields_after_events(self) -> None:
        for section, key in (
            ("project", "name"),
            ("project", "objective"),
            ("project", "current_milestone"),
            ("project", "stop_rule"),
            ("state", "project_head"),
            ("state", "updated_at"),
            ("state", "last_event_id"),
        ):
            payload = _valid_project_state()
            payload[section][key] = None

            errors = list(self.validator.iter_errors(payload))

            self.assertTrue(errors)
            self.assertTrue(any(list(error.path) == [section, key] for error in errors))

    def test_rejects_stale_count_shape(self) -> None:
        payload = _valid_project_state()
        payload["counts"] = {"p0_now_open": 0, "p1_now_open": 0, "p2_open": 0, "blocked": 0, "deferred": 0}

        errors = list(self.validator.iter_errors(payload))

        self.assertTrue(errors)


def _valid_project_state() -> dict:
    return deepcopy(
        {
            "schema_version": 11,
            "project": {
                "name": "Demo",
                "objective": "Plan the milestone.",
                "current_milestone": "Phase 5",
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
                "object_total": 1,
                "link_total": 0,
                "by_type": {"objective": 1},
                "by_status": {"active": 1},
                "by_relation": {},
            },
            "objects": [
                {
                    "id": "O-objective",
                    "type": "objective",
                    "title": "Phase 5",
                    "body": "Plan the milestone.",
                    "status": "active",
                    "created_at": "2026-04-23T12:00:00Z",
                    "updated_at": None,
                    "source_event_ids": ["E-001"],
                    "metadata": {},
                }
            ],
            "links": [],
            "graph": {
                "nodes": [],
                "edges": [],
                "resolved_conflicts": [],
                "inferred_candidates": [],
            },
        }
    )


if __name__ == "__main__":
    unittest.main()
