from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator


OBJECT_TYPES = [
    "objective",
    "constraint",
    "criterion",
    "option",
    "proposal",
    "decision",
    "assumption",
    "evidence",
    "risk",
    "action",
    "verification",
    "revisit_trigger",
    "artifact",
]


class ObjectSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas" / "object.schema.json"
        self.validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))

    def test_accepts_all_domain_object_types(self) -> None:
        for object_type in OBJECT_TYPES:
            with self.subTest(object_type=object_type):
                self.validator.validate(_valid_object(object_type))

    def test_rejects_unknown_object_type(self) -> None:
        payload = _valid_object("decision")
        payload["type"] = "workstream"

        errors = list(self.validator.iter_errors(payload))

        self.assertTrue(errors)
        self.assertTrue(any(list(error.path) == ["type"] for error in errors))

    def test_rejects_legacy_relation_style_object_fields(self) -> None:
        legacy_fields = (
            "depends_on",
            "blocked_by",
            "options",
            "recommendation",
            "accepted_answer",
            "evidence_refs",
            "revisit_triggers",
        )

        for field in legacy_fields:
            with self.subTest(field=field):
                payload = _valid_object("decision")
                payload[field] = []

                errors = list(self.validator.iter_errors(payload))

                self.assertTrue(errors)
                self.assertTrue(any(error.validator == "additionalProperties" for error in errors))


def _valid_object(object_type: str) -> dict:
    payload = {
        "id": f"O-{object_type}",
        "type": object_type,
        "title": object_type.replace("_", " ").title(),
        "body": "Projected from the effective event stream.",
        "status": "active",
        "created_at": "2026-04-23T12:00:00Z",
        "updated_at": None,
        "source_event_ids": ["E-001"],
        "metadata": {},
    }
    return deepcopy(payload)


if __name__ == "__main__":
    unittest.main()
