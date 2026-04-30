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

    def test_accepts_resolved_by_evidence_and_invalidated_status_counts(self) -> None:
        payload = _valid_scenario()
        payload["evaluation"]["expected_decision_coverage"]["required_status_counts"] = [
            {"status": "resolved-by-evidence", "mode": "min", "count": 1},
            {"status": "invalidated", "mode": "exact", "count": 0},
        ]

        self.assertEqual([], list(self.validator.iter_errors(payload)))

    def test_rejects_legacy_answered_by_codebase_status_count(self) -> None:
        payload = _valid_scenario()
        payload["evaluation"]["expected_decision_coverage"]["required_status_counts"] = [
            {"status": "answered_by_codebase", "mode": "min", "count": 1}
        ]

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_old_status_count_object_shape(self) -> None:
        payload = _valid_scenario()
        coverage = payload["evaluation"]["expected_decision_coverage"]
        del coverage["required_status_counts"]
        coverage["required_statuses"] = {"answered_by_codebase": 1}

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_invalid_now_timestamp(self) -> None:
        payload = _valid_scenario()
        payload["evaluation"]["now"] = "not-a-date"

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

    def test_accepts_optional_safety_gate_expectations(self) -> None:
        payload = _valid_scenario()
        payload["evaluation"]["expected_safety_gates"] = {
            "required_rule_ids": ["validity_review"],
            "required_approval_thresholds": ["human_review"],
            "min_approval_required_count": 1,
            "required_insufficient_evidence_ids": ["data_dictionary"],
        }

        self.assertEqual([], list(self.validator.iter_errors(payload)))

    def test_accepts_optional_question_probe_expectations(self) -> None:
        payload = _valid_scenario()
        payload["evaluation"]["expected_questions"]["probe_session_ids"] = ["S-research-protocol"]
        payload["evaluation"]["expected_questions"]["advance_steps"] = 2

        self.assertEqual([], list(self.validator.iter_errors(payload)))

    def test_rejects_invalid_question_probe_session_id(self) -> None:
        payload = _valid_scenario()
        payload["evaluation"]["expected_questions"]["probe_session_ids"] = ["../S"]

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_accepts_optional_document_source_traceability_requirement(self) -> None:
        payload = _valid_scenario()
        payload["evaluation"]["expected_documents"][0]["require_source_traceability"] = True

        self.assertEqual([], list(self.validator.iter_errors(payload)))

    def test_rejects_invalid_document_source_traceability_requirement(self) -> None:
        payload = _valid_scenario()
        payload["evaluation"]["expected_documents"][0]["require_source_traceability"] = "yes"

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_accepts_optional_plan_and_revisit_expectations(self) -> None:
        payload = _valid_scenario()
        payload["evaluation"]["expected_plan_executability"] = {
            "readiness": "conditional",
            "min_implementation_ready_count": 1,
        }
        payload["evaluation"]["expected_revisit_quality"] = {"mode": "min", "count": 1}

        self.assertEqual([], list(self.validator.iter_errors(payload)))

    def test_rejects_invalid_plan_and_revisit_expectations(self) -> None:
        invalid_payloads = []
        payload = _valid_scenario()
        payload["evaluation"]["expected_plan_executability"] = {
            "readiness": "partial",
            "min_implementation_ready_count": 1,
        }
        invalid_payloads.append(payload)

        payload = _valid_scenario()
        payload["evaluation"]["expected_revisit_quality"] = {"mode": "at_least", "count": 1}
        invalid_payloads.append(payload)

        for payload in invalid_payloads:
            with self.subTest(payload=payload["evaluation"]):
                self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_invalid_safety_gate_approval_threshold(self) -> None:
        payload = _valid_scenario()
        payload["evaluation"]["expected_safety_gates"] = {
            "required_rule_ids": ["validity_review"],
            "required_approval_thresholds": ["manual_review"],
            "min_approval_required_count": 1,
            "required_insufficient_evidence_ids": ["data_dictionary"],
        }

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_invalid_insufficient_evidence_ids(self) -> None:
        payload = _valid_scenario()
        payload["evaluation"]["expected_safety_gates"] = {
            "required_rule_ids": ["validity_review"],
            "required_approval_thresholds": ["human_review"],
            "min_approval_required_count": 1,
            "required_insufficient_evidence_ids": ["../data_dictionary"],
        }

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
                "required_status_counts": [
                    {"status": "accepted", "mode": "exact", "count": 2},
                    {"status": "unresolved", "mode": "min", "count": 1},
                ],
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
                "required_risk_tiers": ["high"],
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
