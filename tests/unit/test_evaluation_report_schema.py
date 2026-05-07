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

    def test_accepts_valid_phase11_passed_report(self) -> None:
        self.assertEqual([], list(self.validator.iter_errors(_valid_report())))

    def test_accepts_failure_payload_with_expected_and_actual_values(self) -> None:
        payload = _valid_report()
        payload["status"] = "failed"
        payload["metrics"]["decision_coverage"]["passed"] = False
        payload["failures"] = [
            {
                "metric": "decision_coverage",
                "message": "Missing required domain decision types.",
                "path": "$.metrics.decision_coverage",
                "expected": ["clarify_goal"],
                "actual": [],
            }
        ]

        self.assertEqual([], list(self.validator.iter_errors(payload)))

    def test_rejects_legacy_report_version_and_metric_names(self) -> None:
        payload = _valid_report()
        payload["schema_version"] = 1
        payload["metrics"]["decision_completeness"] = payload["metrics"].pop("decision_coverage")

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_missing_required_metric(self) -> None:
        payload = _valid_report()
        del payload["metrics"]["conflict_precision"]

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
        payload["metrics"]["decision_coverage"]["passed"] = False

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_passed_report_with_failures(self) -> None:
        payload = _valid_report()
        payload["failures"] = [
            {
                "metric": "decision_coverage",
                "message": "Failure payload contradicts passed status.",
            }
        ]

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_failed_report_with_all_metrics_passing(self) -> None:
        payload = _valid_report()
        payload["status"] = "failed"
        payload["failures"] = [
            {
                "metric": "decision_coverage",
                "message": "Failure payload must correspond to a failed metric.",
            }
        ]

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_failed_report_without_failures(self) -> None:
        payload = _valid_report()
        payload["status"] = "failed"
        payload["metrics"]["decision_coverage"]["passed"] = False

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_invalid_generated_at_timestamp(self) -> None:
        payload = _valid_report()
        payload["generated_at"] = "not-a-date"

        self.assertTrue(list(self.validator.iter_errors(payload)))


def _valid_report() -> dict:
    return {
        "schema_version": 2,
        "scenario_id": "policy_interpretation",
        "status": "passed",
        "generated_at": "2026-04-29T00:00:00Z",
        "metrics": {
            "decision_coverage": {
                "required_count": 2,
                "covered_count": 2,
                "missing_ids": [],
                "passed": True,
            },
            "question_efficiency": {
                "asked_count": 0,
                "max_allowed": 1,
                "repeated_forbidden_decision_types": [],
                "passed": True,
            },
            "conflict_detection_recall": {
                "expected_count": 0,
                "actual_count": 0,
                "missing_conflict_ids": [],
                "missing_conflict_types": [],
                "passed": True,
            },
            "conflict_precision": {
                "expected_count": 0,
                "actual_count": 0,
                "unexpected_conflict_ids": [],
                "false_positive_count": 0,
                "passed": True,
            },
            "evidence_linkage_rate": {
                "required_count": 1,
                "covered_count": 1,
                "linked_evidence_count": 1,
                "total_evidence_count": 1,
                "linkage_rate": 1.0,
                "missing_ids": [],
                "invalid_source_refs": [],
                "passed": True,
            },
            "assumption_exposure": {
                "required_count": 1,
                "covered_count": 1,
                "assumption_count": 1,
                "stale_assumption_count": 0,
                "stale_evidence_count": 0,
                "verification_gap_count": 1,
                "due_revisit_count": 0,
                "missing_ids": [],
                "passed": True,
            },
            "risk_coverage": {
                "required_count": 1,
                "covered_count": 1,
                "missing_ids": [],
                "passed": True,
            },
            "action_executability": {
                "readiness": "conditional",
                "action_count": 3,
                "implementation_ready_count": 0,
                "blocker_count": 0,
                "unresolved_conflict_count": 0,
                "passed": True,
            },
            "document_validity": {
                "required_sections_present": True,
                "empty_required_sections": [],
                "missing_source_traceability": [],
                "passed": True,
            },
            "runtime_performance": {
                "total_seconds": 0.1,
                "load_runtime_seconds": 0.01,
                "event_count": 20,
                "session_count": 1,
                "object_count": 8,
                "decision_count": 2,
                "max_total_seconds": None,
                "max_load_runtime_seconds": None,
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
