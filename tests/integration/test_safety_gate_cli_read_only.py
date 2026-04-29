from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jsonschema import Draft202012Validator

from decide_me.domains import domain_pack_digest, load_builtin_packs
from decide_me.lifecycle import create_session
from decide_me.store import bootstrap_runtime, rebuild_and_persist, transact
from tests.helpers.impact_runtime import event_hash_snapshot, load_schema, run_json_cli, runtime_state_snapshot
from tests.helpers.typed_metadata import assumption_metadata, evidence_metadata, risk_metadata


class SafetyGateCliReadOnlyTests(unittest.TestCase):
    def test_safety_gate_cli_commands_return_json_without_runtime_state_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _build_safety_gate_runtime(Path(tmp))
            validator = Draft202012Validator(load_schema("schemas/safety-gates.schema.json"))

            for args in (
                ("show-safety-gate", "--ai-dir", str(ai_dir), "--object-id", "DEC-001"),
                ("show-safety-gates", "--ai-dir", str(ai_dir)),
            ):
                with self.subTest(command=args[0]):
                    event_before = event_hash_snapshot(ai_dir)
                    runtime_before = runtime_state_snapshot(ai_dir)

                    payload = run_json_cli(*args)

                    self.assertEqual(event_before, event_hash_snapshot(ai_dir))
                    self.assertEqual(runtime_before, runtime_state_snapshot(ai_dir))
                    self.assertEqual([], list(validator.iter_errors(payload)))

            single = run_json_cli("show-safety-gate", "--ai-dir", str(ai_dir), "--object-id", "DEC-001")
            self.assertEqual("DEC-001", single["object_id"])
            self.assertEqual("needs_approval", single["gate_status"])
            self.assertEqual("sufficient", single["evidence_coverage"])
            self.assertEqual("high", single["risk_tier"])
            self.assertEqual("human_review", single["approval_threshold"])
            self.assertEqual(["EV-001"], [item["object_id"] for item in single["evidence"]])
            self.assertEqual(["AS-001"], [item["object_id"] for item in single["assumptions"]])
            self.assertEqual(["RISK-001"], [item["object_id"] for item in single["risks"]])
            self.assertEqual(
                [
                    "L-AS-001-constrains-DEC-001",
                    "L-EV-001-supports-DEC-001",
                    "L-RISK-001-challenges-DEC-001",
                ],
                single["source_link_ids"],
            )

            report = run_json_cli("show-safety-gates", "--ai-dir", str(ai_dir))
            self.assertEqual(["ACT-001", "DEC-001"], [item["object_id"] for item in report["results"]])
            self.assertEqual(2, report["summary"]["evaluated_count"])
            self.assertEqual({"needs_approval": 2}, report["summary"]["by_gate_status"])

    def test_safety_gate_cli_reports_domain_pack_overlay(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _build_domain_safety_gate_runtime(Path(tmp))

            single = run_json_cli("show-safety-gate", "--ai-dir", str(ai_dir), "--object-id", "DEC-domain")

            self.assertEqual("needs_approval", single["gate_status"])
            self.assertIn("domain_required_evidence_missing", single["approval_reasons"])
            self.assertEqual("external_review", single["approval_threshold"])
            self.assertEqual(
                ["protocol_or_project_brief", "data_dictionary"],
                [item["required_evidence_id"] for item in single["domain_requirements"]],
            )
            self.assertEqual("patient_data_external_review", single["domain_safety_rules"][0]["rule_id"])


def _build_safety_gate_runtime(tmp: Path) -> Path:
    ai_dir = tmp / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Evaluate safety gate diagnostics.",
        current_milestone="Phase 7 readiness",
    )
    session = create_session(str(ai_dir), context="Safety gate diagnostic")
    session_id = session["session"]["id"]
    transact(ai_dir, lambda _bundle: _events(session_id))
    rebuild_and_persist(ai_dir)
    return ai_dir


def _build_domain_safety_gate_runtime(tmp: Path) -> Path:
    ai_dir = tmp / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Evaluate domain safety gate diagnostics.",
        current_milestone="Phase 9 readiness",
    )
    session = create_session(str(ai_dir), context="Research primary endpoint", domain_pack_id="research")
    session_id = session["session"]["id"]
    transact(ai_dir, lambda _bundle: _domain_events(session_id))
    rebuild_and_persist(ai_dir)
    return ai_dir


def _events(session_id: str) -> list[dict]:
    object_specs = [
        ("E-safety-evidence", "EV-001", "evidence", "active", evidence_metadata(source_ref="docs/safety.md")),
        (
            "E-safety-assumption",
            "AS-001",
            "assumption",
            "active",
            assumption_metadata(
                statement="The rollout can be reviewed before release.",
                confidence="low",
                invalidates_if_false=["DEC-001"],
                owner="maintainer",
            ),
        ),
        (
            "E-safety-risk",
            "RISK-001",
            "risk",
            "open",
            risk_metadata(
                statement="The release can ship without sufficient review.",
                risk_tier="high",
                mitigation_object_ids=["ACT-001"],
                approval_threshold="human_review",
            ),
        ),
        (
            "E-safety-decision",
            "DEC-001",
            "decision",
            "unresolved",
            {"priority": "P0", "frontier": "now", "reversibility": "reversible"},
        ),
        ("E-safety-action", "ACT-001", "action", "active", {}),
    ]
    link_specs = [
        ("E-link-evidence-decision", "L-EV-001-supports-DEC-001", "EV-001", "supports", "DEC-001"),
        ("E-link-evidence-action", "L-EV-001-verifies-ACT-001", "EV-001", "verifies", "ACT-001"),
        ("E-link-assumption-decision", "L-AS-001-constrains-DEC-001", "AS-001", "constrains", "DEC-001"),
        ("E-link-risk-decision", "L-RISK-001-challenges-DEC-001", "RISK-001", "challenges", "DEC-001"),
        ("E-link-action-risk", "L-ACT-001-mitigates-RISK-001", "ACT-001", "mitigates", "RISK-001"),
    ]
    return [
        {
            "event_id": event_id,
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {"object": _object(object_id, object_type, status, event_id, metadata)},
        }
        for event_id, object_id, object_type, status, metadata in object_specs
    ] + [
        {
            "event_id": event_id,
            "session_id": session_id,
            "event_type": "object_linked",
            "payload": {"link": _link(link_id, source, relation, target, event_id)},
        }
        for event_id, link_id, source, relation, target in link_specs
    ]


def _domain_events(session_id: str) -> list[dict]:
    return [
        {
            "event_id": "E-domain-decision",
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {
                "object": _object(
                    "DEC-domain",
                    "decision",
                    "unresolved",
                    "E-domain-decision",
                    {
                        "priority": "P0",
                        "frontier": "now",
                        "reversibility": "hard-to-reverse",
                        **_research_pack_identity(),
                        "domain_decision_type": "primary_endpoint",
                        "domain_criteria": [
                            "scientific_validity",
                            "clinical_or_business_relevance",
                            "data_availability",
                        ],
                    },
                )
            },
        },
        {
            "event_id": "E-domain-risk",
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {
                "object": _object(
                    "RISK-domain",
                    "risk",
                    "open",
                    "E-domain-risk",
                    {
                        **risk_metadata(risk_tier="low", approval_threshold="none"),
                        **_research_pack_identity(),
                        "domain_risk_type": "patient_data",
                    },
                )
            },
        },
        {
            "event_id": "E-domain-link-risk",
            "session_id": session_id,
            "event_type": "object_linked",
            "payload": {
                "link": _link(
                    "L-RISK-domain-constrains-DEC-domain",
                    "RISK-domain",
                    "constrains",
                    "DEC-domain",
                    "E-domain-link-risk",
                )
            },
        },
    ]


def _object(object_id: str, object_type: str, status: str, event_id: str, metadata: dict) -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": object_id,
        "body": "Safety gate CLI read-only fixture object.",
        "status": status,
        "created_at": "2026-04-28T00:00:00Z",
        "updated_at": None,
        "source_event_ids": [event_id],
        "metadata": metadata,
    }


def _link(link_id: str, source: str, relation: str, target: str, event_id: str) -> dict:
    return {
        "id": link_id,
        "source_object_id": source,
        "relation": relation,
        "target_object_id": target,
        "rationale": "Safety gate CLI read-only fixture link.",
        "created_at": "2026-04-28T00:00:00Z",
        "source_event_ids": [event_id],
    }


def _research_pack_identity() -> dict:
    pack = load_builtin_packs()["research"]
    return {
        "domain_pack_id": pack.pack_id,
        "domain_pack_version": pack.version,
        "domain_pack_digest": domain_pack_digest(pack),
    }


if __name__ == "__main__":
    unittest.main()
