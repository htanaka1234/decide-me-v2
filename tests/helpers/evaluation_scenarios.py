from __future__ import annotations

import hashlib
import json
import shutil
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
from decide_me.registers import build_evidence_register, build_risk_register
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


@dataclass(frozen=True)
class EvaluationScenario:
    data: dict[str, Any]
    path: Path
    root: Path
    seed_paths: dict[str, Path]

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
    seed_paths = {
        session["session_id"]: _resolve_seed_path(scenario_root, session["seed_events"])
        for session in raw["sessions"]
    }
    return EvaluationScenario(
        data=raw,
        path=scenario_path,
        root=scenario_root,
        seed_paths=seed_paths,
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
    ai_dir = runtime.ai_dir
    bundle = rebuild_and_persist(ai_dir)
    events = read_event_log(runtime_paths(ai_dir))
    project_state = bundle["project_state"]
    evaluation = scenario.evaluation
    failures: list[dict[str, Any]] = []

    validation_issues = validate_runtime(ai_dir)
    metrics = {
        "question_efficiency": _question_efficiency_metric(scenario, runtime, failures),
        "decision_completeness": _decision_completeness_metric(scenario, project_state, failures),
        "evidence_coverage": _evidence_coverage_metric(scenario, project_state, failures),
        "risk_coverage": _risk_and_safety_metric(scenario, runtime, project_state, failures),
        "conflict_detection": _conflict_detection_metric(scenario, runtime, bundle, failures),
        "plan_executability": _plan_executability_metric(scenario, runtime, bundle, failures),
        "document_readability": _document_readability_metric(scenario, runtime, failures),
        "revisit_quality": _revisit_quality_metric(scenario, project_state, evaluation["now"], failures),
    }
    if validation_issues:
        metrics["plan_executability"]["passed"] = False
        failures.append(
            _failure(
                "plan_executability",
                "Runtime validation reported issues.",
                "$.runtime.validation",
                expected=[],
                actual=validation_issues,
            )
        )

    return {
        "schema_version": 1,
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
    expected = scenario.evaluation["expected_questions"]
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


def _decision_completeness_metric(
    scenario: EvaluationScenario,
    project_state: dict[str, Any],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = scenario.evaluation["expected_decision_coverage"]
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
                "decision_completeness",
                "Missing required decision coverage.",
                "$.metrics.decision_completeness",
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


def _evidence_coverage_metric(
    scenario: EvaluationScenario,
    project_state: dict[str, Any],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = scenario.evaluation["expected_evidence_coverage"]
    register = build_evidence_register(project_state)
    objects_by_id = _objects_by_id(project_state)
    linked_evidence_items = [
        item
        for item in register["items"]
        if _is_live_object(item) and (item.get("supports_object_ids") or item.get("verifies_object_ids"))
    ]
    supporting_count = len(linked_evidence_items)
    actual_requirement_ids = {
        objects_by_id.get(item["object_id"], {}).get("metadata", {}).get("evidence_requirement_id")
        for item in linked_evidence_items
        if objects_by_id.get(item["object_id"], {}).get("metadata", {}).get("evidence_requirement_id")
    }
    missing = [
        requirement_id
        for requirement_id in expected["required_evidence_requirement_ids"]
        if requirement_id not in actual_requirement_ids
    ]
    if supporting_count < expected["min_supporting_evidence"]:
        missing.append(f"supporting_evidence_min:{expected['min_supporting_evidence']}")

    required_count = len(expected["required_evidence_requirement_ids"])
    covered_count = required_count - len(
        [
            item
            for item in missing
            if not item.startswith("supporting_evidence_min:")
        ]
    )
    passed = not missing
    if missing:
        failures.append(
            _failure(
                "evidence_coverage",
                "Missing required evidence coverage.",
                "$.metrics.evidence_coverage",
                expected=expected,
                actual={
                    "supporting_evidence_requirement_ids": sorted(actual_requirement_ids),
                    "supporting_evidence": supporting_count,
                },
            )
        )
    return {
        "required_count": required_count,
        "covered_count": covered_count,
        "missing_ids": missing,
        "passed": passed,
    }


def _risk_and_safety_metric(
    scenario: EvaluationScenario,
    runtime: ScenarioRuntime,
    project_state: dict[str, Any],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_risks = scenario.evaluation["expected_risks"]
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
    expected_safety = scenario.evaluation.get("expected_safety_gates")
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


def _conflict_detection_metric(
    scenario: EvaluationScenario,
    runtime: ScenarioRuntime,
    bundle: dict[str, Any],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = scenario.evaluation["expected_conflicts"]
    conflicts = _scenario_conflicts(runtime, bundle)
    actual_ids = sorted(conflict["conflict_id"] for conflict in conflicts)
    actual_types = sorted(
        {
            conflict_type
            for conflict in conflicts
            if (conflict_type := conflict.get("conflict_type") or conflict.get("kind"))
        }
    )
    required_ids = expected.get("required_conflict_ids", [])
    required_types = expected.get("required_conflict_types", [])
    missing_ids = [conflict_id for conflict_id in required_ids if conflict_id not in actual_ids]
    missing_types = [conflict_type for conflict_type in required_types if conflict_type not in actual_types]
    unexpected_ids = []
    if len(conflicts) != expected["count"]:
        unexpected_ids = actual_ids
    passed = len(conflicts) == expected["count"] and not missing_ids and not missing_types
    if not passed:
        failures.append(
            _failure(
                "conflict_detection",
                "Conflict diagnostics did not match expectations.",
                "$.metrics.conflict_detection",
                expected=expected,
                actual={
                    "count": len(conflicts),
                    "conflict_ids": actual_ids,
                    "conflict_types": actual_types,
                },
            )
        )
    return {
        "expected_count": expected["count"],
        "actual_count": len(conflicts),
        "missing_conflict_ids": sorted([*missing_ids, *[f"type:{item}" for item in missing_types]]),
        "unexpected_conflict_ids": unexpected_ids,
        "passed": passed,
    }


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


def _plan_executability_metric(
    scenario: EvaluationScenario,
    runtime: ScenarioRuntime,
    bundle: dict[str, Any],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    closed_sessions = [
        bundle["sessions"][session_id]
        for session_id in runtime.closed_session_ids
        if session_id in bundle["sessions"]
    ]
    expected = scenario.evaluation.get("expected_plan_executability")
    if not closed_sessions:
        if expected is not None:
            failures.append(
                _failure(
                    "plan_executability",
                    "Plan executability requires at least one closed session.",
                    "$.metrics.plan_executability",
                    expected=expected,
                    actual={"closed_session_count": 0},
                )
            )
            return {
                "readiness": "blocked",
                "action_count": 0,
                "implementation_ready_count": 0,
                "blocker_count": 0,
                "passed": False,
            }
        return {
            "readiness": "ready",
            "action_count": 0,
            "implementation_ready_count": 0,
            "blocker_count": 0,
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
                "plan_executability",
                "Action plan assembly failed.",
                "$.metrics.plan_executability",
                expected="action plan",
                actual=str(exc),
            )
        )
        return {
            "readiness": "blocked",
            "action_count": 0,
            "implementation_ready_count": 0,
            "blocker_count": 0,
            "passed": False,
        }
    readiness = action_plan["readiness"]
    action_count = len(action_plan["actions"])
    implementation_ready_count = len(action_plan["implementation_ready_actions"])
    blocker_count = len(action_plan["blockers"])
    expectation_failures: list[str] = []
    if expected is not None:
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
        if expectation_failures:
            failures.append(
                _failure(
                    "plan_executability",
                    "Action plan executability did not match expectations.",
                    "$.metrics.plan_executability",
                    expected=expected,
                    actual={
                        "readiness": readiness,
                        "action_count": action_count,
                        "implementation_ready_count": implementation_ready_count,
                        "blocker_count": blocker_count,
                        "failed_expectations": expectation_failures,
                    },
                )
            )
    return {
        "readiness": readiness,
        "action_count": action_count,
        "implementation_ready_count": implementation_ready_count,
        "blocker_count": blocker_count,
        "passed": not expectation_failures,
    }


def _document_readability_metric(
    scenario: EvaluationScenario,
    runtime: ScenarioRuntime,
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_documents = scenario.evaluation["expected_documents"]
    missing_sections: list[str] = []
    empty_sections: list[str] = []
    missing_traceability: list[str] = []
    for expected in expected_documents:
        try:
            document = compile_document(
                runtime.ai_dir,
                document_type=expected["type"],
                session_ids=runtime.closed_session_ids,
                domain_pack_id=scenario.domain_pack,
                now=scenario.evaluation["now"],
            )
        except Exception as exc:
            failures.append(
                _failure(
                    "document_readability",
                    f"Document compilation failed for {expected['type']}.",
                    "$.metrics.document_readability",
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
                "document_readability",
                "Document required sections or source traceability were missing or empty.",
                "$.metrics.document_readability",
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


def _revisit_quality_metric(
    scenario: EvaluationScenario,
    project_state: dict[str, Any],
    now: str,
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
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
    expected = scenario.evaluation.get("expected_revisit_quality")
    expectation_failures: list[dict[str, Any]] = []
    if expected is not None:
        for key, actual_count in counts.items():
            expectation = expected[key]
            if not _count_expectation_satisfied(expectation, actual_count):
                expectation_failures.append(
                    {
                        "diagnostic": key,
                        "mode": expectation["mode"],
                        "expected": expectation["count"],
                        "actual": actual_count,
                    }
                )
        if expectation_failures:
            failures.append(
                _failure(
                    "revisit_quality",
                    "Stale or revisit diagnostics did not match expectations.",
                    "$.metrics.revisit_quality",
                    expected=expected,
                    actual={
                        **counts,
                        "failed_expectations": expectation_failures,
                    },
                )
            )
    return {
        "stale_assumption_count": counts["stale_assumptions"],
        "stale_evidence_count": counts["stale_evidence"],
        "verification_gap_count": counts["verification_gaps"],
        "due_revisit_count": counts["due_revisits"],
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
