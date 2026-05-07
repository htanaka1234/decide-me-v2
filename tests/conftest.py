from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any


EVALUATION_TEST_FILES = {
    "tests/integration/test_evaluate_scenarios_script.py",
    "tests/integration/test_evaluation_scenarios.py",
    "tests/unit/test_evaluation_report_schema.py",
    "tests/unit/test_evaluation_scenario_fixtures.py",
    "tests/unit/test_evaluation_scenario_helpers.py",
    "tests/unit/test_evaluation_scenario_schema.py",
    "tests/unit/test_snapshot_normalization.py",
}

PHASE_GATE_TEST_FILES = {
    "tests/unit/test_evaluation_report_schema.py",
    "tests/unit/test_evaluation_scenario_schema.py",
    "tests/unit/test_pytest_markers.py",
    "tests/integration/test_evaluation_scenarios.py",
    "tests/integration/test_phase5_object_runtime_gate.py",
    "tests/integration/test_phase6_distribution_artifact.py",
    "tests/integration/test_phase6_graph_impact_gate.py",
    "tests/integration/test_phase7_distribution_artifact.py",
    "tests/integration/test_phase8_distribution_artifact.py",
    "tests/integration/test_phase9_distribution_artifact.py",
    "tests/integration/test_phase11_distribution_artifact.py",
    "tests/integration/test_phase11_gate_script.py",
}

SLOW_TEST_FILES = {
    "tests/integration/test_evaluate_scenarios_script.py",
    "tests/integration/test_evaluation_scenarios.py",
}


def markers_for_test_path(path: str | Path) -> tuple[str, ...]:
    normalized = _normalize_path(path)
    markers: set[str] = set()
    if normalized.startswith("tests/unit/"):
        markers.add("unit")
    elif normalized.startswith("tests/integration/"):
        markers.add("integration")
    elif normalized.startswith("tests/smoke/"):
        markers.update({"phase_gate", "smoke"})

    if normalized in EVALUATION_TEST_FILES:
        markers.add("evaluation")
    if normalized in PHASE_GATE_TEST_FILES:
        markers.add("phase_gate")
    if normalized in SLOW_TEST_FILES:
        markers.add("slow")
    return tuple(sorted(markers))


def pytest_collection_modifyitems(config: Any, items: list[Any]) -> None:
    root = Path(str(config.rootpath))
    for item in items:
        item_path = Path(str(item.path))
        try:
            relative = item_path.relative_to(root)
        except ValueError:
            relative = item_path
        for marker in markers_for_test_path(relative):
            item.add_marker(marker)


def _normalize_path(path: str | Path) -> str:
    return PurePosixPath(str(path).replace("\\", "/")).as_posix()
