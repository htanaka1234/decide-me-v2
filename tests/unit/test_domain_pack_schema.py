from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from decide_me.domains.model import (
    DecisionTypeSpec,
    DomainPack,
    domain_pack_from_dict,
)


class DomainPackSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas" / "domain-pack.schema.json"
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.schema)

    def test_accepts_research_like_pack_payload(self) -> None:
        self.assertEqual([], list(self.validator.iter_errors(_valid_pack())))

    def test_rejects_invalid_pack_ids(self) -> None:
        for pack_id in ("Research", "research-plan", "9research"):
            with self.subTest(pack_id=pack_id):
                payload = _valid_pack()
                payload["pack_id"] = pack_id

                self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_unknown_top_level_field(self) -> None:
        payload = _valid_pack()
        payload["python_hook"] = "decide_me.plugins.research"

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_unknown_nested_fields(self) -> None:
        cases = (
            (["decision_types", 0], "prompt"),
            (["documents", 0], "builder"),
            (["interview"], "classifier"),
        )
        for path, field in cases:
            with self.subTest(path=path, field=field):
                payload = _valid_pack()
                target = _at_path(payload, path)
                target[field] = "not allowed"

                self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_invalid_core_enums(self) -> None:
        cases = (
            (["default_core_domain"], "research"),
            (["decision_types", 0, "object_type"], "domain_decision"),
            (["decision_types", 0, "layer"], "domain"),
            (["evidence_requirements", 0, "evidence_source"], "database"),
            (["risk_types", 0, "default_risk_tier"], "severe"),
            (["risk_types", 0, "default_approval_threshold"], "automatic"),
            (["documents", 0, "document_type"], "protocol"),
            (["evidence_requirements", 0, "min_confidence"], "certain"),
            (["evidence_requirements", 0, "freshness_required"], "fresh"),
        )
        for path, value in cases:
            with self.subTest(path=path):
                payload = _valid_pack()
                _set_path(payload, path, value)

                self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_model_round_trips_pack_payload(self) -> None:
        payload = _valid_pack()
        pack = domain_pack_from_dict(payload)

        self.assertIsInstance(pack, DomainPack)
        self.assertIsInstance(pack.decision_types[0], DecisionTypeSpec)
        self.assertIsInstance(pack.aliases, tuple)
        self.assertIsInstance(pack.decision_types[0].criteria, tuple)
        self.assertEqual(payload, pack.to_dict())


def _valid_pack() -> dict:
    return {
        "schema_version": 1,
        "pack_id": "research",
        "version": "0.1.0",
        "label": "Research",
        "description": "Research planning and analysis decision support.",
        "aliases": ["study", "protocol", "analysis plan"],
        "default_core_domain": "data",
        "decision_types": [
            {
                "id": "research_question",
                "label": "Research question",
                "object_type": "decision",
                "layer": "purpose",
                "kind": "choice",
                "default_priority": "P0",
                "default_reversibility": "hard-to-reverse",
                "criteria": ["scientific_validity", "feasibility"],
                "required_evidence": ["protocol_or_project_brief"],
            }
        ],
        "criteria": [
            {
                "id": "scientific_validity",
                "label": "Scientific validity",
                "description": "Whether the decision preserves internal and external validity.",
            },
            {
                "id": "feasibility",
                "label": "Feasibility",
                "description": "Whether the plan can be executed with available resources.",
            },
        ],
        "evidence_requirements": [
            {
                "id": "protocol_or_project_brief",
                "label": "Protocol or project brief",
                "evidence_source": "docs",
                "domain_evidence_type": "protocol",
                "min_confidence": "medium",
                "freshness_required": "current",
            }
        ],
        "risk_types": [
            {
                "id": "human_subjects",
                "label": "Human subjects risk",
                "default_risk_tier": "high",
                "default_approval_threshold": "external_review",
            }
        ],
        "safety_rules": [
            {
                "id": "human_subjects_review",
                "applies_when": {"risk_types": ["human_subjects"]},
                "approval_threshold": "external_review",
                "reason": "Human-subjects decisions require external review.",
            }
        ],
        "documents": [
            {
                "document_type": "research-plan",
                "default": True,
                "profile_id": "research_protocol",
                "required_sections": [
                    "objective",
                    "research_question",
                    "risks",
                    "verification",
                ],
            }
        ],
        "interview": {
            "domain_hints": ["cohort", "endpoint", "missing data"],
            "question_templates": {
                "research_question": "What research question should this plan answer?"
            },
        },
    }


def _at_path(payload: dict, path: list[str | int]) -> dict:
    current = payload
    for part in path:
        current = current[part]
    return current


def _set_path(payload: dict, path: list[str | int], value: object) -> None:
    target = _at_path(payload, path[:-1])
    target[path[-1]] = value


if __name__ == "__main__":
    unittest.main()
