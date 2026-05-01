#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT_STR = str(REPO_ROOT)
sys.path = [entry for entry in sys.path if entry != REPO_ROOT_STR]
sys.path.insert(0, REPO_ROOT_STR)

from tests.helpers.evaluation_assertions import validate_evaluation_report
from tests.helpers.evaluation_scenarios import (
    build_scenario_runtime,
    load_scenario,
    run_scenario_evaluation,
)
from tests.helpers.evaluation_snapshots import (
    collect_evaluation_snapshots,
    compare_evaluation_snapshots,
    write_expected_snapshots,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="run Phase 10 evaluation scenarios")
    parser.add_argument(
        "--scenarios",
        default=str(REPO_ROOT / "tests" / "scenarios"),
        help="directory containing */scenario.yaml or a single scenario.yaml file",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--update-snapshots",
        action="store_true",
        help="update expected_outputs snapshots for scenarios whose evaluation passes",
    )
    args = parser.parse_args(argv)

    try:
        scenario_paths = _discover_scenario_paths(Path(args.scenarios))
    except Exception as exc:
        if args.format == "json":
            _print_json(
                {
                    "status": "failed",
                    "scenario_count": 0,
                    "update_snapshots": args.update_snapshots,
                    "scenarios": [],
                }
            )
        else:
            print(f"scenario discovery failed: {exc}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        work_root = Path(tmp)
        results = [
            _run_one_scenario(path, work_root, update_snapshots=args.update_snapshots)
            for path in scenario_paths
        ]

    summary = {
        "status": "passed" if all(item["status"] == "passed" for item in results) else "failed",
        "scenario_count": len(results),
        "update_snapshots": args.update_snapshots,
        "scenarios": results,
    }
    if args.format == "json":
        _print_json(summary)
    else:
        _print_text(summary)
    return 0 if summary["status"] == "passed" else 1


def _discover_scenario_paths(path: Path) -> list[Path]:
    scenario_path = path.resolve()
    if scenario_path.is_file():
        if scenario_path.name != "scenario.yaml":
            raise ValueError(f"scenario file must be named scenario.yaml: {scenario_path}")
        return [scenario_path]
    if not scenario_path.is_dir():
        raise FileNotFoundError(f"scenario path does not exist: {scenario_path}")
    paths = sorted(scenario_path.glob("*/scenario.yaml"))
    if not paths:
        raise FileNotFoundError(f"no scenario.yaml files found under {scenario_path}")
    return paths


def _run_one_scenario(
    scenario_path: Path,
    work_root: Path,
    *,
    update_snapshots: bool,
) -> dict[str, Any]:
    scenario_id = scenario_path.parent.name
    failures: list[dict[str, Any]] = []
    snapshot_failures: list[str] = []
    snapshot_status = "failed"
    updated_snapshot_count = 0

    try:
        scenario = load_scenario(scenario_path)
        scenario_id = scenario.scenario_id
        runtime = build_scenario_runtime(scenario, work_root)
        report = run_scenario_evaluation(scenario, runtime)
        schema_errors = validate_evaluation_report(report)
        if schema_errors:
            failures.extend(
                {"metric": "report_schema", "message": error}
                for error in schema_errors
            )
        failures.extend(report.get("failures", []))
        evaluation_status = "passed" if report.get("status") == "passed" and not schema_errors else "failed"

        if update_snapshots and evaluation_status != "passed":
            snapshot_failures.append("snapshot update skipped because evaluation failed")
        else:
            snapshots = collect_evaluation_snapshots(scenario, runtime, report)
            if update_snapshots:
                changed = write_expected_snapshots(scenario, snapshots)
                updated_snapshot_count = len(changed)
                snapshot_status = "updated"
            else:
                snapshot_failures = compare_evaluation_snapshots(scenario, snapshots)
                snapshot_status = "passed" if not snapshot_failures else "failed"
    except Exception as exc:
        evaluation_status = "failed"
        failures.append({"metric": "runner", "message": str(exc)})

    status = "passed" if evaluation_status == "passed" and snapshot_status in {"passed", "updated"} else "failed"
    return {
        "scenario_id": scenario_id,
        "status": status,
        "evaluation_status": evaluation_status,
        "snapshot_status": snapshot_status,
        "failure_count": len(failures),
        "snapshot_mismatch_count": len(snapshot_failures),
        "updated_snapshot_count": updated_snapshot_count,
        "failures": failures,
        "snapshot_failures": snapshot_failures,
    }


def _print_json(summary: dict[str, Any]) -> None:
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


def _print_text(summary: dict[str, Any]) -> None:
    print(
        f"evaluation scenarios: {summary['status']} "
        f"({summary['scenario_count']} scenario(s), update_snapshots={summary['update_snapshots']})"
    )
    for result in summary["scenarios"]:
        print(
            f"- {result['scenario_id']}: {result['status']} "
            f"(evaluation={result['evaluation_status']}, snapshots={result['snapshot_status']})"
        )
        for failure in result["failures"]:
            print(f"  - {failure.get('metric')}: {failure.get('message')}")
        for failure in result["snapshot_failures"]:
            print("  - snapshot: " + failure.replace("\n", "\n    "))


if __name__ == "__main__":
    raise SystemExit(main())
