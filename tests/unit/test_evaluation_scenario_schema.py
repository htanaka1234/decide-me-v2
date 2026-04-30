from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


class EvaluationScenarioSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas" / "evaluation-scenario.schema.json"
        self.validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))

    def test_accepts_valid_research_protocol_scenario(self) -> None:
        self.assertEqual([], list(self.validator.iter_errors(_valid_scenario())))

    def test_rejects_unknown_top_level_field(self) -> None:
        payload = _valid_scenario()
        payload["runner"] = "scripts/evaluate_scenarios.py"

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_missing_required_evaluation_section(self) -> None:
        payload = _valid_scenario()
        del payload["evaluation"]["expected_documents"]

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_invalid_document_format(self) -> None:
        payload = _valid_scenario()
        payload["evaluation"]["expected_documents"][0]["format"] = "html"

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

    def test_rejects_unknown_nested_expectation_field(self) -> None:
        payload = _valid_scenario()
        payload["evaluation"]["expected_risks"]["runner_hint"] = "ignore"

        self.assertTrue(list(self.validator.iter_errors(payload)))


def _valid_scenario() -> dict:
    return {
        "schema_version": 1,
        "scenario_id": "research_protocol",
        "label": "Research protocol planning",
        "domain_pack": "research",
        "project": {
            "name": "Demo research project",
            "objective": "Define a reproducible retrospective cohort study.",
            "current_milestone": "Protocol decisions",
        },
        "sessions": [
            {
                "session_id": "S-research-protocol",
                "context": "Plan a retrospective cohort study with endpoint and missing-data decisions.",
                "seed_events": "events.jsonl",
                "close": True,
            }
        ],
        "evaluation": {
            "now": "2026-04-29T00:00:00Z",
            "expected_decision_coverage": {
                "required_domain_decision_types": [
                    "research_question",
                    "cohort_definition",
                    "primary_endpoint",
                    "missing_data_strategy",
                ],
                "required_statuses": {
                    "accepted": 2,
                    "unresolved_min": 1,
                },
            },
            "expected_questions": {
                "max_questions": 4,
                "forbidden_repeated_decision_types": ["primary_endpoint"],
            },
            "expected_evidence_coverage": {
                "min_supporting_evidence": 2,
                "required_evidence_requirement_ids": [
                    "protocol_or_project_brief",
                    "data_dictionary",
                ],
            },
            "expected_risks": {
                "required_domain_risk_types": ["unclear_endpoint", "missing_data"],
                "min_high_or_critical_risks": 1,
            },
            "expected_conflicts": {
                "count": 0,
            },
            "expected_documents": [
                {
                    "type": "research-plan",
                    "format": "json",
                    "required_sections": [
                        "objective",
                        "research-question-decision-targets",
                        "evidence-base",
                        "analysis-verification-plan",
                        "risks-and-mitigations",
                        "source-traceability",
                    ],
                }
            ],
        },
    }


if __name__ == "__main__":
    unittest.main()
