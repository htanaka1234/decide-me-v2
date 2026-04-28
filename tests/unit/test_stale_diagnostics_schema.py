from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

from decide_me.stale_detection import (
    detect_revisit_due,
    detect_stale_assumptions,
    detect_stale_evidence,
    detect_verification_gaps,
)
from tests.helpers.typed_metadata import (
    assumption_metadata,
    evidence_metadata,
    revisit_trigger_metadata,
)


NOW = "2026-04-28T12:00:00Z"
PAST = "2026-04-27T12:00:00Z"


class StaleDiagnosticsSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas" / "stale-diagnostics.schema.json"
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.schema)

    def test_accepts_all_stale_diagnostic_payloads(self) -> None:
        project_state = _valid_project_state()
        for diagnostic_type, payload in (
            ("stale_assumptions", detect_stale_assumptions(project_state, now=NOW)),
            ("stale_evidence", detect_stale_evidence(project_state, now=NOW)),
            ("verification_gaps", detect_verification_gaps(project_state, now=NOW)),
            ("revisit_due", detect_revisit_due(project_state, now=NOW)),
        ):
            with self.subTest(diagnostic_type=diagnostic_type):
                self.assertEqual([], list(self.validator.iter_errors(payload)))

    def test_rejects_invalid_enum_values(self) -> None:
        cases = (
            (detect_stale_assumptions(_valid_project_state(), now=NOW), ["items", 0, "confidence"], "certain"),
            (detect_stale_evidence(_valid_project_state(), now=NOW), ["items", 0, "freshness"], "fresh"),
            (detect_verification_gaps(_valid_project_state(), now=NOW), ["items", 0, "gap_severity"], "low"),
            (detect_revisit_due(_valid_project_state(), now=NOW), ["items", 0, "trigger_type"], "calendar"),
        )
        for payload, path, value in cases:
            with self.subTest(path=path):
                _set_path(payload, path, value)

                errors = list(self.validator.iter_errors(payload))

                self.assertTrue(errors)

    def test_rejects_null_list_items(self) -> None:
        cases = (
            (detect_stale_assumptions(_valid_project_state(), now=NOW), ["items", 0, "related_object_ids"], [None]),
            (detect_stale_evidence(_valid_project_state(), now=NOW), ["items", 0, "affected_decision_ids"], [None]),
            (detect_verification_gaps(_valid_project_state(), now=NOW), ["items", 0, "related_link_ids"], [None]),
            (detect_revisit_due(_valid_project_state(), now=NOW), ["items", 0, "target_object_ids"], [None]),
        )
        for payload, path, value in cases:
            with self.subTest(path=path):
                _set_path(payload, path, value)

                errors = list(self.validator.iter_errors(payload))

                self.assertTrue(errors)

    def test_rejects_missing_required_fields(self) -> None:
        stale_assumptions = detect_stale_assumptions(_valid_project_state(), now=NOW)
        stale_assumptions["items"][0].pop("stale_reason")

        stale_evidence = detect_stale_evidence(_valid_project_state(), now=NOW)
        stale_evidence["summary"].pop("affected_decision_count")

        verification_gaps = detect_verification_gaps(_valid_project_state(), now=NOW)
        verification_gaps["items"][0].pop("gap_reason")

        revisit_due = detect_revisit_due(_valid_project_state(), now=NOW)
        revisit_due.pop("as_of")

        for payload in (stale_assumptions, stale_evidence, verification_gaps, revisit_due):
            with self.subTest(diagnostic_type=payload.get("diagnostic_type")):
                errors = list(self.validator.iter_errors(payload))

                self.assertTrue(errors)


def _valid_project_state() -> dict:
    return {
        "schema_version": 12,
        "state": {
            "project_head": "H-stale",
            "event_count": 8,
            "updated_at": "2026-04-28T00:00:00Z",
            "last_event_id": "E-stale",
        },
        "objects": [
            _object("AS-001", "assumption", assumption_metadata(expires_at=PAST, invalidates_if_false=["D-001"])),
            _object("D-001", "decision", {}),
            _object("E-001", "evidence", evidence_metadata(valid_until=PAST)),
            _object("A-001", "action", {}),
            _object(
                "RT-001",
                "revisit_trigger",
                revisit_trigger_metadata(due_at=PAST, target_object_ids=["D-001"]),
            ),
        ],
        "links": [
            _link("L-AS-001-constrains-D-001", "AS-001", "constrains", "D-001"),
            _link("L-E-001-supports-D-001", "E-001", "supports", "D-001"),
            _link("L-RT-001-revisits-D-001", "RT-001", "revisits", "D-001"),
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
        "rationale": "Stale diagnostics schema fixture link.",
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
