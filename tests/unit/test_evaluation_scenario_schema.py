from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


class EvaluationScenarioSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas" / "evaluation-scenario.schema.json"
        self.validator = Draft202012Validator(
            json.loads(schema_path.read_text(encoding="utf-8")),
            format_checker=_format_checker(),
        )

    def test_accepts_valid_phase11_scenario_orchestrator(self) -> None:
        self.assertEqual([], list(self.validator.iter_errors(_valid_scenario())))

    def test_requires_schema_version_2(self) -> None:
        payload = _valid_scenario()
        payload["schema_version"] = 1

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_legacy_inline_expectations(self) -> None:
        payload = _valid_scenario()
        payload["evaluation"]["expected_decision_coverage"] = {
            "required_domain_decision_types": ["clarify_goal"],
            "required_status_counts": [],
        }

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_unknown_top_level_field(self) -> None:
        payload = _valid_scenario()
        payload["runner"] = "scripts/evaluate_scenarios.py"

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_invalid_now_timestamp(self) -> None:
        payload = _valid_scenario()
        payload["evaluation"]["now"] = "not-a-date"

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_unsafe_seed_event_paths(self) -> None:
        unsafe_paths = [
            "../events.jsonl",
            "fixtures/../events.jsonl",
            "/tmp/events.jsonl",
            "C:/events.jsonl",
            "events.json",
        ]
        for seed_events in unsafe_paths:
            with self.subTest(seed_events=seed_events):
                payload = _valid_scenario()
                payload["sessions"][0]["seed_events"] = seed_events

                self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_accepts_nested_relative_seed_event_path(self) -> None:
        payload = _valid_scenario()
        payload["sessions"][0]["seed_events"] = "fixtures/research/events.jsonl"

        self.assertEqual([], list(self.validator.iter_errors(payload)))

    def test_rejects_invalid_question_probe_session_id_shape_in_sessions(self) -> None:
        payload = _valid_scenario()
        payload["sessions"][0]["session_id"] = "../S"

        self.assertTrue(list(self.validator.iter_errors(payload)))


def _valid_scenario() -> dict:
    return {
        "schema_version": 2,
        "scenario_id": "policy_interpretation",
        "label": "Policy interpretation benchmark",
        "domain_pack": "generic",
        "project": {
            "name": "Demo policy project",
            "objective": "Interpret an internal policy exception.",
            "current_milestone": "Policy interpretation recommendation",
        },
        "sessions": [
            {
                "session_id": "S-policy-interpretation",
                "context": "Interpret whether a limited exception can proceed.",
                "seed_events": "events.jsonl",
                "close": True,
            }
        ],
        "evaluation": {
            "now": "2026-04-29T00:00:00Z",
        },
    }


def _format_checker() -> FormatChecker:
    checker = FormatChecker()

    @checker.checks("date-time", raises=ValueError)
    def is_date_time(value: object) -> bool:
        if not isinstance(value, str):
            return True
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        datetime.fromisoformat(normalized)
        return True

    return checker


if __name__ == "__main__":
    unittest.main()
