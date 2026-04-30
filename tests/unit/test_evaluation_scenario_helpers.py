from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import yaml

from decide_me.domains import domain_pack_digest, load_builtin_packs
from decide_me.store import read_event_log, runtime_paths
from tests.helpers.evaluation_assertions import validate_evaluation_report
from tests.helpers.evaluation_scenarios import (
    build_scenario_runtime,
    load_scenario,
    run_scenario_evaluation,
)


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
    seed_events: list[dict] | None = None,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "scenario.yaml").write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    rows = seed_events if seed_events is not None else _seed_events("S-generic-minimal")
    (root / "events.jsonl").write_text(
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
