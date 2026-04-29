from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from decide_me.domains import validate_domain_pack_payload
from decide_me.domains.model import DomainPack, domain_pack_from_dict


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKS_DIR = REPO_ROOT / "decide_me" / "domains" / "packs"
EXPECTED_PACK_IDS = {"generic", "software", "research", "procurement"}
RESEARCH_DECISION_TYPE_IDS = {
    "research_question",
    "study_design",
    "cohort_definition",
    "inclusion_exclusion",
    "exposure_definition",
    "comparator_definition",
    "primary_endpoint",
    "secondary_endpoint",
    "covariate_strategy",
    "missing_data_strategy",
    "sensitivity_analysis",
    "reproducibility_plan",
    "publication_plan",
}
RESEARCH_RISK_TYPE_IDS = {
    "unclear_endpoint",
    "selection_bias",
    "information_bias",
    "confounding",
    "missing_data",
    "data_access",
    "patient_data",
    "ethics_or_irb",
    "reproducibility",
}
PROCUREMENT_DECISION_TYPE_IDS = {
    "requirement_definition",
    "budget_limit",
    "candidate_selection",
    "evaluation_criteria",
    "comparison_method",
    "vendor_risk",
    "contract_review",
    "security_review",
    "final_selection",
    "implementation_plan",
    "renewal_or_revisit_plan",
}
PROCUREMENT_RISK_TYPE_IDS = {
    "vendor_lock_in",
    "hidden_cost",
    "contract_constraint",
    "data_processing",
    "support_quality",
    "switching_cost",
    "sole_vendor",
    "budget_overrun",
}


class DomainPackBuiltinPacksTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = REPO_ROOT / "schemas" / "domain-pack.schema.json"
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.schema)

    def test_builtin_pack_files_are_exact_expected_set(self) -> None:
        pack_files = sorted(PACKS_DIR.glob("*.yaml"))

        self.assertEqual(EXPECTED_PACK_IDS, {path.stem for path in pack_files})
        for path in pack_files:
            with self.subTest(path=path.name):
                self.assertEqual(path.stem, _load_yaml(path)["pack_id"])

    def test_builtin_packs_validate_against_schema_and_model(self) -> None:
        for pack_id, raw in _load_packs().items():
            with self.subTest(pack_id=pack_id):
                errors = sorted(self.validator.iter_errors(raw), key=lambda error: list(error.path))
                self.assertEqual([], [error.message for error in errors])
                validate_domain_pack_payload(raw)

                pack = domain_pack_from_dict(raw)

                self.assertIsInstance(pack, DomainPack)
                self.assertEqual(raw, pack.to_dict())

    def test_research_pack_matches_phase9_mvp_content(self) -> None:
        pack = _load_packs()["research"]

        self.assertEqual(RESEARCH_DECISION_TYPE_IDS, _ids(pack["decision_types"]))
        self.assertEqual(RESEARCH_RISK_TYPE_IDS, _ids(pack["risk_types"]))
        self.assertTrue(
            {
                "research",
                "research plan",
                "clinical research",
                "cohort study",
            }.issubset(set(pack["aliases"]))
        )
        self.assertIn(
            ("research-plan", "research_protocol"),
            _document_profiles(pack["documents"]),
        )

    def test_procurement_pack_matches_phase9_mvp_content(self) -> None:
        pack = _load_packs()["procurement"]

        self.assertEqual(PROCUREMENT_DECISION_TYPE_IDS, _ids(pack["decision_types"]))
        self.assertEqual(PROCUREMENT_RISK_TYPE_IDS, _ids(pack["risk_types"]))
        self.assertEqual(
            ["requirements_brief", "budget_context"],
            _decision_type(pack, "comparison_method")["required_evidence"],
        )
        self.assertEqual(
            ["requirements_brief", "budget_context"],
            _decision_type(pack, "evaluation_criteria")["required_evidence"],
        )
        self.assertEqual(
            ["security_review_input"],
            _decision_type(pack, "security_review")["required_evidence"],
        )
        self.assertIn(
            ("comparison-table", "procurement_comparison"),
            _document_profiles(pack["documents"]),
        )

    def test_software_pack_preserves_key_hints(self) -> None:
        pack = _load_packs()["software"]
        hints = set(pack["interview"]["domain_hints"])

        for hint in ("api", "auth", "endpoint", "database"):
            with self.subTest(hint=hint):
                self.assertIn(hint, hints)
        self.assertEqual("technical", pack["default_core_domain"])

    def test_generic_pack_is_useful_fallback(self) -> None:
        pack = _load_packs()["generic"]

        self.assertEqual("other", pack["default_core_domain"])
        self.assertEqual(["generic", "general"], pack["aliases"])
        self.assertEqual([], pack["interview"]["domain_hints"])
        self.assertEqual([], pack["evidence_requirements"])
        self.assertEqual([], pack["risk_types"])
        self.assertEqual([], pack["safety_rules"])
        self.assertIn("clarify_goal", _ids(pack["decision_types"]))
        self.assertIn("choose_option", _ids(pack["decision_types"]))
        self.assertIn("resolve_constraint", _ids(pack["decision_types"]))
        self.assertIn("plan_verification", _ids(pack["decision_types"]))
        for item in pack["decision_types"]:
            with self.subTest(decision_type=item["id"]):
                self.assertEqual([], item["required_evidence"])


def _load_packs() -> dict[str, dict[str, Any]]:
    return {path.stem: _load_yaml(path) for path in sorted(PACKS_DIR.glob("*.yaml"))}


def _load_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise AssertionError(f"{path} did not load as a mapping")
    return loaded


def _ids(items: list[dict[str, Any]]) -> set[str]:
    return {item["id"] for item in items}


def _decision_type(pack: dict[str, Any], decision_type_id: str) -> dict[str, Any]:
    for item in pack["decision_types"]:
        if item["id"] == decision_type_id:
            return item
    raise AssertionError(f"missing decision type: {decision_type_id}")


def _document_profiles(items: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {(item["document_type"], item["profile_id"]) for item in items}


if __name__ == "__main__":
    unittest.main()
