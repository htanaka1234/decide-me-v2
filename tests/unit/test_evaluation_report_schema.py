from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


class EvaluationReportSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas" / "evaluation-report.schema.json"
        self.validator = Draft202012Validator(
            json.loads(schema_path.read_text(encoding="utf-8")),
            format_checker=_format_checker(),
        )

    def test_accepts_valid_passed_report(self) -> None:
        self.assertEqual([], list(self.validator.iter_errors(_valid_report())))

    def test_accepts_failure_payload_with_expected_and_actual_values(self) -> None:
        payload = _valid_report()
        payload["status"] = "failed"
        payload["metrics"]["decision_completeness"]["passed"] = False
        payload["failures"] = [
            {
                "metric": "decision_completeness",
                "message": "Missing required domain decision types.",
                "path": "$.metrics.decision_completeness",
                "expected": ["primary_endpoint"],
                "actual": [],
            }
        ]

        self.assertEqual([], list(self.validator.iter_errors(payload)))

    def test_rejects_invalid_status(self) -> None:
        payload = _valid_report()
        payload["status"] = "partial"

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_missing_required_metric(self) -> None:
        payload = _valid_report()
        del payload["metrics"]["conflict_detection"]

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_unknown_metric_field(self) -> None:
        payload = _valid_report()
        payload["metrics"]["question_efficiency"]["elapsed_seconds"] = 12

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_unknown_failure_metric(self) -> None:
        payload = _valid_report()
        payload["status"] = "failed"
        payload["failures"] = [
            {
                "metric": "snapshot",
                "message": "Unexpected snapshot diff.",
            }
        ]

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_passed_report_with_failed_metric(self) -> None:
        payload = _valid_report()
        payload["metrics"]["decision_completeness"]["passed"] = False

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_passed_report_with_failures(self) -> None:
        payload = _valid_report()
        payload["failures"] = [
            {
                "metric": "decision_completeness",
                "message": "Failure payload contradicts passed status.",
            }
        ]

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_failed_report_with_all_metrics_passing(self) -> None:
        payload = _valid_report()
        payload["status"] = "failed"
        payload["failures"] = [
            {
                "metric": "decision_completeness",
                "message": "Failure payload must correspond to a failed metric.",
            }
        ]

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_failed_report_without_failures(self) -> None:
        payload = _valid_report()
        payload["status"] = "failed"
        payload["metrics"]["decision_completeness"]["passed"] = False

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_invalid_generated_at_timestamp(self) -> None:
        payload = _valid_report()
        payload["generated_at"] = "not-a-date"

        self.assertTrue(list(self.validator.iter_errors(payload)))


def _valid_report() -> dict:
    return {
        "schema_version": 1,
        "scenario_id": "research_protocol",
        "status": "passed",
        "generated_at": "2026-04-29T00:00:00Z",
        "metrics": {
            "question_efficiency": {
                "asked_count": 3,
                "max_allowed": 4,
                "passed": True,
            },
            "decision_completeness": {
                "required_count": 4,
                "covered_count": 4,
                "passed": True,
            },
            "evidence_coverage": {
                "required_count": 2,
                "covered_count": 2,
                "passed": True,
            },
            "risk_coverage": {
                "required_count": 2,
                "covered_count": 2,
                "passed": True,
            },
            "conflict_detection": {
                "expected_count": 0,
                "actual_count": 0,
                "passed": True,
            },
            "plan_executability": {
                "readiness": "conditional",
                "action_count": 2,
                "implementation_ready_count": 1,
                "blocker_count": 0,
                "passed": True,
            },
            "document_readability": {
                "required_sections_present": True,
                "empty_required_sections": [],
                "missing_source_traceability": [],
                "passed": True,
            },
            "revisit_quality": {
                "stale_assumption_count": 0,
                "stale_evidence_count": 0,
                "verification_gap_count": 1,
                "due_revisit_count": 1,
                "passed": True,
            },
        },
        "failures": [],
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
