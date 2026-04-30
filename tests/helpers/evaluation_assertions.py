from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_SCHEMA_PATH = REPO_ROOT / "schemas" / "evaluation-report.schema.json"


def validate_evaluation_report(report: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(
        json.loads(REPORT_SCHEMA_PATH.read_text(encoding="utf-8")),
        format_checker=_format_checker(),
    )
    return [_format_schema_error(error) for error in sorted(validator.iter_errors(report), key=str)]


def assert_evaluation_report_matches_expectations(
    testcase: Any,
    scenario: Any,
    report: dict[str, Any],
) -> None:
    schema_errors = validate_evaluation_report(report)
    if schema_errors:
        testcase.fail("evaluation report schema validation failed:\n" + "\n".join(schema_errors))

    if report.get("status") == "passed":
        return

    scenario_id = getattr(scenario, "scenario_id", report.get("scenario_id", "unknown"))
    lines = [f"evaluation scenario {scenario_id} failed:"]
    for failure in report.get("failures", []):
        message = f"- {failure.get('metric')}: {failure.get('message')}"
        if "path" in failure:
            message += f" ({failure['path']})"
        if "expected" in failure or "actual" in failure:
            message += f" expected={failure.get('expected')!r} actual={failure.get('actual')!r}"
        lines.append(message)
    testcase.fail("\n".join(lines))


def _format_schema_error(error: Any) -> str:
    path = "$"
    for part in error.absolute_path:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}"
    return f"{path}: {error.message}"


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
