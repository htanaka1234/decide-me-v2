from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator
from tests.helpers.schema_validation import OBJECT_SCHEMA_ID
from tests.helpers.typed_metadata import metadata_for_object_type


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
            "evidence",
            "revisit_triggers",
        )

        for field in legacy_fields:
            with self.subTest(field=field):
                payload = _valid_object("decision")
                payload[field] = []

                errors = list(self.validator.iter_errors(payload))

                self.assertTrue(errors)
                self.assertTrue(any(error.validator == "additionalProperties" for error in errors))

    def test_project_state_references_standalone_object_schema(self) -> None:
        self.assertEqual({"$ref": OBJECT_SCHEMA_ID}, self.project_schema["properties"]["objects"]["items"])

    def test_schema_declares_date_time_fields(self) -> None:
        self.assertEqual("date-time", self.schema["properties"]["created_at"]["format"])
        self.assertEqual("date-time", self.schema["properties"]["updated_at"]["format"])

    def test_accepts_typed_metadata_contracts(self) -> None:
        for object_type in ("evidence", "assumption", "risk", "verification", "revisit_trigger"):
            with self.subTest(object_type=object_type):
                self.validator.validate(_valid_object(object_type))

    def test_accepts_safety_approval_artifact_metadata(self) -> None:
        payload = _valid_object("artifact")
        payload["metadata"] = _safety_approval_metadata()

        self.validator.validate(payload)

    def test_rejects_missing_typed_metadata_fields(self) -> None:
        for object_type, field in (
            ("evidence", "source_ref"),
            ("assumption", "statement"),
            ("risk", "risk_tier"),
            ("verification", "method"),
            ("revisit_trigger", "target_object_ids"),
        ):
            with self.subTest(object_type=object_type, field=field):
                payload = _valid_object(object_type)
                payload["metadata"].pop(field)

                errors = list(self.validator.iter_errors(payload))

                self.assertTrue(errors)
                self.assertTrue(any(error.validator == "required" for error in errors))

    def test_rejects_invalid_typed_metadata_values(self) -> None:
        cases = (
            ("evidence", "confidence", "certain"),
            ("assumption", "invalidates_if_false", [None]),
            ("risk", "approval_threshold", "auto"),
            ("verification", "verified_at", 123),
            ("revisit_trigger", "trigger_type", "manual"),
            ("artifact", "gate_digest", "bad"),
        )
        for object_type, field, value in cases:
            with self.subTest(object_type=object_type, field=field):
                payload = _valid_object(object_type)
                if object_type == "artifact":
                    payload["metadata"] = _safety_approval_metadata()
                payload["metadata"][field] = value

                errors = list(self.validator.iter_errors(payload))

                self.assertTrue(errors)


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
        "metadata": _valid_metadata(object_type),
    }
    return deepcopy(payload)


def _valid_metadata(object_type: str) -> dict:
    return metadata_for_object_type(object_type)


def _safety_approval_metadata() -> dict:
    return {
        "artifact_type": "safety_gate_approval",
        "target_object_id": "D-001",
        "gate_digest": "SG-123456789abc",
        "approval_threshold": "human_review",
        "approved_by": "user",
        "approved_at": "2026-04-28T00:00:00Z",
        "reason": "Reviewed.",
        "expires_at": None,
    }


if __name__ == "__main__":
    unittest.main()
