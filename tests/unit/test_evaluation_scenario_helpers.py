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

    def test_runtime_builder_close_ids_do_not_collide_for_similar_session_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            work = Path(tmp) / "work"
            payload = _valid_scenario()
            payload["scenario_id"] = "close_id_collision"
            payload["sessions"] = [
                {
                    "session_id": "S-a",
                    "context": "Close session A.",
                    "seed_events": "s-a.jsonl",
                    "close": True,
                },
                {
                    "session_id": "S_a",
                    "context": "Close session underscore.",
                    "seed_events": "s_underscore.jsonl",
                    "close": True,
                },
                {
                    "session_id": "S.a",
                    "context": "Close session dot.",
                    "seed_events": "s_dot.jsonl",
                    "close": True,
                },
            ]
            payload["evaluation"]["expected_decision_coverage"] = {
                "required_domain_decision_types": [],
                "required_status_counts": [
                    {"status": "accepted", "mode": "exact", "count": 0},
                ],
            }
            _write_scenario_fixture(
                root,
                payload,
                seed_events={
                    "s-a.jsonl": [],
                    "s_underscore.jsonl": [],
                    "s_dot.jsonl": [],
                },
            )
            scenario = load_scenario(root / "scenario.yaml")

            runtime = build_scenario_runtime(scenario, work)
            close_events = [
                event
                for event in read_event_log(runtime_paths(runtime.ai_dir))
                if event["event_type"] == "session_closed"
            ]

            self.assertEqual(["S-a", "S_a", "S.a"], runtime.closed_session_ids)
            self.assertEqual(3, len(close_events))
            self.assertEqual(3, len({event["tx_id"] for event in close_events}))
            self.assertEqual(3, len({event["event_id"] for event in close_events}))

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

    def test_evidence_coverage_requires_linked_supporting_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            work = Path(tmp) / "work"
            payload = _valid_scenario()
            payload["domain_pack"] = "research"
            payload["evaluation"]["expected_decision_coverage"] = {
                "required_domain_decision_types": ["research_question"],
                "required_status_counts": [
                    {"status": "accepted", "mode": "exact", "count": 1},
                ],
            }
            payload["evaluation"]["expected_evidence_coverage"] = {
                "min_supporting_evidence": 1,
                "required_evidence_requirement_ids": ["protocol_or_project_brief"],
            }
            _write_scenario_fixture(
                root,
                payload,
                seed_events=_research_seed_events_with_unlinked_evidence("S-generic-minimal"),
            )
            scenario = load_scenario(root / "scenario.yaml")
            runtime = build_scenario_runtime(scenario, work)

            report = run_scenario_evaluation(scenario, runtime)

            self.assertEqual([], validate_evaluation_report(report))
            self.assertEqual("failed", report["status"])
            self.assertIn("evidence_coverage", {item["metric"] for item in report["failures"]})
            self.assertIn("protocol_or_project_brief", report["metrics"]["evidence_coverage"]["missing_ids"])

    def test_invalidated_evidence_does_not_satisfy_linked_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            work = Path(tmp) / "work"
            payload = _valid_scenario()
            payload["domain_pack"] = "research"
            payload["evaluation"]["expected_decision_coverage"] = {
                "required_domain_decision_types": ["research_question"],
                "required_status_counts": [
                    {"status": "accepted", "mode": "exact", "count": 1},
                ],
            }
            payload["evaluation"]["expected_evidence_coverage"] = {
                "min_supporting_evidence": 1,
                "required_evidence_requirement_ids": ["protocol_or_project_brief"],
            }
            _write_scenario_fixture(
                root,
                payload,
                seed_events=_research_seed_events_with_invalidated_linked_evidence("S-generic-minimal"),
            )
            scenario = load_scenario(root / "scenario.yaml")
            runtime = build_scenario_runtime(scenario, work)

            report = run_scenario_evaluation(scenario, runtime)

            self.assertEqual([], validate_evaluation_report(report))
            self.assertEqual("failed", report["status"])
            self.assertIn("evidence_coverage", {item["metric"] for item in report["failures"]})
            self.assertIn("protocol_or_project_brief", report["metrics"]["evidence_coverage"]["missing_ids"])

    def test_safety_gate_negative_expectations_pass_and_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            work = Path(tmp) / "work"
            payload = _valid_scenario()
            payload["sessions"][0]["close"] = False
            payload["evaluation"]["expected_safety_gates"] = {
                "required_rule_ids": [],
                "required_approval_thresholds": [],
                "min_approval_required_count": 0,
                "max_approval_required_count": 0,
                "required_insufficient_evidence_ids": [],
                "forbidden_rule_ids": [],
                "forbidden_approval_thresholds": ["human_review", "external_review"],
            }
            _write_scenario_fixture(root, payload)
            scenario = load_scenario(root / "scenario.yaml")
            runtime = build_scenario_runtime(scenario, work)

            passing_report = run_scenario_evaluation(scenario, runtime)

            self.assertEqual([], validate_evaluation_report(passing_report))
            self.assertEqual("passed", passing_report["status"])

            _write_scenario_fixture(
                root,
                payload,
                seed_events=_seed_events_with_human_review_risk("S-generic-minimal"),
            )
            failing_scenario = load_scenario(root / "scenario.yaml")
            failing_runtime = build_scenario_runtime(failing_scenario, Path(tmp) / "work-risk")

            failing_report = run_scenario_evaluation(failing_scenario, failing_runtime)

            self.assertEqual([], validate_evaluation_report(failing_report))
            self.assertEqual("failed", failing_report["status"])
            risk_failures = [
                item for item in failing_report["failures"] if item["metric"] == "risk_coverage"
            ]
            self.assertEqual(1, len(risk_failures))
            self.assertIn("approval_required_max:0", failing_report["metrics"]["risk_coverage"]["missing_ids"])
            self.assertIn(
                "forbidden_approval_threshold:human_review",
                failing_report["metrics"]["risk_coverage"]["missing_ids"],
            )

    def test_invalidated_risk_does_not_satisfy_risk_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            work = Path(tmp) / "work"
            payload = _valid_scenario()
            payload["evaluation"]["expected_risks"] = {
                "required_domain_risk_types": ["review_required"],
                "required_risk_tiers": ["high"],
                "min_high_or_critical_risks": 1,
            }
            _write_scenario_fixture(
                root,
                payload,
                seed_events=_seed_events_with_human_review_risk("S-generic-minimal", status="invalidated"),
            )
            scenario = load_scenario(root / "scenario.yaml")
            runtime = build_scenario_runtime(scenario, work)

            report = run_scenario_evaluation(scenario, runtime)

            self.assertEqual([], validate_evaluation_report(report))
            self.assertEqual("failed", report["status"])
            self.assertIn("risk_coverage", {item["metric"] for item in report["failures"]})
            missing = report["metrics"]["risk_coverage"]["missing_ids"]
            self.assertIn("review_required", missing)
            self.assertIn("risk_tier:high", missing)

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

    def test_plan_executability_expectation_fails_when_action_count_is_too_low(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            work = Path(tmp) / "work"
            payload = _valid_scenario()
            payload["evaluation"]["expected_plan_executability"] = {
                "readiness": "ready",
                "min_implementation_ready_count": 0,
                "min_action_count": 99,
            }
            _write_scenario_fixture(root, payload)
            scenario = load_scenario(root / "scenario.yaml")
            runtime = build_scenario_runtime(scenario, work)

            report = run_scenario_evaluation(scenario, runtime)

            self.assertEqual([], validate_evaluation_report(report))
            self.assertEqual("failed", report["status"])
            plan_metric = report["metrics"]["plan_executability"]
            self.assertGreaterEqual(plan_metric["action_count"], 1)
            self.assertIn("plan_executability", {item["metric"] for item in report["failures"]})

    def test_plan_executability_expectation_fails_when_blocker_count_is_too_high(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            work = Path(tmp) / "work"
            payload = _valid_scenario()
            payload["evaluation"]["expected_decision_coverage"]["required_domain_decision_types"] = [
                "choose_option"
            ]
            payload["evaluation"]["expected_decision_coverage"]["required_status_counts"] = [
                {"status": "unresolved", "mode": "exact", "count": 1}
            ]
            payload["evaluation"]["expected_plan_executability"] = {
                "readiness": "blocked",
                "min_implementation_ready_count": 0,
                "max_blocker_count": 0,
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
            self.assertGreater(report["metrics"]["plan_executability"]["blocker_count"], 0)
            self.assertIn("plan_executability", {item["metric"] for item in report["failures"]})

    def test_plan_executability_fails_when_required_to_have_no_unresolved_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            payload = _valid_scenario()
            payload["scenario_id"] = "plan_conflict_guard"
            payload["sessions"] = [
                {
                    "session_id": "S-conflict-a",
                    "context": "Accept the baseline option.",
                    "seed_events": "events-a.jsonl",
                    "close": True,
                },
                {
                    "session_id": "S-conflict-b",
                    "context": "Accept a conflicting option.",
                    "seed_events": "events-b.jsonl",
                    "close": True,
                },
            ]
            payload["evaluation"]["expected_decision_coverage"] = {
                "required_domain_decision_types": ["choose_option"],
                "required_status_counts": [
                    {"status": "accepted", "mode": "min", "count": 1},
                ],
            }
            payload["evaluation"]["expected_conflicts"] = {
                "count": 1,
                "required_conflict_types": ["decision-accepted-proposal-mismatch"],
            }
            payload["evaluation"]["expected_plan_executability"] = {
                "readiness": "ready",
                "min_implementation_ready_count": 0,
                "min_action_count": 1,
                "max_blocker_count": 0,
                "require_no_unresolved_conflicts": True,
            }
            _write_scenario_fixture(
                root,
                payload,
                seed_events={
                    "events-a.jsonl": _conflicting_proposal_seed(
                        "S-conflict-a",
                        variant="a",
                        include_decision=True,
                    ),
                    "events-b.jsonl": _conflicting_proposal_seed(
                        "S-conflict-b",
                        variant="b",
                        include_decision=False,
                    ),
                },
            )
            scenario = load_scenario(root / "scenario.yaml")
            runtime = build_scenario_runtime(scenario, Path(tmp) / "work-conflict")

            report = run_scenario_evaluation(scenario, runtime)

            self.assertEqual([], validate_evaluation_report(report))
            self.assertEqual("failed", report["status"])
            self.assertTrue(report["metrics"]["conflict_detection"]["passed"])
            self.assertFalse(report["metrics"]["plan_executability"]["passed"])
            self.assertEqual(1, report["metrics"]["plan_executability"]["unresolved_conflict_count"])
            self.assertIn("plan_executability", {item["metric"] for item in report["failures"]})

            opting_out = deepcopy(payload)
            opting_out["evaluation"]["expected_plan_executability"][
                "require_no_unresolved_conflicts"
            ] = False
            _write_scenario_fixture(
                root,
                opting_out,
                seed_events={
                    "events-a.jsonl": _conflicting_proposal_seed(
                        "S-conflict-a",
                        variant="a",
                        include_decision=True,
                    ),
                    "events-b.jsonl": _conflicting_proposal_seed(
                        "S-conflict-b",
                        variant="b",
                        include_decision=False,
                    ),
                },
            )
            opting_out_scenario = load_scenario(root / "scenario.yaml")
            opting_out_runtime = build_scenario_runtime(
                opting_out_scenario,
                Path(tmp) / "work-conflict-opt-out",
            )

            opting_out_report = run_scenario_evaluation(opting_out_scenario, opting_out_runtime)

            self.assertEqual([], validate_evaluation_report(opting_out_report))
            self.assertTrue(opting_out_report["metrics"]["plan_executability"]["passed"])
            self.assertEqual(
                1,
                opting_out_report["metrics"]["plan_executability"]["unresolved_conflict_count"],
            )

    def test_plan_executability_expectation_fails_without_closed_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            work = Path(tmp) / "work"
            payload = _valid_scenario()
            payload["sessions"][0]["close"] = False
            payload["evaluation"]["expected_plan_executability"] = {
                "readiness": "ready",
                "min_implementation_ready_count": 0,
            }
            _write_scenario_fixture(root, payload)
            scenario = load_scenario(root / "scenario.yaml")
            runtime = build_scenario_runtime(scenario, work)

            report = run_scenario_evaluation(scenario, runtime)

            self.assertEqual([], validate_evaluation_report(report))
            self.assertEqual("failed", report["status"])
            plan_failures = [
                item for item in report["failures"] if item["metric"] == "plan_executability"
            ]
            self.assertEqual(1, len(plan_failures))
            self.assertIn("requires at least one closed session", plan_failures[0]["message"])

    def test_revisit_quality_expectation_fails_when_due_count_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            work = Path(tmp) / "work"
            payload = _valid_scenario()
            payload["evaluation"]["expected_revisit_quality"] = {
                "stale_assumptions": {"mode": "exact", "count": 0},
                "stale_evidence": {"mode": "exact", "count": 0},
                "verification_gaps": {"mode": "exact", "count": 0},
                "due_revisits": {"mode": "exact", "count": 1},
            }
            _write_scenario_fixture(root, payload)
            scenario = load_scenario(root / "scenario.yaml")
            runtime = build_scenario_runtime(scenario, work)

            report = run_scenario_evaluation(scenario, runtime)

            self.assertEqual([], validate_evaluation_report(report))
            self.assertEqual("failed", report["status"])
            self.assertIn("revisit_quality", {item["metric"] for item in report["failures"]})

    def test_revisit_quality_expectations_cover_stale_and_gap_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scenario"
            work = Path(tmp) / "work"
            payload = _valid_scenario()
            payload["sessions"][0]["close"] = False
            payload["evaluation"]["expected_revisit_quality"] = {
                "stale_assumptions": {"mode": "exact", "count": 1},
                "stale_evidence": {"mode": "exact", "count": 1},
                "verification_gaps": {"mode": "exact", "count": 1},
                "due_revisits": {"mode": "exact", "count": 1},
            }
            _write_scenario_fixture(
                root,
                payload,
                seed_events=_seed_events_with_revisit_diagnostics("S-generic-minimal"),
            )
            scenario = load_scenario(root / "scenario.yaml")
            runtime = build_scenario_runtime(scenario, work)

            passing_report = run_scenario_evaluation(scenario, runtime)

            self.assertEqual([], validate_evaluation_report(passing_report))
            self.assertEqual("passed", passing_report["status"])
            revisit_metric = passing_report["metrics"]["revisit_quality"]
            self.assertEqual(1, revisit_metric["stale_assumption_count"])
            self.assertEqual(1, revisit_metric["stale_evidence_count"])
            self.assertEqual(1, revisit_metric["verification_gap_count"])
            self.assertEqual(1, revisit_metric["due_revisit_count"])

            failing = deepcopy(payload)
            failing["evaluation"]["expected_revisit_quality"] = {
                "stale_assumptions": {"mode": "exact", "count": 0},
                "stale_evidence": {"mode": "exact", "count": 0},
                "verification_gaps": {"mode": "exact", "count": 0},
                "due_revisits": {"mode": "exact", "count": 0},
            }
            _write_scenario_fixture(
                root,
                failing,
                seed_events=_seed_events_with_revisit_diagnostics("S-generic-minimal"),
            )
            failing_scenario = load_scenario(root / "scenario.yaml")
            failing_runtime = build_scenario_runtime(failing_scenario, Path(tmp) / "work-revisit-fail")

            failing_report = run_scenario_evaluation(failing_scenario, failing_runtime)

            self.assertEqual([], validate_evaluation_report(failing_report))
            self.assertEqual("failed", failing_report["status"])
            self.assertIn("revisit_quality", {item["metric"] for item in failing_report["failures"]})

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


def _conflicting_proposal_seed(
    session_id: str,
    *,
    variant: str,
    include_decision: bool,
) -> list[dict]:
    created_at = f"2026-04-29T00:21:0{0 if variant == 'a' else 1}Z"
    decision_id = "DEC-conflict-choice"
    proposal_id = f"PRO-conflict-{variant}"
    option_id = f"OPT-conflict-{variant}"
    events: list[dict] = []
    if include_decision:
        events.append(
            _object_event(
                f"E-conflict-{variant}-decision",
                decision_id,
                "decision",
                "accepted",
                "Choose a shared option.",
                _generic_decision_metadata(),
                created_at,
            )
        )
    events.extend(
        [
            _object_event(
                f"E-conflict-{variant}-proposal",
                proposal_id,
                "proposal",
                "accepted",
                f"Use option {variant.upper()}.",
                {"origin_session_id": session_id},
                created_at,
            ),
            _object_event(
                f"E-conflict-{variant}-option",
                option_id,
                "option",
                "active",
                f"Option {variant.upper()}.",
                {},
                created_at,
            ),
            _link_event(
                f"E-conflict-{variant}-link-addresses",
                f"L-{proposal_id}-addresses-{decision_id}",
                proposal_id,
                "addresses",
                decision_id,
                created_at,
            ),
            _link_event(
                f"E-conflict-{variant}-link-accepts",
                f"L-{decision_id}-accepts-{proposal_id}",
                decision_id,
                "accepts",
                proposal_id,
                created_at,
            ),
            _link_event(
                f"E-conflict-{variant}-link-recommends",
                f"L-{proposal_id}-recommends-{option_id}",
                proposal_id,
                "recommends",
                option_id,
                created_at,
            ),
        ]
    )
    return events


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


def _research_seed_events_with_unlinked_evidence(session_id: str) -> list[dict]:
    created_at = "2026-04-29T00:20:30Z"
    return [
        _object_event(
            "E-seed-research-decision",
            "DEC-research-question",
            "decision",
            "accepted",
            "Define the research question.",
            _research_decision_metadata(),
            created_at,
        ),
        _object_event(
            "E-seed-research-proposal",
            "PRO-research-question",
            "proposal",
            "accepted",
            "Study the retrospective cohort outcome.",
            {"origin_session_id": session_id},
            created_at,
        ),
        _object_event(
            "E-seed-research-option",
            "OPT-research-question",
            "option",
            "active",
            "Retrospective cohort outcome question.",
            {},
            created_at,
        ),
        _link_event(
            "E-seed-research-link-addresses",
            "L-PRO-research-question-addresses-DEC-research-question",
            "PRO-research-question",
            "addresses",
            "DEC-research-question",
            created_at,
        ),
        _link_event(
            "E-seed-research-link-accepts",
            "L-DEC-research-question-accepts-PRO-research-question",
            "DEC-research-question",
            "accepts",
            "PRO-research-question",
            created_at,
        ),
        _link_event(
            "E-seed-research-link-recommends",
            "L-PRO-research-question-recommends-OPT-research-question",
            "PRO-research-question",
            "recommends",
            "OPT-research-question",
            created_at,
        ),
        _object_event(
            "E-seed-unlinked-evidence",
            "EVID-project-brief",
            "evidence",
            "active",
            "Project brief exists but is not linked as support.",
            _evidence_metadata("protocol_or_project_brief", pack_id="research", freshness="current"),
            created_at,
        ),
    ]


def _research_seed_events_with_invalidated_linked_evidence(session_id: str) -> list[dict]:
    events = _research_seed_events_with_unlinked_evidence(session_id)
    for event in events:
        obj = event.get("payload", {}).get("object")
        if obj and obj.get("id") == "EVID-project-brief":
            obj["status"] = "invalidated"
            obj["body"] = "Invalidated project brief is linked but must not satisfy coverage."
    events.append(
        _link_event(
            "E-seed-invalidated-evidence-link",
            "L-EVID-project-brief-supports-DEC-research-question",
            "EVID-project-brief",
            "supports",
            "DEC-research-question",
            "2026-04-29T00:20:31Z",
        )
    )
    return events


def _seed_events_with_human_review_risk(session_id: str, *, status: str = "active") -> list[dict]:
    created_at = "2026-04-29T00:20:30Z"
    pack = load_builtin_packs()["generic"]
    return [
        *_seed_events(session_id),
        _object_event(
            "E-seed-risk",
            "RISK-high-review",
            "risk",
            status,
            "The option needs human review.",
            {
                "statement": "The option needs human review.",
                "severity": "high",
                "likelihood": "medium",
                "risk_tier": "high",
                "reversibility": "partially_reversible",
                "mitigation_object_ids": [],
                "approval_threshold": "human_review",
                "domain_pack_id": pack.pack_id,
                "domain_pack_version": pack.version,
                "domain_pack_digest": domain_pack_digest(pack),
                "domain_risk_type": "review_required",
            },
            created_at,
        ),
        _link_event(
            "E-seed-risk-link",
            "L-RISK-high-review-challenges-DEC-choice",
            "RISK-high-review",
            "challenges",
            "DEC-choice",
            created_at,
        ),
    ]


def _seed_events_with_revisit_diagnostics(session_id: str) -> list[dict]:
    created_at = "2026-04-29T00:20:30Z"
    return [
        *_seed_events(session_id),
        _object_event(
            "E-seed-action-gap",
            "ACT-diagnostic-gap",
            "action",
            "active",
            "Action intentionally lacks verification.",
            {
                "decision_id": "DEC-choice",
                "evidence_backed": False,
                "evidence_source": None,
                "implementation_ready": True,
                "kind": "execution",
                "next_step": "Perform the diagnostic action.",
                "origin_session_id": session_id,
                "priority": "P1",
                "resolvable_by": "human",
                "responsibility": "owner",
                "reversibility": "reversible",
            },
            created_at,
        ),
        _object_event(
            "E-seed-stale-assumption",
            "ASM-diagnostic-expired",
            "assumption",
            "active",
            "Expired assumption.",
            {
                "statement": "The context is still valid.",
                "confidence": "medium",
                "validation": "review",
                "invalidates_if_false": ["DEC-choice"],
                "expires_at": "2026-04-28T00:00:00Z",
                "owner": "owner",
            },
            created_at,
        ),
        _object_event(
            "E-seed-stale-evidence",
            "EVID-diagnostic-stale",
            "evidence",
            "active",
            "Stale supporting evidence.",
            _evidence_metadata(None, freshness="stale", valid_until="2026-04-28T00:00:00Z"),
            created_at,
        ),
        _object_event(
            "E-seed-revisit-due",
            "REV-diagnostic-due",
            "revisit_trigger",
            "active",
            "Due revisit.",
            {
                "trigger_type": "time",
                "condition": "Review the selected option.",
                "due_at": "2026-04-28T00:00:00Z",
                "target_object_ids": ["DEC-choice"],
            },
            created_at,
        ),
        _link_event(
            "E-seed-action-gap-link",
            "L-ACT-diagnostic-gap-addresses-DEC-choice",
            "ACT-diagnostic-gap",
            "addresses",
            "DEC-choice",
            created_at,
        ),
        _link_event(
            "E-seed-stale-assumption-link",
            "L-ASM-diagnostic-expired-constrains-DEC-choice",
            "ASM-diagnostic-expired",
            "constrains",
            "DEC-choice",
            created_at,
        ),
        _link_event(
            "E-seed-stale-evidence-link",
            "L-EVID-diagnostic-stale-supports-DEC-choice",
            "EVID-diagnostic-stale",
            "supports",
            "DEC-choice",
            created_at,
        ),
        _link_event(
            "E-seed-revisit-due-link",
            "L-REV-diagnostic-due-revisits-DEC-choice",
            "REV-diagnostic-due",
            "revisits",
            "DEC-choice",
            created_at,
        ),
    ]


def _evidence_metadata(
    requirement_id: str | None,
    *,
    pack_id: str = "generic",
    freshness: str,
    valid_until: str | None = None,
) -> dict:
    metadata = {
        "source": "docs",
        "source_ref": "fixture.md",
        "summary": "Fixture evidence.",
        "confidence": "high",
        "freshness": freshness,
        "observed_at": "2026-04-29T00:20:30Z",
        "valid_until": valid_until,
    }
    if requirement_id is None:
        return metadata
    pack = load_builtin_packs()[pack_id]
    metadata.update({
        "domain_pack_id": pack.pack_id,
        "domain_pack_version": pack.version,
        "domain_pack_digest": domain_pack_digest(pack),
        "domain_evidence_type": requirement_id,
        "evidence_requirement_id": requirement_id,
    })
    return metadata


def _research_decision_metadata() -> dict:
    pack = load_builtin_packs()["research"]
    return {
        "priority": "P0",
        "frontier": "now",
        "reversibility": "reversible",
        "domain_pack_id": pack.pack_id,
        "domain_pack_version": pack.version,
        "domain_pack_digest": domain_pack_digest(pack),
        "domain_decision_type": "research_question",
        "domain_criteria": ["scientific_validity", "clinical_or_business_relevance", "feasibility"],
    }


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
