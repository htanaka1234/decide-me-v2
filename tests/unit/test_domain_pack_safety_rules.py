from __future__ import annotations

import unittest
from copy import deepcopy

from decide_me.domains import DomainRegistry, domain_pack_digest, load_builtin_packs
from decide_me.safety_gate import evaluate_safety_gate
from tests.helpers.typed_metadata import evidence_metadata, risk_metadata


class DomainPackSafetyRuleTests(unittest.TestCase):
    def test_research_required_evidence_missing_needs_approval(self) -> None:
        project_state = _project_state(
            objects=[
                _object(
                    "D-001",
                    "decision",
                    metadata=_decision_metadata("research", "primary_endpoint"),
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

    def test_research_required_evidence_can_be_satisfied_by_requirement_or_domain_type(self) -> None:
        project_state = _project_state(
            objects=[
                _object(
                    "D-001",
                    "decision",
                    metadata=_decision_metadata("research", "primary_endpoint"),
                ),
                _object(
                    "E-001",
                    "evidence",
                    metadata={
                        **evidence_metadata(source_ref="docs/protocol.md"),
                        **_pack_identity("research"),
                        "evidence_requirement_id": "protocol_or_project_brief",
                    },
                ),
                _object(
                    "E-002",
                    "evidence",
                    metadata={
                        **evidence_metadata(source_ref="docs/data-dictionary.md"),
                        **_pack_identity("research"),
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

    def test_research_patient_data_safety_rule_raises_approval_threshold(self) -> None:
        project_state = _project_state(
            objects=[
                _object(
                    "D-001",
                    "decision",
                    metadata=_decision_metadata("research", "publication_plan"),
                ),
                _object(
                    "R-001",
                    "risk",
                    metadata={
                        **risk_metadata(risk_tier="low", approval_threshold="none"),
                        **_pack_identity("research"),
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

    def test_research_patient_data_cannot_be_satisfied_by_explicit_acceptance_artifact(self) -> None:
        project_state = _project_state(
            objects=[
                _object(
                    "D-001",
                    "decision",
                    metadata=_decision_metadata("research", "publication_plan"),
                ),
                _object(
                    "R-001",
                    "risk",
                    metadata={
                        **risk_metadata(risk_tier="low", approval_threshold="none"),
                        **_pack_identity("research"),
                        "domain_risk_type": "patient_data",
                    },
                ),
            ],
            links=[_link("L-R-001-constrains-D-001", "R-001", "constrains", "D-001")],
        )
        gate = evaluate_safety_gate(project_state, "D-001", domain_registry=_registry())
        project_state = _with_approval(
            project_state,
            gate["gate_digest"],
            approval_threshold="external_review",
            approval_level="explicit_acceptance",
        )

        result = evaluate_safety_gate(project_state, "D-001", domain_registry=_registry())

        self.assertEqual("needs_approval", result["gate_status"])
        self.assertEqual("external_review", result["approval_threshold"])
        self.assertFalse(result["approval_satisfied"])
        self.assertEqual([], result["approval_artifact_ids"])

    def test_procurement_final_selection_missing_comparison_evidence_needs_approval(self) -> None:
        project_state = _project_state(
            objects=[
                _object(
                    "D-001",
                    "decision",
                    metadata=_decision_metadata("procurement", "final_selection"),
                ),
            ],
            links=[],
        )

        result = evaluate_safety_gate(project_state, "D-001", domain_registry=_registry())

        missing = [item["required_evidence_id"] for item in result["domain_requirements"] if not item["satisfied"]]
        self.assertEqual("needs_approval", result["gate_status"])
        self.assertIn("domain_required_evidence_missing", result["approval_reasons"])
        self.assertIn("comparison_table", missing)
        self.assertIn("budget_context", missing)
        self.assertIn("contract_terms", missing)
        self.assertEqual(result["domain_requirements"], result["digest_inputs"]["domain_requirements"])

    def test_domain_pack_metadata_mismatch_fails_fast(self) -> None:
        metadata = _decision_metadata("research", "primary_endpoint")
        metadata["domain_pack_digest"] = "DP-000000000000"
        project_state = _project_state(objects=[_object("D-001", "decision", metadata=metadata)], links=[])

        with self.assertRaisesRegex(ValueError, "domain_pack_digest mismatch"):
            evaluate_safety_gate(project_state, "D-001", domain_registry=_registry())


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
        "rationale": "Domain safety gate fixture link.",
        "created_at": "2026-04-28T00:00:00Z",
        "source_event_ids": ["E-link"],
    }


def _with_approval(
    project_state: dict,
    gate_digest: str,
    *,
    approval_threshold: str,
    approval_level: str,
) -> dict:
    copied = deepcopy(project_state)
    copied["objects"].append(
        _object(
            "ART-approval-D-001",
            "artifact",
            metadata={
                "artifact_type": "safety_gate_approval",
                "target_object_id": "D-001",
                "gate_digest": gate_digest,
                "approval_threshold": approval_threshold,
                "approval_level": approval_level,
                "approved_by": "explicit_acceptance",
                "approved_at": "2026-04-28T00:00:00Z",
                "reason": "Explicit acceptance is not enough.",
                "expires_at": None,
            },
        )
    )
    copied["links"].append(_link("L-ART-approval-D-001-addresses-D-001", "ART-approval-D-001", "addresses", "D-001"))
    return copied


def _registry() -> DomainRegistry:
    return DomainRegistry(load_builtin_packs())


def _pack_identity(pack_id: str) -> dict:
    pack = load_builtin_packs()[pack_id]
    return {
        "domain_pack_id": pack.pack_id,
        "domain_pack_version": pack.version,
        "domain_pack_digest": domain_pack_digest(pack),
    }


def _decision_metadata(pack_id: str, decision_type_id: str) -> dict:
    registry = _registry()
    spec = registry.decision_type(pack_id, decision_type_id)
    return {
        "priority": spec.default_priority,
        "frontier": "now",
        "reversibility": spec.default_reversibility,
        **_pack_identity(pack_id),
        "domain_decision_type": spec.id,
        "domain_criteria": list(spec.criteria),
    }


if __name__ == "__main__":
    unittest.main()
