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
]


class LinkSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas" / "link.schema.json"
        self.validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))

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
