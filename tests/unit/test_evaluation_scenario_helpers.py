from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import yaml

from decide_me.domains import domain_pack_digest, load_builtin_packs
from decide_me.lifecycle import close_session
from decide_me.store import load_runtime, read_event_log, runtime_paths
from tests.helpers.evaluation_assertions import validate_evaluation_report
from tests.helpers.evaluation_scenarios import (
    build_scenario_runtime,
    load_scenario,
    run_scenario_evaluation,
)
from tests.helpers.snapshot_normalization import stable_json


class EvaluationScenarioHelperTests(unittest.TestCase):
    def test_loader_accepts_valid_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_scenario_fixture(root, _valid_scenario())

            scenario = load_scenario(root / "scenario.yaml")

            self.assertEqual("generic_minimal", scenario.scenario_id)
            self.assertEqual(root.resolve() / "events.jsonl", scenario.seed_paths["S-generic-minimal"])

    def test_loader_rejects_invalid_schema_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _valid_scenario()
            del payload["evaluation"]["expected_documents"]
            _write_scenario_fixture(root, payload)

            with self.assertRaisesRegex(ValueError, "invalid evaluation scenario"):
                load_scenario(root / "scenario.yaml")

    def test_runtime_builder_uses_requested_session_ids_and_closes_marked_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            work = Path(tmp) / "work"
            _write_scenario_fixture(root, _valid_scenario())
            scenario = load_scenario(root / "scenario.yaml")

            runtime = build_scenario_runtime(scenario, work)

            self.assertIn("S-generic-minimal", runtime.bundle["sessions"])
            self.assertEqual(["S-generic-minimal"], runtime.closed_session_ids)
            self.assertEqual(
                "closed",
                runtime.bundle["sessions"]["S-generic-minimal"]["session"]["lifecycle"]["status"],
            )
            self.assertGreater(runtime.bundle["project_state"]["state"]["event_count"], 1)
            self.assertEqual(
                "S-generic-minimal",
                [
                    event
                    for event in read_event_log(runtime_paths(runtime.ai_dir))
                    if event["event_type"] == "session_created"
                ][0]["session_id"],
            )

    def test_runtime_builder_close_output_is_deterministic_across_builds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            _write_scenario_fixture(root, _valid_scenario())
            scenario = load_scenario(root / "scenario.yaml")

            first = build_scenario_runtime(scenario, Path(tmp) / "work-a")
            second = build_scenario_runtime(scenario, Path(tmp) / "work-b")

            self.assertEqual(
                stable_json(first.bundle["project_state"]),
                stable_json(second.bundle["project_state"]),
            )
            self.assertEqual(
                stable_json(first.bundle["sessions"]),
                stable_json(second.bundle["sessions"]),
            )

    def test_close_session_accepts_deterministic_now_and_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            work = Path(tmp) / "work"
            payload = _valid_scenario()
            payload["sessions"][0]["close"] = False
            _write_scenario_fixture(root, payload)
            scenario = load_scenario(root / "scenario.yaml")
            runtime = build_scenario_runtime(scenario, work)

            close_session(
                str(runtime.ai_dir),
                "S-generic-minimal",
                now="2026-04-29T02:30:00Z",
                tx_id="T-close-fixed",
                event_id_prefix="E-close-fixed",
            )
            events = [event for event in read_event_log(runtime_paths(runtime.ai_dir)) if event["tx_id"] == "T-close-fixed"]
            bundle = load_runtime(runtime_paths(runtime.ai_dir))
            action = [
                obj
                for obj in bundle["project_state"]["objects"]
                if obj["type"] == "action"
            ][0]

            self.assertEqual(
                ["E-close-fixed-0001", "E-close-fixed-0002", "E-close-fixed-0003", "E-close-fixed-0004"],
                [event["event_id"] for event in events],
            )
            self.assertTrue(all(event["ts"] == "2026-04-29T02:30:00Z" for event in events))
            self.assertEqual("2026-04-29T02:30:00Z", action["created_at"])
            self.assertEqual(["E-close-fixed-0001"], action["source_event_ids"])

    def test_evaluation_report_passes_for_minimal_generic_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            work = Path(tmp) / "work"
            _write_scenario_fixture(root, _valid_scenario())
            scenario = load_scenario(root / "scenario.yaml")
            runtime = build_scenario_runtime(scenario, work)

            report = run_scenario_evaluation(scenario, runtime)

            self.assertEqual([], validate_evaluation_report(report))
            self.assertEqual("passed", report["status"])

    def test_question_efficiency_probe_fails_when_advance_session_asks_too_many_questions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            work = Path(tmp) / "work"
            payload = _valid_scenario()
            payload["sessions"][0]["close"] = False
            payload["evaluation"]["expected_decision_coverage"]["required_status_counts"] = [
                {"status": "unresolved", "mode": "exact", "count": 1}
            ]
            payload["evaluation"]["expected_questions"] = {
                "max_questions": 0,
                "forbidden_repeated_decision_types": [],
                "probe_session_ids": ["S-generic-minimal"],
                "advance_steps": 1,
            }
            _write_scenario_fixture(
                root,
                payload,
                seed_events=_unresolved_decision_seed("E-seed-decision", "DEC-choice"),
            )
            scenario = load_scenario(root / "scenario.yaml")
            runtime = build_scenario_runtime(scenario, work)

            report = run_scenario_evaluation(scenario, runtime)

            self.assertEqual([], validate_evaluation_report(report))
            self.assertEqual("failed", report["status"])
            self.assertIn("question_efficiency", {item["metric"] for item in report["failures"]})

    def test_question_efficiency_probe_detects_repeated_forbidden_decision_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            work = Path(tmp) / "work"
            payload = _valid_scenario()
            payload["sessions"] = [
                {
                    "session_id": "S-probe-a",
                    "context": "Choose option A.",
                    "seed_events": "events-a.jsonl",
                    "close": False,
                },
                {
                    "session_id": "S-probe-b",
                    "context": "Choose option B.",
                    "seed_events": "events-b.jsonl",
                    "close": False,
                },
            ]
            payload["evaluation"]["expected_decision_coverage"]["required_status_counts"] = [
                {"status": "unresolved", "mode": "exact", "count": 2}
            ]
            payload["evaluation"]["expected_questions"] = {
                "max_questions": 4,
                "forbidden_repeated_decision_types": ["choose_option"],
                "probe_session_ids": ["S-probe-a", "S-probe-b"],
                "advance_steps": 1,
            }
            _write_scenario_fixture(
                root,
                payload,
                seed_events={
                    "events-a.jsonl": _unresolved_decision_seed("E-seed-a", "DEC-choice-a"),
                    "events-b.jsonl": _unresolved_decision_seed("E-seed-b", "DEC-choice-b"),
                },
            )
            scenario = load_scenario(root / "scenario.yaml")
            runtime = build_scenario_runtime(scenario, work)

            report = run_scenario_evaluation(scenario, runtime)

            self.assertEqual([], validate_evaluation_report(report))
            self.assertEqual("failed", report["status"])
            question_metric = report["metrics"]["question_efficiency"]
            self.assertEqual(["choose_option"], question_metric["repeated_forbidden_decision_types"])

    def test_document_source_traceability_expectation_passes_and_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            work = Path(tmp) / "work"
            payload = _valid_scenario()
            payload["evaluation"]["expected_documents"] = [
                {
                    "type": "decision-brief",
                    "format": "json",
                    "required_sections": ["source-traceability"],
                    "require_source_traceability": True,
                }
            ]
            _write_scenario_fixture(root, payload)
            scenario = load_scenario(root / "scenario.yaml")
            runtime = build_scenario_runtime(scenario, work)

            self.assertEqual("passed", run_scenario_evaluation(scenario, runtime)["status"])

            failing = deepcopy(payload)
            failing["evaluation"]["expected_documents"] = [
                {
                    "type": "risk-register",
                    "format": "json",
                    "required_sections": ["summary"],
                    "require_source_traceability": True,
                }
            ]
            _write_scenario_fixture(root, failing)
            failing_scenario = load_scenario(root / "scenario.yaml")
            failing_runtime = build_scenario_runtime(failing_scenario, Path(tmp) / "work-trace-fail")

            report = run_scenario_evaluation(failing_scenario, failing_runtime)

            self.assertEqual([], validate_evaluation_report(report))
            self.assertEqual("failed", report["status"])
            self.assertIn("document_readability", {item["metric"] for item in report["failures"]})

    def test_plan_executability_expectation_fails_when_expected_counts_do_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            work = Path(tmp) / "work"
            payload = _valid_scenario()
            payload["evaluation"]["expected_plan_executability"] = {
                "readiness": "blocked",
                "min_implementation_ready_count": 2,
            }
            _write_scenario_fixture(root, payload)
            scenario = load_scenario(root / "scenario.yaml")
            runtime = build_scenario_runtime(scenario, work)

            report = run_scenario_evaluation(scenario, runtime)

            self.assertEqual([], validate_evaluation_report(report))
            self.assertEqual("failed", report["status"])
            self.assertIn("plan_executability", {item["metric"] for item in report["failures"]})

    def test_revisit_quality_expectation_fails_when_due_count_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            work = Path(tmp) / "work"
            payload = _valid_scenario()
            payload["evaluation"]["expected_revisit_quality"] = {"mode": "exact", "count": 1}
            _write_scenario_fixture(root, payload)
            scenario = load_scenario(root / "scenario.yaml")
            runtime = build_scenario_runtime(scenario, work)

            report = run_scenario_evaluation(scenario, runtime)

            self.assertEqual([], validate_evaluation_report(report))
            self.assertEqual("failed", report["status"])
            self.assertIn("revisit_quality", {item["metric"] for item in report["failures"]})

    def test_evaluation_report_fails_with_schema_shaped_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            work = Path(tmp) / "work"
            payload = _valid_scenario()
            payload["evaluation"]["expected_decision_coverage"]["required_domain_decision_types"] = [
                "plan_verification"
            ]
            payload["evaluation"]["expected_evidence_coverage"] = {
                "min_supporting_evidence": 1,
                "required_evidence_requirement_ids": ["project_brief"],
            }
            payload["evaluation"]["expected_risks"] = {
                "required_domain_risk_types": ["major_failure"],
                "required_risk_tiers": ["high"],
                "min_high_or_critical_risks": 1,
            }
            _write_scenario_fixture(root, payload)
            scenario = load_scenario(root / "scenario.yaml")
            runtime = build_scenario_runtime(scenario, work)

            report = run_scenario_evaluation(scenario, runtime)

            self.assertEqual([], validate_evaluation_report(report))
            self.assertEqual("failed", report["status"])
            self.assertIn("decision_completeness", {item["metric"] for item in report["failures"]})
            self.assertIn("evidence_coverage", {item["metric"] for item in report["failures"]})
            self.assertIn("risk_coverage", {item["metric"] for item in report["failures"]})

    def test_runtime_builder_rejects_seed_session_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            work = Path(tmp) / "work"
            _write_scenario_fixture(
                root,
                _valid_scenario(),
                seed_events=[{"session_id": "S-other", "event_type": "object_recorded", "payload": {}}],
            )
            scenario = load_scenario(root / "scenario.yaml")

            with self.assertRaisesRegex(ValueError, "does not match scenario session"):
                build_scenario_runtime(scenario, work)


def _write_scenario_fixture(
    root: Path,
    payload: dict,
    *,
    seed_events: list[dict] | dict[str, list[dict]] | None = None,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "scenario.yaml").write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    if isinstance(seed_events, dict):
        for filename, rows in seed_events.items():
            _write_jsonl(root / filename, rows)
        return
    rows = seed_events if seed_events is not None else _seed_events("S-generic-minimal")
    _write_jsonl(root / "events.jsonl", rows)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _valid_scenario() -> dict:
    return {
        "schema_version": 1,
        "scenario_id": "generic_minimal",
        "label": "Generic minimal scenario",
        "domain_pack": "generic",
        "project": {
            "name": "Demo",
            "objective": "Choose a simple option.",
            "current_milestone": "Pick option",
        },
        "sessions": [
            {
                "session_id": "S-generic-minimal",
                "context": "Choose a simple option.",
                "seed_events": "events.jsonl",
                "close": True,
            }
        ],
        "evaluation": {
            "now": "2026-04-29T00:00:00Z",
            "expected_decision_coverage": {
                "required_domain_decision_types": ["choose_option"],
                "required_status_counts": [
                    {"status": "accepted", "mode": "exact", "count": 1},
                ],
            },
            "expected_questions": {
                "max_questions": 0,
                "forbidden_repeated_decision_types": [],
            },
            "expected_evidence_coverage": {
                "min_supporting_evidence": 0,
                "required_evidence_requirement_ids": [],
            },
            "expected_risks": {
                "required_domain_risk_types": [],
                "min_high_or_critical_risks": 0,
            },
            "expected_conflicts": {
                "count": 0,
            },
            "expected_documents": [],
        },
    }


def _seed_events(session_id: str) -> list[dict]:
    created_at = "2026-04-29T00:20:00Z"
    decision_metadata = _generic_decision_metadata()
    decision = _object_event(
        "E-seed-decision",
        "DEC-choice",
        "decision",
        "accepted",
        "Choose the option.",
        decision_metadata,
        created_at,
    )
    proposal = _object_event(
        "E-seed-proposal",
        "PRO-choice",
        "proposal",
        "accepted",
        "Use the smallest viable option.",
        {"origin_session_id": session_id},
        created_at,
    )
    option = _object_event(
        "E-seed-option",
        "OPT-smallest",
        "option",
        "active",
        "The smallest viable option.",
        {},
        created_at,
    )
    return [
        decision,
        proposal,
        option,
        _link_event(
            "E-seed-link-addresses",
            "L-PRO-choice-addresses-DEC-choice",
            "PRO-choice",
            "addresses",
            "DEC-choice",
            created_at,
        ),
        _link_event(
            "E-seed-link-accepts",
            "L-DEC-choice-accepts-PRO-choice",
            "DEC-choice",
            "accepts",
            "PRO-choice",
            created_at,
        ),
        _link_event(
            "E-seed-link-recommends",
            "L-PRO-choice-recommends-OPT-smallest",
            "PRO-choice",
            "recommends",
            "OPT-smallest",
            created_at,
        ),
    ]


def _unresolved_decision_seed(event_id: str, decision_id: str) -> list[dict]:
    metadata = _generic_decision_metadata()
    metadata["priority"] = "P0"
    return [
        _object_event(
            event_id,
            decision_id,
            "decision",
            "unresolved",
            "Choose the option.",
            metadata,
            "2026-04-29T00:20:00Z",
        )
    ]


def _generic_decision_metadata() -> dict:
    pack = load_builtin_packs()["generic"]
    return {
        "priority": "P1",
        "frontier": "now",
        "reversibility": "reversible",
        "domain_pack_id": pack.pack_id,
        "domain_pack_version": pack.version,
        "domain_pack_digest": domain_pack_digest(pack),
        "domain_decision_type": "choose_option",
        "domain_criteria": ["fitness", "tradeoff_visibility"],
    }


def _object_event(
    event_id: str,
    object_id: str,
    object_type: str,
    status: str,
    body: str,
    metadata: dict,
    created_at: str,
) -> dict:
    return {
        "event_id": event_id,
        "event_type": "object_recorded",
        "payload": {
            "object": {
                "id": object_id,
                "type": object_type,
                "title": object_id,
                "body": body,
                "status": status,
                "created_at": created_at,
                "updated_at": None,
                "source_event_ids": [event_id],
                "metadata": deepcopy(metadata),
            }
        },
    }


def _link_event(
    event_id: str,
    link_id: str,
    source: str,
    relation: str,
    target: str,
    created_at: str,
) -> dict:
    return {
        "event_id": event_id,
        "event_type": "object_linked",
        "payload": {
            "link": {
                "id": link_id,
                "source_object_id": source,
                "relation": relation,
                "target_object_id": target,
                "rationale": "Scenario fixture link.",
                "created_at": created_at,
                "source_event_ids": [event_id],
            }
        },
    }


if __name__ == "__main__":
    unittest.main()
