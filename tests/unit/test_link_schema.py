from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator


LINK_RELATIONS = [
    "depends_on",
    "supports",
    "challenges",
    "recommends",
    "accepts",
    "addresses",
    "verifies",
    "revisits",
    "supersedes",
    "blocked_by",
    "constrains",
    "enables",
    "requires",
    "invalidates",
    "mitigates",
    "derived_from",
]


class LinkSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_root = Path(__file__).resolve().parents[2] / "schemas"
        link_schema_path = schema_root / "link.schema.json"
        project_schema_path = schema_root / "project-state.schema.json"
        self.schema = json.loads(link_schema_path.read_text(encoding="utf-8"))
        self.project_schema = json.loads(project_schema_path.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.schema)

    def test_accepts_all_link_relations(self) -> None:
        for relation in LINK_RELATIONS:
            with self.subTest(relation=relation):
                self.validator.validate(_valid_link(relation))

    def test_rejects_unknown_link_relation(self) -> None:
        payload = _valid_link("supports")
        payload["relation"] = "duplicates"

        errors = list(self.validator.iter_errors(payload))

        self.assertTrue(errors)
        self.assertTrue(any(list(error.path) == ["relation"] for error in errors))

    def test_rejects_unknown_top_level_fields(self) -> None:
        payload = _valid_link("supports")
        payload["metadata"] = {}

        errors = list(self.validator.iter_errors(payload))

        self.assertTrue(errors)
        self.assertTrue(any(error.validator == "additionalProperties" for error in errors))

    def test_project_state_references_standalone_link_schema(self) -> None:
        self.assertEqual({"$ref": "link.schema.json"}, self.project_schema["properties"]["links"]["items"])

    def test_project_state_relation_enum_matches_link_schema(self) -> None:
        self.assertEqual(
            set(self.schema["properties"]["relation"]["enum"]),
            set(self.project_schema["$defs"]["link_relation"]["enum"]),
        )

    def test_link_envelope_uses_explicit_object_endpoint_names(self) -> None:
        self.assertEqual(
            [
                "id",
                "source_object_id",
                "relation",
                "target_object_id",
                "rationale",
                "created_at",
                "source_event_ids",
            ],
            self.schema["required"],
        )
        for alias in ("source_id", "rel", "target_id"):
            self.assertNotIn(alias, self.schema["properties"])

    def test_schema_declares_created_at_date_time_format(self) -> None:
        self.assertEqual("date-time", self.schema["properties"]["created_at"]["format"])


def _valid_link(relation: str) -> dict:
    payload = {
        "id": f"L-{relation}",
        "source_object_id": "O-source",
        "relation": relation,
        "target_object_id": "O-target",
        "rationale": "Projected from an event-derived relation.",
        "created_at": "2026-04-23T12:00:00Z",
        "source_event_ids": ["E-001"],
    }
    return deepcopy(payload)


if __name__ == "__main__":
    unittest.main()
