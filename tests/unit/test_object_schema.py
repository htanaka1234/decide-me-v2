from __future__ import annotations

import json
import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


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
        schema_root = Path(__file__).resolve().parents[2] / "schemas"
        object_schema_path = schema_root / "object.schema.json"
        project_schema_path = schema_root / "project-state.schema.json"
        self.schema = json.loads(object_schema_path.read_text(encoding="utf-8"))
        self.project_schema = json.loads(project_schema_path.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.schema)
        self.format_validator = Draft202012Validator(self.schema, format_checker=_format_checker())

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

    def test_project_state_embedded_object_schema_matches_standalone_schema(self) -> None:
        embedded = self.project_schema["$defs"]["domain_object"]
        self.assertEqual(self.schema["required"], embedded["required"])
        self.assertEqual(self.schema["additionalProperties"], embedded["additionalProperties"])
        self.assertEqual(self.schema["properties"].keys(), embedded["properties"].keys())
        self.assertEqual(self.schema["properties"]["type"]["enum"], self.project_schema["$defs"]["object_type"]["enum"])
        self.assertEqual(self.schema["properties"]["source_event_ids"], self.project_schema["$defs"]["source_event_ids"])

        for field in ("id", "title", "body", "status", "created_at", "updated_at", "metadata"):
            self.assertEqual(self.schema["properties"][field], embedded["properties"][field])

    def test_format_checker_rejects_invalid_date_time_fields(self) -> None:
        payload = _valid_object("evidence")
        payload["created_at"] = "not-a-date-time"

        errors = list(self.format_validator.iter_errors(payload))

        self.assertTrue(errors)
        self.assertTrue(any(list(error.path) == ["created_at"] and error.validator == "format" for error in errors))

        payload = _valid_object("evidence")
        payload["updated_at"] = "not-a-date-time"

        errors = list(self.format_validator.iter_errors(payload))

        self.assertTrue(errors)
        self.assertTrue(any(list(error.path) == ["updated_at"] and error.validator == "format" for error in errors))


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


def _format_checker() -> FormatChecker:
    checker = FormatChecker()

    @checker.checks("date-time")
    def is_date_time(value: object) -> bool:
        if not isinstance(value, str):
            return True
        if "T" not in value:
            return False
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return True

    return checker


if __name__ == "__main__":
    unittest.main()
