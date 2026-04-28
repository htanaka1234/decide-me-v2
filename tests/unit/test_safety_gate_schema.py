from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

from decide_me.safety_gate import build_safety_gate_report, evaluate_safety_gate
from tests.helpers.typed_metadata import evidence_metadata, risk_metadata


class SafetyGateSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas" / "safety-gates.schema.json"
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.schema)

    def test_accepts_single_result_and_report(self) -> None:
        project_state = _valid_project_state()
        for payload in (
            evaluate_safety_gate(project_state, "D-001"),
            build_safety_gate_report(project_state),
        ):
            with self.subTest(keys=sorted(payload)):
                self.assertEqual([], list(self.validator.iter_errors(payload)))

    def test_rejects_invalid_enum_values(self) -> None:
        cases = (
            (evaluate_safety_gate(_valid_project_state(), "D-001"), ["gate_status"], "waiting"),
            (evaluate_safety_gate(_valid_project_state(), "D-001"), ["risk_tier"], "severe"),
            (evaluate_safety_gate(_valid_project_state(), "D-001"), ["evidence_coverage"], "partial"),
            (evaluate_safety_gate(_valid_project_state(), "D-001"), ["approval_threshold"], "auto"),
        )
        for payload, path, value in cases:
            with self.subTest(path=path):
                _set_path(payload, path, value)

                errors = list(self.validator.iter_errors(payload))

                self.assertTrue(errors)

    def test_rejects_null_list_items(self) -> None:
        cases = (
            (evaluate_safety_gate(_valid_project_state(), "D-001"), ["source_link_ids"], [None]),
            (evaluate_safety_gate(_valid_project_state(), "D-001"), ["blocking_reasons"], [None]),
            (evaluate_safety_gate(_valid_project_state(), "D-001"), ["evidence", 0, "source_ref"], None),
            (evaluate_safety_gate(_valid_project_state(), "D-001"), ["risks", 0, "mitigation_object_ids"], [None]),
        )
        for payload, path, value in cases:
            with self.subTest(path=path):
                _set_path(payload, path, value)

                errors = list(self.validator.iter_errors(payload))

                self.assertTrue(errors)

    def test_rejects_missing_required_fields(self) -> None:
        result = evaluate_safety_gate(_valid_project_state(), "D-001")
        result.pop("approval_required")

        report = build_safety_gate_report(_valid_project_state())
        report["summary"].pop("blocking_count")

        for payload in (result, report):
            with self.subTest(keys=sorted(payload)):
                errors = list(self.validator.iter_errors(payload))

                self.assertTrue(errors)


def _valid_project_state() -> dict:
    return {
        "schema_version": 12,
        "state": {
            "project_head": "H-safety",
            "event_count": 5,
            "updated_at": "2026-04-28T00:00:00Z",
            "last_event_id": "E-safety",
        },
        "objects": [
            _object("D-001", "decision", {}),
            _object("E-001", "evidence", evidence_metadata()),
            _object(
                "R-001",
                "risk",
                risk_metadata(
                    risk_tier="low",
                    approval_threshold="none",
                    mitigation_object_ids=["D-001"],
                ),
            ),
        ],
        "links": [
            _link("L-E-001-supports-D-001", "E-001", "supports", "D-001"),
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
        "rationale": "Safety gate schema fixture link.",
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
