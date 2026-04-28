from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

from decide_me.registers import build_assumption_register, build_evidence_register, build_risk_register
from tests.helpers.typed_metadata import assumption_metadata, evidence_metadata, risk_metadata


class RegisterSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas" / "registers.schema.json"
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.schema)

    def test_accepts_register_payloads(self) -> None:
        project_state = _valid_project_state()
        for register_type, payload in (
            ("evidence", build_evidence_register(project_state)),
            ("assumption", build_assumption_register(project_state)),
            ("risk", build_risk_register(project_state)),
        ):
            with self.subTest(register_type=register_type):
                errors = list(self.validator.iter_errors(payload))
                self.assertEqual([], errors)

    def test_rejects_invalid_register_type(self) -> None:
        payload = build_evidence_register(_valid_project_state())
        payload["register_type"] = "verification"

        errors = list(self.validator.iter_errors(payload))

        self.assertTrue(errors)
        self.assertTrue(any(list(error.path) == ["register_type"] for error in errors))

    def test_rejects_invalid_typed_values(self) -> None:
        cases = (
            (build_evidence_register(_valid_project_state()), ["items", 0, "confidence"], "certain"),
            (build_evidence_register(_valid_project_state()), ["items", 0, "freshness"], "fresh"),
            (build_risk_register(_valid_project_state()), ["items", 0, "risk_tier"], "severe"),
            (build_risk_register(_valid_project_state()), ["items", 0, "approval_threshold"], "auto"),
        )
        for payload, path, value in cases:
            with self.subTest(path=path):
                _set_path(payload, path, value)

                errors = list(self.validator.iter_errors(payload))

                self.assertTrue(errors)

    def test_rejects_invalid_list_and_null_shapes(self) -> None:
        cases = (
            (build_evidence_register(_valid_project_state()), ["items", 0, "related_link_ids"], [None]),
            (build_assumption_register(_valid_project_state()), ["items", 0, "invalidates_if_false"], "D-001"),
            (build_evidence_register(_valid_project_state()), ["items", 0, "source_ref"], None),
            (build_risk_register(_valid_project_state()), ["items", 0, "mitigation_object_ids"], [None]),
        )
        for payload, path, value in cases:
            with self.subTest(path=path):
                _set_path(payload, path, value)

                errors = list(self.validator.iter_errors(payload))

                self.assertTrue(errors)


def _valid_project_state() -> dict:
    return {
        "schema_version": 12,
        "state": {
            "project_head": "H-register",
            "event_count": 8,
            "updated_at": "2026-04-28T00:00:00Z",
            "last_event_id": "E-register",
        },
        "objects": [
            _object("E-001", "evidence", evidence_metadata()),
            _object(
                "AS-001",
                "assumption",
                assumption_metadata(invalidates_if_false=["D-001"], owner="platform"),
            ),
            _object("RISK-001", "risk", risk_metadata(mitigation_object_ids=["A-001"])),
            _object("D-001", "decision", {}),
            _object("A-001", "action", {}),
        ],
        "links": [
            _link("L-E-001-supports-D-001", "E-001", "supports", "D-001"),
            _link("L-AS-001-constrains-D-001", "AS-001", "constrains", "D-001"),
            _link("L-A-001-mitigates-RISK-001", "A-001", "mitigates", "RISK-001"),
        ],
    }


def _object(object_id: str, object_type: str, metadata: dict) -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": object_id,
        "body": None,
        "status": "active",
        "created_at": "2026-04-28T00:00:00Z",
        "updated_at": None,
        "source_event_ids": ["E-create"],
        "metadata": deepcopy(metadata),
    }


def _link(link_id: str, source: str, relation: str, target: str) -> dict:
    return {
        "id": link_id,
        "source_object_id": source,
        "relation": relation,
        "target_object_id": target,
        "rationale": "Register schema fixture link.",
        "created_at": "2026-04-28T00:00:00Z",
        "source_event_ids": ["E-link"],
    }


def _set_path(payload: dict, path: list[str | int], value: object) -> None:
    current: object = payload
    for part in path[:-1]:
        current = current[part]  # type: ignore[index]
    current[path[-1]] = value  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
