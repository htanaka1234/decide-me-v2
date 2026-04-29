from __future__ import annotations

import unittest
from copy import deepcopy

from decide_me.domains import DomainRegistry, domain_pack_digest, load_builtin_packs
from decide_me.safety_gate import build_safety_gate_report, evaluate_safety_gate
from tests.helpers.typed_metadata import assumption_metadata, evidence_metadata, risk_metadata


class SafetyGateTests(unittest.TestCase):
    def test_sufficient_evidence_passes_gate(self) -> None:
        project_state = _project_state(
            objects=[
                _object("D-001", "decision", metadata={"reversibility": "reversible"}),
                _object("E-001", "evidence", metadata=evidence_metadata(confidence="high", freshness="current")),
            ],
            links=[_link("L-E-001-supports-D-001", "E-001", "supports", "D-001")],
        )

        result = evaluate_safety_gate(project_state, "D-001")

        self.assertEqual("passed", result["gate_status"])
        self.assertEqual("sufficient", result["evidence_coverage"])
        self.assertFalse(result["approval_required"])
        self.assertEqual("none", result["risk_tier"])
        self.assertEqual([], result["blocking_reasons"])
        self.assertEqual(["L-E-001-supports-D-001"], result["source_link_ids"])

    def test_missing_evidence_without_risk_is_warning(self) -> None:
        result = evaluate_safety_gate(
            _project_state(objects=[_object("D-001", "decision")], links=[]),
            "D-001",
        )

        self.assertEqual("passed", result["gate_status"])
        self.assertEqual("insufficient", result["evidence_coverage"])
        self.assertIn("insufficient_evidence", result["warning_reasons"])
        self.assertEqual([], result["blocking_reasons"])

    def test_domain_required_evidence_missing_needs_approval(self) -> None:
        project_state = _project_state(
            objects=[
                _object(
                    "D-001",
                    "decision",
                    metadata=_research_decision_metadata("primary_endpoint"),
                ),
            ],
            links=[],
        )

        result = evaluate_safety_gate(project_state, "D-001", domain_registry=_registry())

        self.assertEqual("needs_approval", result["gate_status"])
        self.assertIn("domain_required_evidence_missing", result["approval_reasons"])
        self.assertEqual(
            ["protocol_or_project_brief", "data_dictionary"],
            [item["required_evidence_id"] for item in result["domain_requirements"]],
        )
        self.assertTrue(all(not item["satisfied"] for item in result["domain_requirements"]))
        self.assertEqual(result["domain_requirements"], result["digest_inputs"]["domain_requirements"])

    def test_domain_required_evidence_can_be_satisfied_by_requirement_or_domain_type(self) -> None:
        project_state = _project_state(
            objects=[
                _object(
                    "D-001",
                    "decision",
                    metadata=_research_decision_metadata("primary_endpoint"),
                ),
                _object(
                    "E-001",
                    "evidence",
                    metadata={
                        **evidence_metadata(source_ref="docs/protocol.md"),
                        **_research_pack_identity(),
                        "evidence_requirement_id": "protocol_or_project_brief",
                    },
                ),
                _object(
                    "E-002",
                    "evidence",
                    metadata={
                        **evidence_metadata(source_ref="docs/data-dictionary.md"),
                        **_research_pack_identity(),
                        "domain_evidence_type": "data_dictionary",
                    },
                ),
            ],
            links=[
                _link("L-E-001-supports-D-001", "E-001", "supports", "D-001"),
                _link("L-E-002-supports-D-001", "E-002", "supports", "D-001"),
            ],
        )

        result = evaluate_safety_gate(project_state, "D-001", domain_registry=_registry())

        self.assertEqual("passed", result["gate_status"])
        self.assertNotIn("domain_required_evidence_missing", result["approval_reasons"])
        self.assertTrue(all(item["satisfied"] for item in result["domain_requirements"]))
        self.assertEqual(
            {
                "protocol_or_project_brief": ["E-001"],
                "data_dictionary": ["E-002"],
            },
            {
                item["required_evidence_id"]: item["satisfied_by_object_ids"]
                for item in result["domain_requirements"]
            },
        )

    def test_domain_safety_rule_raises_approval_threshold(self) -> None:
        project_state = _project_state(
            objects=[
                _object(
                    "D-001",
                    "decision",
                    metadata=_research_decision_metadata("publication_plan"),
                ),
                _object(
                    "R-001",
                    "risk",
                    metadata={
                        **risk_metadata(risk_tier="low", approval_threshold="none"),
                        **_research_pack_identity(),
                        "domain_risk_type": "patient_data",
                    },
                ),
            ],
            links=[_link("L-R-001-constrains-D-001", "R-001", "constrains", "D-001")],
        )

        result = evaluate_safety_gate(project_state, "D-001", domain_registry=_registry())

        self.assertEqual("external_review", result["approval_threshold"])
        self.assertIn("external_review_required", result["approval_reasons"])
        self.assertEqual("patient_data_external_review", result["domain_safety_rules"][0]["rule_id"])
        self.assertEqual(["patient_data"], result["domain_safety_rules"][0]["matched_risk_types"])

    def test_domain_pack_metadata_mismatch_fails_fast(self) -> None:
        metadata = _research_decision_metadata("primary_endpoint")
        metadata["domain_pack_digest"] = "DP-000000000000"
        project_state = _project_state(objects=[_object("D-001", "decision", metadata=metadata)], links=[])

        with self.assertRaisesRegex(ValueError, "domain_pack_digest mismatch"):
            evaluate_safety_gate(project_state, "D-001", domain_registry=_registry())

    def test_missing_evidence_on_medium_risk_needs_approval(self) -> None:
        project_state = _project_state(
            objects=[
                _object("D-001", "decision"),
                _object("R-001", "risk", metadata=risk_metadata(risk_tier="medium", approval_threshold="none")),
            ],
            links=[_link("L-R-001-constrains-D-001", "R-001", "constrains", "D-001")],
        )

        result = evaluate_safety_gate(project_state, "D-001")

        self.assertEqual("needs_approval", result["gate_status"])
        self.assertIn("insufficient_evidence_requires_approval", result["approval_reasons"])

    def test_challenge_evidence_blocks_gate(self) -> None:
        project_state = _project_state(
            objects=[
                _object("D-001", "decision"),
                _object("E-001", "evidence", metadata=evidence_metadata(confidence="high", freshness="current")),
                _object("E-002", "evidence", metadata=evidence_metadata(source_ref="docs/challenge.md")),
            ],
            links=[
                _link("L-E-001-supports-D-001", "E-001", "supports", "D-001"),
                _link("L-E-002-challenges-D-001", "E-002", "challenges", "D-001"),
            ],
        )

        result = evaluate_safety_gate(project_state, "D-001")

        self.assertEqual("blocked", result["gate_status"])
        self.assertEqual("challenged", result["evidence_coverage"])
        self.assertIn("challenged_evidence", result["blocking_reasons"])
        self.assertEqual(["challenges", "supports"], sorted(item["relation"] for item in result["evidence"]))

    def test_high_and_critical_risks_use_highest_tier(self) -> None:
        project_state = _project_state(
            objects=[
                _object("D-001", "decision"),
                _object("E-001", "evidence", metadata=evidence_metadata()),
                _object("R-001", "risk", metadata=risk_metadata(risk_tier="high")),
                _object("R-002", "risk", metadata=risk_metadata(risk_tier="critical")),
            ],
            links=[
                _link("L-E-001-supports-D-001", "E-001", "supports", "D-001"),
                _link("L-R-001-challenges-D-001", "R-001", "challenges", "D-001"),
                _link("L-R-002-invalidates-D-001", "R-002", "invalidates", "D-001"),
            ],
        )

        result = evaluate_safety_gate(project_state, "D-001")

        self.assertEqual("critical", result["risk_tier"])
        self.assertEqual("blocked", result["gate_status"])
        self.assertIn("critical_risk_tier", result["blocking_reasons"])
        self.assertEqual(["R-001", "R-002"], [risk["object_id"] for risk in result["risks"]])

    def test_approval_threshold_uses_highest_related_risk_threshold(self) -> None:
        project_state = _project_state(
            objects=[
                _object("D-001", "decision"),
                _object("E-001", "evidence", metadata=evidence_metadata()),
                _object(
                    "R-001",
                    "risk",
                    metadata=risk_metadata(risk_tier="low", approval_threshold="explicit_acceptance"),
                ),
                _object(
                    "R-002",
                    "risk",
                    metadata=risk_metadata(risk_tier="low", approval_threshold="external_review"),
                ),
            ],
            links=[
                _link("L-E-001-supports-D-001", "E-001", "supports", "D-001"),
                _link("L-R-001-constrains-D-001", "R-001", "constrains", "D-001"),
                _link("L-R-002-constrains-D-001", "R-002", "constrains", "D-001"),
            ],
        )

        result = evaluate_safety_gate(project_state, "D-001")

        self.assertEqual("external_review", result["approval_threshold"])
        self.assertTrue(result["approval_required"])
        self.assertEqual("needs_approval", result["gate_status"])
        self.assertEqual(["external_review_required"], result["approval_reasons"])

    def test_reversibility_maps_decision_and_risk_constraints(self) -> None:
        irreversible_state = _project_state(
            objects=[
                _object("D-001", "decision", metadata={"reversibility": "irreversible"}),
                _object("E-001", "evidence", metadata=evidence_metadata()),
            ],
            links=[_link("L-E-001-supports-D-001", "E-001", "supports", "D-001")],
        )

        irreversible = evaluate_safety_gate(irreversible_state, "D-001")

        self.assertEqual("irreversible", irreversible["reversibility"])
        self.assertIn("irreversible_change", irreversible["approval_reasons"])
        self.assertEqual("needs_approval", irreversible["gate_status"])

        partial_state = _project_state(
            objects=[
                _object("A-001", "action"),
                _object("E-001", "evidence", metadata=evidence_metadata()),
                _object(
                    "R-001",
                    "risk",
                    metadata=risk_metadata(
                        risk_tier="low",
                        approval_threshold="none",
                        reversibility="partially_reversible",
                    ),
                ),
            ],
            links=[
                _link("L-E-001-supports-A-001", "E-001", "supports", "A-001"),
                _link("L-A-001-blocked-by-R-001", "A-001", "blocked_by", "R-001"),
            ],
        )

        partial = evaluate_safety_gate(partial_state, "A-001")

        self.assertEqual("partially_reversible", partial["reversibility"])
        self.assertIn("partially_reversible_change", partial["warning_reasons"])
        self.assertEqual("passed", partial["gate_status"])

        irreversible_action_state = _project_state(
            objects=[
                _object("A-002", "action", metadata={"reversibility": "irreversible"}),
                _object("E-002", "evidence", metadata=evidence_metadata()),
            ],
            links=[_link("L-E-002-supports-A-002", "E-002", "supports", "A-002")],
        )

        irreversible_action = evaluate_safety_gate(irreversible_action_state, "A-002")

        self.assertEqual("irreversible", irreversible_action["reversibility"])
        self.assertIn("irreversible_change", irreversible_action["approval_reasons"])
        self.assertEqual("needs_approval", irreversible_action["gate_status"])

    def test_low_confidence_assumption_adds_warning(self) -> None:
        project_state = _project_state(
            objects=[
                _object("D-001", "decision"),
                _object("E-001", "evidence", metadata=evidence_metadata()),
                _object("AS-001", "assumption", metadata=assumption_metadata(confidence="low")),
            ],
            links=[
                _link("L-E-001-supports-D-001", "E-001", "supports", "D-001"),
                _link("L-AS-001-constrains-D-001", "AS-001", "constrains", "D-001"),
            ],
        )

        result = evaluate_safety_gate(project_state, "D-001")

        self.assertEqual("passed", result["gate_status"])
        self.assertEqual(["low_confidence_assumption"], result["warning_reasons"])
        self.assertEqual(["AS-001"], [item["object_id"] for item in result["assumptions"]])

    def test_report_defaults_to_live_decisions_and_actions(self) -> None:
        project_state = _project_state(
            objects=[
                _object("D-002", "decision", status="invalidated"),
                _object("A-001", "action"),
                _object("D-001", "decision"),
                _object("R-001", "risk", metadata=risk_metadata()),
            ],
            links=[],
        )

        report = build_safety_gate_report(project_state)

        self.assertEqual(2, report["summary"]["evaluated_count"])
        self.assertEqual(["A-001", "D-001"], [result["object_id"] for result in report["results"]])
        self.assertEqual({"needs_approval": 1, "passed": 1}, report["summary"]["by_gate_status"])

    def test_gate_digest_is_stable_for_same_inputs(self) -> None:
        project_state = _project_state(
            objects=[
                _object("D-001", "decision"),
                _object("E-001", "evidence", metadata=evidence_metadata()),
            ],
            links=[_link("L-E-001-supports-D-001", "E-001", "supports", "D-001")],
        )

        first = evaluate_safety_gate(project_state, "D-001")
        second = evaluate_safety_gate(project_state, "D-001")

        self.assertEqual(first["gate_digest"], second["gate_digest"])
        self.assertRegex(first["gate_digest"], r"^SG-[0-9a-f]{12}$")

    def test_stale_only_supporting_evidence_is_insufficient(self) -> None:
        project_state = _project_state(
            objects=[
                _object("D-001", "decision"),
                _object(
                    "E-001",
                    "evidence",
                    metadata=evidence_metadata(valid_until="2026-04-27T00:00:00Z"),
                ),
            ],
            links=[_link("L-E-001-supports-D-001", "E-001", "supports", "D-001")],
        )

        result = evaluate_safety_gate(project_state, "D-001", now="2026-04-28T00:00:00Z")

        self.assertEqual("insufficient", result["evidence_coverage"])
        self.assertIn("stale_supporting_evidence", result["warning_reasons"])

    def test_completed_action_verification_gap_blocks(self) -> None:
        result = evaluate_safety_gate(
            _project_state(objects=[_object("A-001", "action", status="completed")], links=[]),
            "A-001",
        )

        self.assertEqual("blocked", result["gate_status"])
        self.assertIn("completed_action_verification_gap", result["blocking_reasons"])

    def test_unknown_object_id_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown object_id: D-missing"):
            evaluate_safety_gate(_project_state(objects=[], links=[]), "D-missing")


def _project_state(*, objects: list[dict], links: list[dict]) -> dict:
    return {
        "schema_version": 12,
        "state": {
            "project_head": "H-test",
            "event_count": len(objects) + len(links),
            "updated_at": "2026-04-28T00:00:00Z",
            "last_event_id": "E-last",
        },
        "objects": deepcopy(objects),
        "links": deepcopy(links),
    }


def _object(
    object_id: str,
    object_type: str,
    *,
    status: str = "active",
    metadata: dict | None = None,
) -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": object_id,
        "body": None,
        "status": status,
        "created_at": "2026-04-28T00:00:00Z",
        "updated_at": None,
        "source_event_ids": ["E-create"],
        "metadata": {} if metadata is None else deepcopy(metadata),
    }


def _link(link_id: str, source: str, relation: str, target: str) -> dict:
    return {
        "id": link_id,
        "source_object_id": source,
        "relation": relation,
        "target_object_id": target,
        "rationale": "Safety gate fixture link.",
        "created_at": "2026-04-28T00:00:00Z",
        "source_event_ids": ["E-link"],
    }


def _registry() -> DomainRegistry:
    return DomainRegistry(load_builtin_packs())


def _research_pack_identity() -> dict:
    pack = load_builtin_packs()["research"]
    return {
        "domain_pack_id": pack.pack_id,
        "domain_pack_version": pack.version,
        "domain_pack_digest": domain_pack_digest(pack),
    }


def _research_decision_metadata(decision_type_id: str) -> dict:
    registry = _registry()
    spec = registry.decision_type("research", decision_type_id)
    return {
        "priority": spec.default_priority,
        "frontier": "now",
        "reversibility": spec.default_reversibility,
        **_research_pack_identity(),
        "domain_decision_type": spec.id,
        "domain_criteria": list(spec.criteria),
    }


if __name__ == "__main__":
    unittest.main()
