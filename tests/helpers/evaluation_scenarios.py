from __future__ import annotations

import hashlib
import json
import shutil
import time
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from decide_me.documents.compiler import compile_document
from decide_me.domains import domain_pack_digest, load_domain_registry
from decide_me.events import build_event
from decide_me.interview import advance_session
from decide_me.lifecycle import close_session
from decide_me.planner import assemble_action_plan, detect_conflicts
from decide_me.registers import build_assumption_register, build_evidence_register, build_risk_register
from decide_me.safety_gate import build_safety_gate_report
from decide_me.session_graph import detect_session_conflicts
from decide_me.stale_detection import (
    detect_revisit_due,
    detect_stale_assumptions,
    detect_stale_evidence,
    detect_verification_gaps,
)
from decide_me.store import (
    SYSTEM_SESSION_ID,
    _write_transaction,
    ensure_runtime_dirs,
    load_runtime,
    read_event_log,
    rebuild_and_persist,
    runtime_paths,
    validate_runtime,
)
from decide_me.taxonomy import stable_unique


REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_SCHEMA_PATH = REPO_ROOT / "schemas" / "evaluation-scenario.schema.json"
EXPECTED_DIR_NAME = "expected"
DOCUMENT_OUTPUTS_DIR = "document_outputs"
DOCUMENT_OUTPUT_MANIFEST = "manifest.yaml"
REQUIRED_EXPECTED_FILES = {
    "decisions": "decisions.yaml",
    "questions": "unresolved_questions.yaml",
    "evidence": "evidence.yaml",
    "conflicts": "conflicts.yaml",
    "risks": "risks.yaml",
    "assumptions": "assumptions.yaml",
    "action_plan": "action_plan.yaml",
}


@dataclass(frozen=True)
class EvaluationScenario:
    data: dict[str, Any]
    path: Path
    root: Path
    seed_paths: dict[str, Path]
    expected: dict[str, Any]

    @property
    def scenario_id(self) -> str:
        return self.data["scenario_id"]

    @property
    def domain_pack(self) -> str:
        return self.data["domain_pack"]

    @property
    def sessions(self) -> list[dict[str, Any]]:
        return list(self.data["sessions"])

    @property
    def evaluation(self) -> dict[str, Any]:
        return self.data["evaluation"]


@dataclass(frozen=True)
class ScenarioRuntime:
    ai_dir: Path
    question_probe_ai_dir: Path
    bundle: dict[str, Any]
    events: list[dict[str, Any]]
    session_ids: list[str]
    closed_session_ids: list[str]


def load_scenario(path: Path) -> EvaluationScenario:
    scenario_path = path.resolve()
    raw = _load_payload(scenario_path)
    _validate_scenario_payload(raw)
    scenario_root = scenario_path.parent.resolve()
    expected = _load_expected_payloads(scenario_root)
    seed_paths = {
        session["session_id"]: _resolve_seed_path(scenario_root, session["seed_events"])
        for session in raw["sessions"]
    }
    _validate_source_material_fixture_paths(scenario_root)
    _validate_evidence_source_refs(scenario_root, seed_paths)
    return EvaluationScenario(
        data=raw,
        path=scenario_path,
        root=scenario_root,
        seed_paths=seed_paths,
        expected=expected,
    )


def build_scenario_runtime(
    scenario: EvaluationScenario,
    tmp_path: Path,
) -> ScenarioRuntime:
    ai_dir = Path(tmp_path) / scenario.scenario_id / ".ai" / "decide-me"
    paths = runtime_paths(ai_dir)
    ensure_runtime_dirs(paths)
    _write_bootstrap_events(scenario, ai_dir)
    rebuild_and_persist(ai_dir)
    question_probe_ai_dir = Path(tmp_path) / scenario.scenario_id / ".ai" / "decide-me-question-probe"
    shutil.copytree(ai_dir, question_probe_ai_dir)

    close_base = _parse_timestamp(scenario.evaluation["now"]) + timedelta(seconds=9000)
    for index, session in enumerate(scenario.sessions, start=1):
        if session["close"]:
            close_id_suffix = _close_id_suffix(index, session["session_id"])
            close_session(
                str(ai_dir),
                session["session_id"],
                now=_format_timestamp(close_base + timedelta(seconds=index)),
                tx_id=_tx_id(scenario, close_id_suffix),
                event_id_prefix=_event_id(scenario, close_id_suffix),
            )

    bundle = rebuild_and_persist(ai_dir)
    events = read_event_log(runtime_paths(ai_dir))
    closed_session_ids = [
        session_id
        for session_id in _scenario_session_ids(scenario)
        if bundle["sessions"][session_id]["session"]["lifecycle"]["status"] == "closed"
    ]
    return ScenarioRuntime(
        ai_dir=ai_dir,
        question_probe_ai_dir=question_probe_ai_dir,
        bundle=bundle,
        events=events,
        session_ids=_scenario_session_ids(scenario),
        closed_session_ids=closed_session_ids,
    )


def run_scenario_evaluation(
    scenario: EvaluationScenario,
    runtime: ScenarioRuntime,
) -> dict[str, Any]:
    started = time.perf_counter()
    ai_dir = runtime.ai_dir
    load_started = time.perf_counter()
    bundle = rebuild_and_persist(ai_dir)
    load_runtime_seconds = time.perf_counter() - load_started
    events = read_event_log(runtime_paths(ai_dir))
    project_state = bundle["project_state"]
    evaluation = scenario.evaluation
    failures: list[dict[str, Any]] = []

    validation_issues = validate_runtime(ai_dir)
    conflict_metrics = _conflict_detection_metrics(scenario, runtime, bundle, failures)
    metrics = {
        "question_efficiency": _question_efficiency_metric(scenario, runtime, failures),
        "decision_coverage": _decision_coverage_metric(scenario, project_state, failures),
        "evidence_linkage_rate": _evidence_linkage_metric(scenario, project_state, failures),
        "assumption_exposure": _assumption_exposure_metric(scenario, project_state, evaluation["now"], failures),
        "risk_coverage": _risk_and_safety_metric(scenario, runtime, project_state, failures),
        "conflict_detection_recall": conflict_metrics["recall"],
        "conflict_precision": conflict_metrics["precision"],
        "action_executability": _action_executability_metric(scenario, runtime, bundle, failures),
        "document_validity": _document_validity_metric(scenario, runtime, failures),
    }
    if validation_issues:
        metrics["action_executability"]["passed"] = False
        failures.append(
            _failure(
                "action_executability",
                "Runtime validation reported issues.",
                "$.runtime.validation",
                expected=[],
                actual=validation_issues,
            )
        )
    metrics["runtime_performance"] = _runtime_performance_metric(
        scenario,
        runtime,
        bundle,
        total_seconds=time.perf_counter() - started,
        load_runtime_seconds=load_runtime_seconds,
        failures=failures,
    )

    return {
        "schema_version": 2,
        "scenario_id": scenario.scenario_id,
        "status": "failed" if failures else "passed",
        "generated_at": evaluation["now"],
        "metrics": metrics,
        "failures": failures,
    }


def _load_payload(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        payload = json.loads(text)
    else:
        payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError(f"evaluation scenario must contain an object: {path}")
    return payload


def _validate_scenario_payload(payload: dict[str, Any]) -> None:
    validator = Draft202012Validator(
        json.loads(SCENARIO_SCHEMA_PATH.read_text(encoding="utf-8")),
        format_checker=_format_checker(),
    )
    errors = sorted(validator.iter_errors(payload), key=str)
    if errors:
        details = "; ".join(_format_schema_error(error) for error in errors)
        raise ValueError(f"invalid evaluation scenario: {details}")


def _load_expected_payloads(scenario_root: Path) -> dict[str, Any]:
    input_context = scenario_root / "input_context.md"
    if not input_context.is_file():
        raise FileNotFoundError(f"scenario input_context.md is required: {input_context}")
    source_materials = scenario_root / "source_materials"
    if not source_materials.is_dir():
        raise FileNotFoundError(f"scenario source_materials directory is required: {source_materials}")
    expected_root = scenario_root / EXPECTED_DIR_NAME
    if not expected_root.is_dir():
        raise FileNotFoundError(f"scenario expected directory is required: {expected_root}")

    expected: dict[str, Any] = {}
    for key, relative_path in REQUIRED_EXPECTED_FILES.items():
        expected[key] = _load_expected_yaml(expected_root / relative_path)
    performance_path = expected_root / "performance.yaml"
    expected["performance"] = _load_expected_yaml(performance_path) if performance_path.exists() else {}
    document_outputs = expected_root / DOCUMENT_OUTPUTS_DIR
    if not document_outputs.is_dir():
        raise FileNotFoundError(f"scenario expected/document_outputs directory is required: {document_outputs}")
    manifest_path = document_outputs / DOCUMENT_OUTPUT_MANIFEST
    manifest = _load_expected_yaml(manifest_path) if manifest_path.exists() else {}
    _validate_expected_document_manifest(manifest, manifest_path)
    documents = manifest["documents"]
    expected["documents"] = documents
    _validate_expected_payloads(scenario_root, expected)
    return expected


def _load_expected_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"scenario expected file is required: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError(f"scenario expected file must contain an object: {path}")
    return payload


def _validate_expected_payloads(scenario_root: Path, expected: dict[str, Any]) -> None:
    _validate_expected_decisions(expected["decisions"], scenario_root / EXPECTED_DIR_NAME / "decisions.yaml")
    _validate_expected_questions(expected["questions"], scenario_root / EXPECTED_DIR_NAME / "unresolved_questions.yaml")
    _validate_expected_evidence(expected["evidence"], scenario_root / EXPECTED_DIR_NAME / "evidence.yaml", scenario_root)
    _validate_expected_conflicts(expected["conflicts"], scenario_root / EXPECTED_DIR_NAME / "conflicts.yaml")
    _validate_expected_risks(expected["risks"], scenario_root / EXPECTED_DIR_NAME / "risks.yaml")
    _validate_expected_assumptions(expected["assumptions"], scenario_root / EXPECTED_DIR_NAME / "assumptions.yaml")
    _validate_expected_action_plan(expected["action_plan"], scenario_root / EXPECTED_DIR_NAME / "action_plan.yaml")
    performance_path = scenario_root / EXPECTED_DIR_NAME / "performance.yaml"
    _validate_expected_performance(expected["performance"], performance_path)


def _validate_expected_decisions(payload: dict[str, Any], path: Path) -> None:
    _require_keys(payload, {"required_domain_decision_types", "required_status_counts"}, path)
    _reject_unknown_keys(payload, {"required_domain_decision_types", "required_status_counts"}, path)
    _require_string_list(payload, "required_domain_decision_types", path)
    counts = _require_list(payload, "required_status_counts", path)
    for index, item in enumerate(counts):
        item_path = f"{path}:required_status_counts[{index}]"
        _require_mapping(item, item_path)
        _require_keys(item, {"status", "mode", "count"}, item_path)
        _reject_unknown_keys(item, {"status", "mode", "count"}, item_path)
        _require_non_empty_string(item, "status", item_path)
        _require_enum(item, "mode", {"exact", "min"}, item_path)
        _require_non_negative_int(item, "count", item_path)


def _validate_expected_questions(payload: dict[str, Any], path: Path) -> None:
    allowed = {"max_questions", "forbidden_repeated_decision_types", "probe_session_ids", "advance_steps"}
    _require_keys(payload, {"max_questions", "forbidden_repeated_decision_types"}, path)
    _reject_unknown_keys(payload, allowed, path)
    _require_non_negative_int(payload, "max_questions", path)
    _require_string_list(payload, "forbidden_repeated_decision_types", path)
    if "probe_session_ids" in payload:
        _require_string_list(payload, "probe_session_ids", path)
    if "advance_steps" in payload:
        _require_minimum_int(payload, "advance_steps", 1, path)


def _validate_expected_evidence(payload: dict[str, Any], path: Path, scenario_root: Path) -> None:
    allowed = {
        "min_linked_evidence",
        "required_evidence_requirement_ids",
        "required_source_refs",
        "require_all_linked_evidence_source_ref",
    }
    _require_keys(payload, {"min_linked_evidence", "required_evidence_requirement_ids", "required_source_refs"}, path)
    _reject_unknown_keys(payload, allowed, path)
    _require_non_negative_int(payload, "min_linked_evidence", path)
    _require_string_list(payload, "required_evidence_requirement_ids", path)
    source_refs = _require_string_list(payload, "required_source_refs", path)
    if "require_all_linked_evidence_source_ref" in payload:
        _require_bool(payload, "require_all_linked_evidence_source_ref", path)
    missing_source_refs = [
        source_ref
        for source_ref in source_refs
        if not _evidence_source_ref_exists(scenario_root, source_ref)
    ]
    if missing_source_refs:
        raise ValueError(f"{path} required_source_refs do not exist: {', '.join(sorted(missing_source_refs))}")


def _validate_expected_conflicts(payload: dict[str, Any], path: Path) -> None:
    allowed = {
        "expected_count",
        "required_conflict_ids",
        "required_conflict_types",
        "allowed_conflict_types",
        "forbidden_conflict_types",
    }
    _require_keys(payload, {"expected_count"}, path)
    _reject_unknown_keys(payload, allowed, path)
    _require_non_negative_int(payload, "expected_count", path)
    for key in (
        "required_conflict_ids",
        "required_conflict_types",
        "allowed_conflict_types",
        "forbidden_conflict_types",
    ):
        if key in payload:
            _require_string_list(payload, key, path)
    if "allowed_conflict_types" in payload and "forbidden_conflict_types" in payload:
        raise ValueError(
            f"{path} allowed_conflict_types and forbidden_conflict_types are mutually exclusive"
        )


def _validate_expected_risks(payload: dict[str, Any], path: Path) -> None:
    allowed = {
        "required_domain_risk_types",
        "required_risk_tiers",
        "min_high_or_critical_risks",
        "safety_gates",
    }
    _require_keys(payload, {"required_domain_risk_types", "min_high_or_critical_risks"}, path)
    _reject_unknown_keys(payload, allowed, path)
    _require_string_list(payload, "required_domain_risk_types", path)
    if "required_risk_tiers" in payload:
        _require_string_list(payload, "required_risk_tiers", path)
    _require_non_negative_int(payload, "min_high_or_critical_risks", path)
    if "safety_gates" in payload:
        _validate_expected_safety_gates(payload["safety_gates"], f"{path}:safety_gates")


def _validate_expected_safety_gates(payload: Any, path: str) -> None:
    _require_mapping(payload, path)
    allowed = {
        "required_rule_ids",
        "required_approval_thresholds",
        "min_approval_required_count",
        "max_approval_required_count",
        "required_insufficient_evidence_ids",
        "forbidden_rule_ids",
        "forbidden_approval_thresholds",
    }
    _require_keys(
        payload,
        {
            "required_rule_ids",
            "required_approval_thresholds",
            "min_approval_required_count",
            "required_insufficient_evidence_ids",
        },
        path,
    )
    _reject_unknown_keys(payload, allowed, path)
    _require_string_list(payload, "required_rule_ids", path)
    _require_string_list(payload, "required_approval_thresholds", path)
    _require_non_negative_int(payload, "min_approval_required_count", path)
    _require_string_list(payload, "required_insufficient_evidence_ids", path)
    if "max_approval_required_count" in payload:
        _require_non_negative_int(payload, "max_approval_required_count", path)
        if payload["max_approval_required_count"] < payload["min_approval_required_count"]:
            raise ValueError(f"{path} max_approval_required_count must be >= min_approval_required_count")
    for key in ("forbidden_rule_ids", "forbidden_approval_thresholds"):
        if key in payload:
            _require_string_list(payload, key, path)


def _validate_expected_assumptions(payload: dict[str, Any], path: Path) -> None:
    allowed = {
        "required_assumption_ids",
        "min_assumption_count",
        "stale_assumptions",
        "stale_evidence",
        "verification_gaps",
        "due_revisits",
    }
    _require_keys(payload, {"required_assumption_ids", "min_assumption_count"}, path)
    _reject_unknown_keys(payload, allowed, path)
    _require_string_list(payload, "required_assumption_ids", path)
    _require_non_negative_int(payload, "min_assumption_count", path)
    for key in ("stale_assumptions", "stale_evidence", "verification_gaps", "due_revisits"):
        if key in payload:
            _validate_count_expectation(payload[key], f"{path}:{key}")


def _validate_expected_action_plan(payload: dict[str, Any], path: Path) -> None:
    allowed = {
        "readiness",
        "min_implementation_ready_count",
        "min_action_count",
        "max_blocker_count",
        "require_no_unresolved_conflicts",
    }
    _reject_unknown_keys(payload, allowed, path)
    if not payload:
        return
    _require_keys(payload, {"readiness", "min_implementation_ready_count"}, path)
    _require_enum(payload, "readiness", {"ready", "conditional", "blocked"}, path)
    _require_non_negative_int(payload, "min_implementation_ready_count", path)
    if "min_action_count" in payload:
        _require_non_negative_int(payload, "min_action_count", path)
    if "max_blocker_count" in payload:
        _require_non_negative_int(payload, "max_blocker_count", path)
    if "require_no_unresolved_conflicts" in payload:
        _require_bool(payload, "require_no_unresolved_conflicts", path)


def _validate_expected_document_manifest(payload: dict[str, Any], path: Path) -> None:
    _require_keys(payload, {"documents"}, path)
    _reject_unknown_keys(payload, {"documents"}, path)
    documents = _require_list(payload, "documents", path)
    for index, document in enumerate(documents):
        item_path = f"{path}:documents[{index}]"
        _require_mapping(document, item_path)
        allowed = {"type", "format", "session_ids", "required_sections", "require_source_traceability"}
        _require_keys(document, {"type", "format", "required_sections"}, item_path)
        _reject_unknown_keys(document, allowed, item_path)
        _require_non_empty_string(document, "type", item_path)
        _require_enum(document, "format", {"json", "csv", "markdown"}, item_path)
        _require_string_list(document, "required_sections", item_path)
        if "session_ids" in document:
            _require_string_list(document, "session_ids", item_path)
        if "require_source_traceability" in document:
            _require_bool(document, "require_source_traceability", item_path)


def _validate_expected_performance(payload: dict[str, Any], path: Path) -> None:
    allowed = {"max_total_seconds", "max_load_runtime_seconds"}
    _reject_unknown_keys(payload, allowed, path)
    for key in sorted(allowed):
        if key in payload:
            _require_non_negative_number(payload, key, path)


def _validate_count_expectation(payload: Any, path: str) -> None:
    _require_mapping(payload, path)
    _require_keys(payload, {"mode", "count"}, path)
    _reject_unknown_keys(payload, {"mode", "count"}, path)
    _require_enum(payload, "mode", {"exact", "min"}, path)
    _require_non_negative_int(payload, "count", path)


def _require_keys(payload: dict[str, Any], required: set[str], path: Path | str) -> None:
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"{path} missing required keys: {', '.join(missing)}")


def _reject_unknown_keys(payload: dict[str, Any], allowed: set[str], path: Path | str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"{path} contains unknown keys: {', '.join(unknown)}")


def _require_mapping(value: Any, path: Path | str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")


def _require_list(payload: dict[str, Any], key: str, path: Path | str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{path} {key} must be an array")
    return value


def _require_string_list(payload: dict[str, Any], key: str, path: Path | str) -> list[str]:
    values = _require_list(payload, key, path)
    invalid = [value for value in values if not isinstance(value, str) or not value]
    if invalid:
        raise ValueError(f"{path} {key} must contain only non-empty strings")
    return values


def _require_non_empty_string(payload: dict[str, Any], key: str, path: Path | str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} {key} must be a non-empty string")
    return value


def _require_enum(payload: dict[str, Any], key: str, allowed: set[str], path: Path | str) -> str:
    value = _require_non_empty_string(payload, key, path)
    if value not in allowed:
        raise ValueError(f"{path} {key} must be one of: {', '.join(sorted(allowed))}")
    return value


def _require_non_negative_int(payload: dict[str, Any], key: str, path: Path | str) -> int:
    return _require_minimum_int(payload, key, 0, path)


def _require_minimum_int(payload: dict[str, Any], key: str, minimum: int, path: Path | str) -> int:
    value = payload.get(key)
    if type(value) is not int or value < minimum:
        raise ValueError(f"{path} {key} must be an integer >= {minimum}")
    return value


def _require_non_negative_number(payload: dict[str, Any], key: str, path: Path | str) -> float:
    value = payload.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{path} {key} must be a number >= 0")
    return float(value)


def _require_bool(payload: dict[str, Any], key: str, path: Path | str) -> bool:
    value = payload.get(key)
    if type(value) is not bool:
        raise ValueError(f"{path} {key} must be a boolean")
    return value


def _validate_source_material_fixture_paths(scenario_root: Path) -> None:
    _resolve_fixture_path(scenario_root, "input_context.md")
    source_materials = (scenario_root / "source_materials").resolve()
    for path in source_materials.rglob("*"):
        if path.is_file():
            try:
                path.resolve().relative_to(source_materials)
            except ValueError as exc:  # pragma: no cover - defensive on unusual filesystems
                raise ValueError(f"source material path escapes source_materials: {path}") from exc


def _validate_evidence_source_refs(scenario_root: Path, seed_paths: dict[str, Path]) -> None:
    invalid_refs = []
    for seed_path in seed_paths.values():
        for spec in _load_seed_event_specs_from_path(seed_path):
            if spec.get("event_type") != "object_recorded":
                continue
            obj = spec.get("payload", {}).get("object", {})
            if obj.get("type") != "evidence":
                continue
            source_ref = obj.get("metadata", {}).get("source_ref")
            if source_ref and not _evidence_source_ref_exists(scenario_root, str(source_ref)):
                invalid_refs.append(f"{seed_path.name}:{obj.get('id')}:{source_ref}")
    if invalid_refs:
        raise ValueError(
            "evidence source_ref must point to input_context.md or source_materials/: "
            + ", ".join(sorted(invalid_refs))
        )


def _evidence_source_ref_exists(scenario_root: Path, source_ref: str) -> bool:
    if source_ref == "input_context.md":
        return (scenario_root / "input_context.md").is_file()
    try:
        candidate = _resolve_fixture_path(scenario_root / "source_materials", source_ref)
    except ValueError:
        return False
    return candidate.is_file()


def _resolve_fixture_path(root: Path, relative_path: str) -> Path:
    if Path(relative_path).is_absolute() or _looks_like_windows_absolute_path(relative_path):
        raise ValueError(f"fixture path must be relative: {relative_path}")
    resolved = (root / relative_path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"fixture path escapes root: {relative_path}") from exc
    return resolved


def _resolve_seed_path(scenario_root: Path, seed_events: str) -> Path:
    seed_path = (scenario_root / seed_events).resolve()
    try:
        seed_path.relative_to(scenario_root)
    except ValueError as exc:
        raise ValueError(f"seed_events path escapes scenario root: {seed_events}") from exc
    if not seed_path.is_file():
        raise FileNotFoundError(f"seed_events file does not exist: {seed_path}")
    return seed_path


def _write_bootstrap_events(scenario: EvaluationScenario, ai_dir: Path) -> None:
    paths = runtime_paths(ai_dir)
    registry = load_domain_registry(ai_dir)
    pack = registry.get(scenario.domain_pack)
    timestamp_base = _parse_timestamp(scenario.evaluation["now"])
    tx_counter = 1

    project_payload = {
        "project": {
            "name": scenario.data["project"]["name"],
            "objective": scenario.data["project"]["objective"],
            "current_milestone": scenario.data["project"]["current_milestone"],
            "stop_rule": "All relevant P0 decisions with frontier=now are resolved, accepted, or explicitly deferred.",
        },
        "protocol": {
            "plain_ok_scope": "same-session-active-proposal-only",
            "proposal_expiry_rules": [
                "project-head-changed",
                "session-boundary",
                "superseded-proposal",
                "decision-invalidated",
                "session-closed",
            ],
            "close_policy": "generate-close-summary-on-close",
        },
    }
    _write_event_specs(
        paths,
        tx_id=_tx_id(scenario, tx_counter),
        specs=[
            {
                "event_id": _event_id(scenario, "project"),
                "session_id": SYSTEM_SESSION_ID,
                "event_type": "project_initialized",
                "payload": project_payload,
                "ts": _format_timestamp(timestamp_base),
            }
        ],
    )
    tx_counter += 1

    classification = _domain_pack_classification(pack, _format_timestamp(timestamp_base + timedelta(seconds=1)))
    for index, session in enumerate(scenario.sessions, start=1):
        timestamp = _format_timestamp(timestamp_base + timedelta(seconds=index))
        session_id = session["session_id"]
        _write_event_specs(
            paths,
            tx_id=_tx_id(scenario, tx_counter),
            specs=[
                {
                    "event_id": _event_id(scenario, f"session-{index:04d}"),
                    "session_id": session_id,
                    "event_type": "session_created",
                    "payload": {
                        "session": {
                            "id": session_id,
                            "started_at": timestamp,
                            "last_seen_at": timestamp,
                            "bound_context_hint": session["context"],
                            "classification": {**classification, "updated_at": timestamp},
                        }
                    },
                    "ts": timestamp,
                }
            ],
        )
        tx_counter += 1

    seed_offset = 1000
    for session_index, session in enumerate(scenario.sessions, start=1):
        session_id = session["session_id"]
        for event_index, spec in enumerate(_load_seed_event_specs(scenario, session), start=1):
            default_timestamp = _format_timestamp(
                timestamp_base + timedelta(seconds=seed_offset + session_index * 100 + event_index)
            )
            spec = _normalize_seed_spec(
                scenario,
                session_id,
                spec,
                event_index=event_index,
                default_timestamp=default_timestamp,
            )
            _write_event_specs(paths, tx_id=_tx_id(scenario, tx_counter), specs=[spec])
            tx_counter += 1


def _write_event_specs(paths: Any, *, tx_id: str, specs: list[dict[str, Any]]) -> None:
    # Scenario fixtures need fixed session IDs, timestamps, transaction IDs, and EventSpec JSONL
    # replay before a public scenario runner exists, so this dev-only helper writes deterministic
    # transaction files directly and still relies on rebuild_and_persist() for projections.
    tx_size = len(specs)
    events = [
        build_event(
            tx_id=tx_id,
            tx_index=index,
            tx_size=tx_size,
            session_id=spec["session_id"],
            event_type=spec["event_type"],
            payload=spec["payload"],
            timestamp=spec["ts"],
            event_id=spec["event_id"],
        )
        for index, spec in enumerate(specs, start=1)
    ]
    _write_transaction(paths, events)


def _load_seed_event_specs(
    scenario: EvaluationScenario,
    session: dict[str, Any],
) -> list[dict[str, Any]]:
    seed_path = scenario.seed_paths[session["session_id"]]
    return _load_seed_event_specs_from_path(seed_path)


def _load_seed_event_specs_from_path(seed_path: Path) -> list[dict[str, Any]]:
    specs = []
    with seed_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                spec = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{seed_path} line {line_number} contains malformed JSON: {exc.msg}") from exc
            if not isinstance(spec, dict):
                raise ValueError(f"{seed_path} line {line_number} must contain an EventSpec object")
            specs.append(spec)
    return specs


def _normalize_seed_spec(
    scenario: EvaluationScenario,
    session_id: str,
    spec: dict[str, Any],
    *,
    event_index: int,
    default_timestamp: str,
) -> dict[str, Any]:
    forbidden_envelope_keys = {"tx_id", "tx_index", "tx_size"}
    present_envelope_keys = sorted(forbidden_envelope_keys & set(spec))
    if present_envelope_keys:
        raise ValueError(
            "seed_events must contain EventSpec rows, not full event envelopes; "
            f"unsupported keys: {', '.join(present_envelope_keys)}"
        )
    if "event_type" not in spec or "payload" not in spec:
        raise ValueError("seed EventSpec rows require event_type and payload")
    explicit_session_id = spec.get("session_id", session_id)
    if explicit_session_id != session_id:
        raise ValueError(
            f"seed EventSpec session_id {explicit_session_id} does not match scenario session {session_id}"
        )
    return {
        "event_id": spec.get("event_id") or _event_id(
            scenario,
            f"{session_id.lower().replace('-', '_')}-{event_index:04d}",
        ),
        "session_id": session_id,
        "event_type": spec["event_type"],
        "payload": deepcopy(spec["payload"]),
        "ts": spec.get("ts") or default_timestamp,
    }


def _question_efficiency_metric(
    scenario: EvaluationScenario,
    runtime: ScenarioRuntime,
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = scenario.expected["questions"]
    probe_session_ids = expected.get("probe_session_ids") or _scenario_session_ids(scenario)
    advance_steps = expected.get("advance_steps", 1)
    known_sessions = set(_scenario_session_ids(scenario))
    unknown_sessions = [session_id for session_id in probe_session_ids if session_id not in known_sessions]
    before_event_ids = {event["event_id"] for event in read_event_log(runtime_paths(runtime.question_probe_ai_dir))}

    probe_errors: list[str] = []
    for session_id in probe_session_ids:
        if session_id in unknown_sessions:
            continue
        for _step in range(advance_steps):
            try:
                advance_session(str(runtime.question_probe_ai_dir), session_id, repo_root=scenario.root)
            except Exception as exc:  # pragma: no cover - future scenario fixtures may exercise this
                probe_errors.append(f"{session_id}: {exc}")
                break

    probe_bundle = load_runtime(runtime_paths(runtime.question_probe_ai_dir))
    probe_events = read_event_log(runtime_paths(runtime.question_probe_ai_dir))
    question_events = [
        event
        for event in probe_events
        if event["event_id"] not in before_event_ids and event["event_type"] == "session_question_asked"
    ]
    object_by_id = _objects_by_id(probe_bundle["project_state"])
    decision_types = [
        object_by_id.get(event["payload"]["target_object_id"], {}).get("metadata", {}).get("domain_decision_type")
        for event in question_events
    ]
    counts = Counter(value for value in decision_types if value)
    repeated = sorted(
        decision_type
        for decision_type in expected["forbidden_repeated_decision_types"]
        if counts.get(decision_type, 0) > 1
    )
    passed = (
        len(question_events) <= expected["max_questions"]
        and not repeated
        and not unknown_sessions
        and not probe_errors
    )
    if len(question_events) > expected["max_questions"]:
        failures.append(
            _failure(
                "question_efficiency",
                "Scenario asked too many questions.",
                "$.metrics.question_efficiency.asked_count",
                expected=expected["max_questions"],
                actual=len(question_events),
            )
        )
    if repeated:
        failures.append(
            _failure(
                "question_efficiency",
                "Scenario repeated forbidden decision type questions.",
                "$.metrics.question_efficiency.repeated_forbidden_decision_types",
                expected=[],
                actual=repeated,
            )
        )
    if unknown_sessions:
        failures.append(
            _failure(
                "question_efficiency",
                "Question probe references unknown scenario sessions.",
                "$.evaluation.expected_questions.probe_session_ids",
                expected=sorted(known_sessions),
                actual=unknown_sessions,
            )
        )
    if probe_errors:
        failures.append(
            _failure(
                "question_efficiency",
                "Question probe execution failed.",
                "$.metrics.question_efficiency",
                expected="advance_session probe succeeds",
                actual=probe_errors,
            )
        )
    return {
        "asked_count": len(question_events),
        "max_allowed": expected["max_questions"],
        "repeated_forbidden_decision_types": repeated,
        "passed": passed,
    }


def _decision_coverage_metric(
    scenario: EvaluationScenario,
    project_state: dict[str, Any],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = scenario.expected["decisions"]
    decisions = [obj for obj in project_state.get("objects", []) if obj.get("type") == "decision"]
    actual_types = {
        obj.get("metadata", {}).get("domain_decision_type")
        for obj in decisions
        if obj.get("metadata", {}).get("domain_decision_type")
    }
    required_types = expected["required_domain_decision_types"]
    missing = [decision_type for decision_type in required_types if decision_type not in actual_types]

    status_counts = Counter(obj.get("status") for obj in decisions)
    status_failures = []
    for item in expected["required_status_counts"]:
        actual_count = status_counts.get(item["status"], 0)
        satisfied = actual_count == item["count"] if item["mode"] == "exact" else actual_count >= item["count"]
        if not satisfied:
            status_failures.append(
                {
                    "status": item["status"],
                    "mode": item["mode"],
                    "expected": item["count"],
                    "actual": actual_count,
                }
            )
            missing.append(f"status:{item['status']}:{item['mode']}:{item['count']}")

    required_count = len(required_types) + len(expected["required_status_counts"])
    covered_count = required_count - len(missing)
    passed = not missing
    if missing:
        failures.append(
            _failure(
                "decision_coverage",
                "Missing required decision coverage.",
                "$.metrics.decision_coverage",
                expected=expected,
                actual={
                    "domain_decision_types": sorted(actual_types),
                    "status_counts": dict(sorted(status_counts.items())),
                    "status_failures": status_failures,
                },
            )
        )
    return {
        "required_count": required_count,
        "covered_count": covered_count,
        "missing_ids": missing,
        "passed": passed,
    }


def _evidence_linkage_metric(
    scenario: EvaluationScenario,
    project_state: dict[str, Any],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = scenario.expected["evidence"]
    register = build_evidence_register(project_state)
    objects_by_id = _objects_by_id(project_state)
    live_evidence_items = [item for item in register["items"] if _is_live_object(item)]
    linked_evidence_items = [
        item
        for item in live_evidence_items
        if _is_live_object(item) and (item.get("supports_object_ids") or item.get("verifies_object_ids"))
    ]
    linked_count = len(linked_evidence_items)
    total_count = len(live_evidence_items)
    linkage_rate = 1.0 if total_count == 0 else linked_count / total_count
    actual_requirement_ids = {
        objects_by_id.get(item["object_id"], {}).get("metadata", {}).get("evidence_requirement_id")
        for item in linked_evidence_items
        if objects_by_id.get(item["object_id"], {}).get("metadata", {}).get("evidence_requirement_id")
    }
    actual_source_refs = {
        objects_by_id.get(item["object_id"], {}).get("metadata", {}).get("source_ref")
        for item in linked_evidence_items
        if objects_by_id.get(item["object_id"], {}).get("metadata", {}).get("source_ref")
    }
    missing_source_ref_ids = [
        item["object_id"]
        for item in linked_evidence_items
        if not objects_by_id.get(item["object_id"], {}).get("metadata", {}).get("source_ref")
    ]
    coverage_missing = [
        requirement_id
        for requirement_id in expected["required_evidence_requirement_ids"]
        if requirement_id not in actual_requirement_ids
    ]
    for source_ref in expected.get("required_source_refs", []):
        if source_ref not in actual_source_refs:
            coverage_missing.append(f"source_ref:{source_ref}")
    diagnostic_missing: list[str] = []
    min_linked = expected.get("min_linked_evidence", expected.get("min_supporting_evidence", 0))
    if linked_count < min_linked:
        diagnostic_missing.append(f"linked_evidence_min:{min_linked}")
    if expected.get("require_all_linked_evidence_source_ref"):
        diagnostic_missing.extend(f"source_ref_missing:{object_id}" for object_id in missing_source_ref_ids)
    invalid_source_refs = [
        str(ref)
        for ref in sorted(actual_source_refs)
        if not _evidence_source_ref_exists(scenario.root, str(ref))
    ]

    required_count = len(expected["required_evidence_requirement_ids"]) + len(expected.get("required_source_refs", []))
    covered_count = max(0, required_count - len(coverage_missing))
    missing = coverage_missing + diagnostic_missing
    passed = not missing and not invalid_source_refs
    if missing or invalid_source_refs:
        failures.append(
            _failure(
                "evidence_linkage_rate",
                "Missing required evidence linkage.",
                "$.metrics.evidence_linkage_rate",
                expected=expected,
                actual={
                    "supporting_evidence_requirement_ids": sorted(actual_requirement_ids),
                    "supporting_source_refs": sorted(actual_source_refs),
                    "linked_evidence": linked_count,
                    "total_evidence": total_count,
                    "missing_source_ref_ids": missing_source_ref_ids,
                    "invalid_source_refs": invalid_source_refs,
                },
            )
        )
    return {
        "required_count": required_count,
        "covered_count": covered_count,
        "linked_evidence_count": linked_count,
        "total_evidence_count": total_count,
        "linkage_rate": round(linkage_rate, 6),
        "missing_ids": missing,
        "invalid_source_refs": invalid_source_refs,
        "passed": passed,
    }


def _risk_and_safety_metric(
    scenario: EvaluationScenario,
    runtime: ScenarioRuntime,
    project_state: dict[str, Any],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_risks = scenario.expected["risks"]
    risk_register = build_risk_register(project_state)
    objects_by_id = _objects_by_id(project_state)
    live_risk_items = [item for item in risk_register["items"] if _is_live_object(item)]
    actual_risk_types = {
        objects_by_id.get(item["object_id"], {}).get("metadata", {}).get("domain_risk_type")
        for item in live_risk_items
        if objects_by_id.get(item["object_id"], {}).get("metadata", {}).get("domain_risk_type")
    }
    actual_tiers = {item.get("risk_tier") for item in live_risk_items if item.get("risk_tier")}
    high_or_critical = sum(
        1
        for item in live_risk_items
        if item.get("risk_tier") in {"high", "critical"}
    )
    missing = [
        risk_type
        for risk_type in expected_risks["required_domain_risk_types"]
        if risk_type not in actual_risk_types
    ]
    for risk_tier in expected_risks.get("required_risk_tiers", []):
        if risk_tier not in actual_tiers:
            missing.append(f"risk_tier:{risk_tier}")
    if high_or_critical < expected_risks["min_high_or_critical_risks"]:
        missing.append(f"high_or_critical_min:{expected_risks['min_high_or_critical_risks']}")

    safety_actual: dict[str, Any] = {}
    expected_safety = expected_risks.get("safety_gates")
    if expected_safety is not None:
        safety_gate_report = build_safety_gate_report(
            project_state,
            now=scenario.evaluation["now"],
            domain_registry=load_domain_registry(runtime.ai_dir),
        )
        safety_actual = _safety_gate_actuals(safety_gate_report)
        for rule_id in expected_safety["required_rule_ids"]:
            if rule_id not in safety_actual["rule_ids"]:
                missing.append(f"safety_rule:{rule_id}")
        for threshold in expected_safety["required_approval_thresholds"]:
            if threshold not in safety_actual["approval_thresholds"]:
                missing.append(f"approval_threshold:{threshold}")
        if safety_actual["approval_required_count"] < expected_safety["min_approval_required_count"]:
            missing.append(f"approval_required_min:{expected_safety['min_approval_required_count']}")
        max_approval_required_count = expected_safety.get("max_approval_required_count")
        if (
            max_approval_required_count is not None
            and safety_actual["approval_required_count"] > max_approval_required_count
        ):
            missing.append(f"approval_required_max:{max_approval_required_count}")
        for requirement_id in expected_safety["required_insufficient_evidence_ids"]:
            if requirement_id not in safety_actual["insufficient_evidence_ids"]:
                missing.append(f"insufficient_evidence:{requirement_id}")
        for rule_id in expected_safety.get("forbidden_rule_ids", []):
            if rule_id in safety_actual["rule_ids"]:
                missing.append(f"forbidden_safety_rule:{rule_id}")
        for threshold in expected_safety.get("forbidden_approval_thresholds", []):
            if threshold in safety_actual["approval_thresholds"]:
                missing.append(f"forbidden_approval_threshold:{threshold}")

    required_count = (
        len(expected_risks["required_domain_risk_types"])
        + len(expected_risks.get("required_risk_tiers", []))
        + (1 if expected_risks["min_high_or_critical_risks"] else 0)
    )
    if expected_safety is not None:
        required_count += (
            len(expected_safety["required_rule_ids"])
            + len(expected_safety["required_approval_thresholds"])
            + (1 if expected_safety["min_approval_required_count"] else 0)
            + (1 if expected_safety.get("max_approval_required_count") is not None else 0)
            + len(expected_safety["required_insufficient_evidence_ids"])
            + len(expected_safety.get("forbidden_rule_ids", []))
            + len(expected_safety.get("forbidden_approval_thresholds", []))
        )
    covered_count = max(0, required_count - len(missing))
    passed = not missing
    if missing:
        failures.append(
            _failure(
                "risk_coverage",
                "Risk or safety gate expectations did not match.",
                "$.metrics.risk_coverage",
                expected={
                    "risks": expected_risks,
                    "safety_gates": expected_safety,
                },
                actual={
                    "domain_risk_types": sorted(actual_risk_types),
                    "risk_tiers": sorted(actual_tiers),
                    "high_or_critical_risks": high_or_critical,
                    "safety_gates": safety_actual,
                },
            )
        )
    return {
        "required_count": required_count,
        "covered_count": covered_count,
        "missing_ids": missing,
        "passed": passed,
    }


def _safety_gate_actuals(safety_gate_report: dict[str, Any]) -> dict[str, Any]:
    rule_ids = set()
    approval_thresholds = set()
    insufficient_evidence_ids = set()
    for result in safety_gate_report["results"]:
        if result.get("approval_threshold"):
            approval_thresholds.add(result["approval_threshold"])
        for rule in result.get("domain_safety_rules", []):
            rule_ids.add(rule["rule_id"])
            approval_thresholds.add(rule["approval_threshold"])
        for requirement in result.get("domain_requirements", []):
            if not requirement.get("satisfied"):
                insufficient_evidence_ids.add(requirement["required_evidence_id"])
    return {
        "rule_ids": sorted(rule_ids),
        "approval_thresholds": sorted(approval_thresholds),
        "approval_required_count": safety_gate_report["summary"]["approval_required_count"],
        "insufficient_evidence_ids": sorted(insufficient_evidence_ids),
    }


def _conflict_detection_metrics(
    scenario: EvaluationScenario,
    runtime: ScenarioRuntime,
    bundle: dict[str, Any],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = scenario.expected["conflicts"]
    conflicts = _scenario_conflicts(runtime, bundle)
    actual_ids = sorted(conflict["conflict_id"] for conflict in conflicts)
    actual_types = sorted(
        {
            conflict_type
            for conflict in conflicts
            if (conflict_type := conflict.get("conflict_type") or conflict.get("kind"))
        }
    )
    expected_count = expected.get("expected_count", expected.get("count", 0))
    required_ids = expected.get("required_conflict_ids", [])
    required_types = expected.get("required_conflict_types", [])
    missing_ids = [conflict_id for conflict_id in required_ids if conflict_id not in actual_ids]
    missing_types = [conflict_type for conflict_type in required_types if conflict_type not in actual_types]
    recall_passed = len(conflicts) >= expected_count and not missing_ids and not missing_types
    unexpected_ids = [
        conflict_id
        for conflict_id in actual_ids
        if conflict_id not in required_ids
    ] if required_ids else (actual_ids if len(conflicts) > expected_count else [])
    unexpected_types = _unexpected_conflict_types(actual_types, expected)
    false_positive_count = max(
        len(unexpected_ids),
        len(unexpected_types),
        max(0, len(conflicts) - expected_count),
    )
    precision_passed = len(conflicts) <= expected_count and not unexpected_ids and not unexpected_types
    if not recall_passed:
        failures.append(
            _failure(
                "conflict_detection_recall",
                "Required conflict diagnostics were not detected.",
                "$.metrics.conflict_detection_recall",
                expected=expected,
                actual={
                    "count": len(conflicts),
                    "conflict_ids": actual_ids,
                    "conflict_types": actual_types,
                },
            )
        )
    if not precision_passed:
        failures.append(
            _failure(
                "conflict_precision",
                "Unexpected conflict diagnostics were detected.",
                "$.metrics.conflict_precision",
                expected=expected,
                actual={
                    "count": len(conflicts),
                    "conflict_ids": actual_ids,
                    "unexpected_conflict_ids": unexpected_ids,
                    "conflict_types": actual_types,
                    "unexpected_conflict_types": unexpected_types,
                },
            )
        )
    return {
        "recall": {
            "expected_count": expected_count,
            "actual_count": len(conflicts),
            "missing_conflict_ids": sorted(missing_ids),
            "missing_conflict_types": sorted(missing_types),
            "passed": recall_passed,
        },
        "precision": {
            "expected_count": expected_count,
            "actual_count": len(conflicts),
            "unexpected_conflict_ids": unexpected_ids,
            "unexpected_conflict_types": unexpected_types,
            "false_positive_count": false_positive_count,
            "passed": precision_passed,
        },
    }


def _unexpected_conflict_types(actual_types: list[str], expected: dict[str, Any]) -> list[str]:
    if "forbidden_conflict_types" in expected:
        return [
            conflict_type
            for conflict_type in actual_types
            if conflict_type in set(expected["forbidden_conflict_types"])
        ]
    if "allowed_conflict_types" in expected:
        allowed = set(expected["allowed_conflict_types"])
        return [conflict_type for conflict_type in actual_types if conflict_type not in allowed]
    required_types = set(expected.get("required_conflict_types", []))
    if required_types:
        return [conflict_type for conflict_type in actual_types if conflict_type not in required_types]
    expected_count = expected.get("expected_count", 0)
    return actual_types if actual_types and expected_count == 0 else []


def _scenario_conflicts(runtime: ScenarioRuntime, bundle: dict[str, Any]) -> list[dict[str, Any]]:
    scenario_sessions = [
        bundle["sessions"][session_id]
        for session_id in runtime.session_ids
        if session_id in bundle["sessions"]
    ]
    planner_conflicts = detect_conflicts(
        scenario_sessions,
        bundle["project_state"],
        resolved_conflicts=bundle["project_state"].get("graph", {}).get("resolved_conflicts", []),
        include_resolved=True,
    )
    session_conflicts = detect_session_conflicts(
        str(runtime.ai_dir),
        session_ids=runtime.session_ids,
        include_related=False,
    )["semantic_conflicts"]
    by_id = {
        conflict["conflict_id"]: conflict
        for conflict in [*planner_conflicts, *session_conflicts]
    }
    return [by_id[conflict_id] for conflict_id in sorted(by_id)]


def _unresolved_conflicts(conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        conflict
        for conflict in conflicts
        if conflict.get("requires_resolution", conflict.get("status") not in {"resolved", "suppressed"})
    ]


def _action_executability_metric(
    scenario: EvaluationScenario,
    runtime: ScenarioRuntime,
    bundle: dict[str, Any],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    unresolved_conflict_count = len(_unresolved_conflicts(_scenario_conflicts(runtime, bundle)))
    closed_sessions = [
        bundle["sessions"][session_id]
        for session_id in runtime.closed_session_ids
        if session_id in bundle["sessions"]
    ]
    expected = scenario.expected["action_plan"]
    if not closed_sessions:
        if expected:
            failures.append(
                _failure(
                    "action_executability",
                    "Action executability requires at least one closed session.",
                    "$.metrics.action_executability",
                    expected=expected,
                    actual={
                        "closed_session_count": 0,
                        "unresolved_conflict_count": unresolved_conflict_count,
                    },
                )
            )
            return {
                "readiness": "blocked",
                "action_count": 0,
                "implementation_ready_count": 0,
                "blocker_count": 0,
                "unresolved_conflict_count": unresolved_conflict_count,
                "passed": False,
            }
        return {
            "readiness": "ready",
            "action_count": 0,
            "implementation_ready_count": 0,
            "blocker_count": 0,
            "unresolved_conflict_count": unresolved_conflict_count,
            "passed": True,
        }
    try:
        action_plan = assemble_action_plan(
            closed_sessions,
            bundle["project_state"],
            resolved_conflicts=bundle["project_state"].get("graph", {}).get("resolved_conflicts", []),
        )
    except Exception as exc:  # pragma: no cover - exercised by future broken fixtures
        failures.append(
            _failure(
                "action_executability",
                "Action plan assembly failed.",
                "$.metrics.action_executability",
                expected="action plan",
                actual=str(exc),
            )
        )
        return {
            "readiness": "blocked",
            "action_count": 0,
            "implementation_ready_count": 0,
            "blocker_count": 0,
            "unresolved_conflict_count": unresolved_conflict_count,
            "passed": False,
        }
    readiness = action_plan["readiness"]
    action_count = len(action_plan["actions"])
    implementation_ready_count = len(action_plan["implementation_ready_actions"])
    blocker_count = len(action_plan["blockers"])
    expectation_failures: list[str] = []
    if expected:
        if readiness != expected["readiness"]:
            expectation_failures.append(f"readiness:{expected['readiness']}")
        if implementation_ready_count < expected["min_implementation_ready_count"]:
            expectation_failures.append(
                f"implementation_ready_min:{expected['min_implementation_ready_count']}"
            )
        if action_count < expected.get("min_action_count", 0):
            expectation_failures.append(f"action_min:{expected['min_action_count']}")
        max_blocker_count = expected.get("max_blocker_count")
        if max_blocker_count is not None and blocker_count > max_blocker_count:
            expectation_failures.append(f"blocker_max:{max_blocker_count}")
        if expected.get("require_no_unresolved_conflicts", True) and unresolved_conflict_count:
            expectation_failures.append("unresolved_conflicts:0")
        if expectation_failures:
            failures.append(
                _failure(
                    "action_executability",
                    "Action executability did not match expectations.",
                    "$.metrics.action_executability",
                    expected=expected,
                    actual={
                        "readiness": readiness,
                        "action_count": action_count,
                        "implementation_ready_count": implementation_ready_count,
                        "blocker_count": blocker_count,
                        "unresolved_conflict_count": unresolved_conflict_count,
                        "failed_expectations": expectation_failures,
                    },
                )
            )
    return {
        "readiness": readiness,
        "action_count": action_count,
        "implementation_ready_count": implementation_ready_count,
        "blocker_count": blocker_count,
        "unresolved_conflict_count": unresolved_conflict_count,
        "passed": not expectation_failures,
    }


def _document_validity_metric(
    scenario: EvaluationScenario,
    runtime: ScenarioRuntime,
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_documents = scenario.expected["documents"]
    missing_sections: list[str] = []
    empty_sections: list[str] = []
    missing_traceability: list[str] = []
    for expected in expected_documents:
        try:
            document = compile_document(
                runtime.ai_dir,
                document_type=expected["type"],
                session_ids=_expected_document_session_ids(expected, runtime),
                domain_pack_id=scenario.domain_pack,
                now=scenario.evaluation["now"],
            )
        except Exception as exc:
            failures.append(
                _failure(
                    "document_validity",
                    f"Document compilation failed for {expected['type']}.",
                    "$.metrics.document_validity",
                    expected=expected,
                    actual=str(exc),
                )
            )
            missing_sections.extend(expected["required_sections"])
            continue

        sections_by_id = {section["id"]: section for section in document.get("sections", [])}
        for section_id in expected["required_sections"]:
            section = sections_by_id.get(section_id)
            if section is None:
                missing_sections.append(section_id)
            elif not _section_has_content(section):
                empty_sections.append(section_id)
        if expected.get("require_source_traceability") and not _document_has_source_traceability(document):
            missing_traceability.append(expected["type"])

    passed = not missing_sections and not empty_sections and not missing_traceability
    if missing_sections or empty_sections or missing_traceability:
        failures.append(
            _failure(
                "document_validity",
                "Document required sections or source traceability were missing or empty.",
                "$.metrics.document_validity",
                expected=expected_documents,
                actual={
                    "missing_sections": sorted(stable_unique(missing_sections)),
                    "empty_sections": sorted(stable_unique(empty_sections)),
                    "missing_source_traceability": sorted(stable_unique(missing_traceability)),
                },
            )
        )
    return {
        "required_sections_present": not missing_sections,
        "empty_required_sections": sorted(stable_unique(empty_sections)),
        "missing_source_traceability": sorted(stable_unique(missing_traceability)),
        "passed": passed,
    }


def _expected_document_session_ids(
    expected: dict[str, Any],
    runtime: ScenarioRuntime,
) -> list[str]:
    return list(expected.get("session_ids") or runtime.closed_session_ids)


def _assumption_exposure_metric(
    scenario: EvaluationScenario,
    project_state: dict[str, Any],
    now: str,
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = scenario.expected["assumptions"]
    assumption_register = build_assumption_register(project_state)
    assumption_ids = {
        item["object_id"]
        for item in assumption_register["items"]
        if _is_live_object(item)
    }
    stale_assumptions = detect_stale_assumptions(project_state, now=now)
    stale_evidence = detect_stale_evidence(project_state, now=now)
    verification_gaps = detect_verification_gaps(project_state, now=now)
    revisit_due = detect_revisit_due(project_state, now=now)
    counts = {
        "stale_assumptions": stale_assumptions["summary"]["item_count"],
        "stale_evidence": stale_evidence["summary"]["item_count"],
        "verification_gaps": verification_gaps["summary"]["item_count"],
        "due_revisits": revisit_due["summary"]["item_count"],
    }
    required_assumption_ids = expected.get("required_assumption_ids", [])
    min_assumption_count = expected.get("min_assumption_count", 0)
    missing = [
        assumption_id
        for assumption_id in required_assumption_ids
        if assumption_id not in assumption_ids
    ]
    if len(assumption_ids) < min_assumption_count:
        missing.append(f"assumption_min:{min_assumption_count}")
    expectation_failures: list[dict[str, Any]] = []
    for key, actual_count in counts.items():
        expectation = expected.get(key)
        if expectation is not None and not _count_expectation_satisfied(expectation, actual_count):
            expectation_failures.append(
                {
                    "diagnostic": key,
                    "mode": expectation["mode"],
                    "expected": expectation["count"],
                    "actual": actual_count,
                }
            )
    if missing or expectation_failures:
        failures.append(
            _failure(
                "assumption_exposure",
                "Assumption exposure or revisit diagnostics did not match expectations.",
                "$.metrics.assumption_exposure",
                expected=expected,
                actual={
                    "assumption_ids": sorted(assumption_ids),
                    **counts,
                    "failed_expectations": expectation_failures,
                },
            )
        )
    required_count = len(required_assumption_ids) + (1 if min_assumption_count else 0)
    covered_count = required_count - len(
        [
            item
            for item in missing
            if not item.startswith("assumption_min:")
        ]
    )
    return {
        "required_count": required_count,
        "covered_count": max(0, covered_count),
        "assumption_count": len(assumption_ids),
        "stale_assumption_count": counts["stale_assumptions"],
        "stale_evidence_count": counts["stale_evidence"],
        "verification_gap_count": counts["verification_gaps"],
        "due_revisit_count": counts["due_revisits"],
        "missing_ids": missing,
        "passed": not missing and not expectation_failures,
    }


def _runtime_performance_metric(
    scenario: EvaluationScenario,
    runtime: ScenarioRuntime,
    bundle: dict[str, Any],
    *,
    total_seconds: float,
    load_runtime_seconds: float,
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = scenario.expected.get("performance", {})
    max_total_seconds = expected.get("max_total_seconds")
    max_load_runtime_seconds = expected.get("max_load_runtime_seconds")
    expectation_failures = []
    if max_total_seconds is not None and total_seconds > max_total_seconds:
        expectation_failures.append(
            {
                "threshold": "max_total_seconds",
                "expected": max_total_seconds,
                "actual": total_seconds,
            }
        )
    if max_load_runtime_seconds is not None and load_runtime_seconds > max_load_runtime_seconds:
        expectation_failures.append(
            {
                "threshold": "max_load_runtime_seconds",
                "expected": max_load_runtime_seconds,
                "actual": load_runtime_seconds,
            }
        )
    if expectation_failures:
        failures.append(
            _failure(
                "runtime_performance",
                "Runtime performance thresholds were exceeded.",
                "$.metrics.runtime_performance",
                expected=expected,
                actual=expectation_failures,
            )
        )
    project_state = bundle["project_state"]
    objects = project_state.get("objects", [])
    return {
        "total_seconds": round(total_seconds, 6),
        "load_runtime_seconds": round(load_runtime_seconds, 6),
        "event_count": project_state["state"]["event_count"],
        "session_count": len(runtime.session_ids),
        "object_count": len(objects),
        "decision_count": len([obj for obj in objects if obj.get("type") == "decision"]),
        "max_total_seconds": max_total_seconds,
        "max_load_runtime_seconds": max_load_runtime_seconds,
        "passed": not expectation_failures,
    }


def _document_has_source_traceability(document: dict[str, Any]) -> bool:
    source = document.get("source", {})
    has_document_source = bool(source.get("object_ids")) and bool(source.get("link_ids"))
    sections_by_id = {section["id"]: section for section in document.get("sections", [])}
    trace_section = sections_by_id.get("source-traceability")
    if trace_section is not None:
        return has_document_source and _section_has_content(trace_section)
    return has_document_source


def _section_has_content(section: dict[str, Any]) -> bool:
    for block in section.get("blocks", []):
        block_type = block.get("type")
        if block_type == "text" and str(block.get("text") or "").strip():
            return True
        if block_type == "list" and block.get("items"):
            return True
        if block_type == "table" and block.get("rows"):
            return True
        if block_type == "object_refs" and block.get("object_ids"):
            return True
        if block_type == "callout" and str(block.get("text") or "").strip():
            return True
    return False


def _failure(
    metric: str,
    message: str,
    path: str,
    *,
    expected: Any | None = None,
    actual: Any | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "metric": metric,
        "message": message,
        "path": path,
    }
    if expected is not None:
        payload["expected"] = expected
    if actual is not None:
        payload["actual"] = actual
    return payload


def _objects_by_id(project_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {obj["id"]: obj for obj in project_state.get("objects", [])}


def _is_live_object(obj: dict[str, Any]) -> bool:
    return obj.get("status") != "invalidated"


def _count_expectation_satisfied(expectation: dict[str, Any], actual_count: int) -> bool:
    expected_count = expectation["count"]
    if expectation["mode"] == "exact":
        return actual_count == expected_count
    return actual_count >= expected_count


def _scenario_session_ids(scenario: EvaluationScenario) -> list[str]:
    return [session["session_id"] for session in scenario.sessions]


def _domain_pack_classification(pack: Any, updated_at: str) -> dict[str, Any]:
    return {
        "domain": pack.default_core_domain,
        "abstraction_level": None,
        "domain_pack_id": pack.pack_id,
        "domain_pack_version": pack.version,
        "domain_pack_digest": domain_pack_digest(pack),
        "assigned_tags": [],
        "search_terms": [],
        "source_refs": [],
        "updated_at": updated_at,
    }


def _tx_id(scenario: EvaluationScenario, index: int | str) -> str:
    suffix = f"{index:04d}" if isinstance(index, int) else index
    return f"T-eval-{scenario.scenario_id}-{suffix}"


def _event_id(scenario: EvaluationScenario, suffix: str) -> str:
    return f"E-eval-{scenario.scenario_id}-{suffix}"


def _close_id_suffix(index: int, session_id: str) -> str:
    digest = hashlib.sha1(session_id.encode("utf-8")).hexdigest()[:8]
    return f"close-{index:04d}-{digest}"


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _looks_like_windows_absolute_path(value: str) -> bool:
    return len(value) >= 3 and value[1:3] == ":/" and value[0].isalpha()


def _format_checker() -> FormatChecker:
    checker = FormatChecker()

    @checker.checks("date-time", raises=ValueError)
    def is_date_time(value: object) -> bool:
        if not isinstance(value, str):
            return True
        _parse_timestamp(value)
        return True

    return checker


def _format_schema_error(error: Any) -> str:
    path = "$"
    for part in error.absolute_path:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}"
    return f"{path}: {error.message}"
