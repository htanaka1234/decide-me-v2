from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from decide_me.domains import (
    DomainPack,
    DomainPackLoadError,
    DomainRegistry,
    apply_decision_pack_metadata,
    build_interview_policy,
    build_interview_policy_from_metadata,
    domain_pack_digest,
    domain_pack_from_dict,
    infer_decision_type,
    load_builtin_packs,
    load_domain_registry,
    load_user_packs,
    validate_domain_pack_payload,
)


EXPECTED_BUILTINS = {"generic", "software", "research", "procurement"}
REPO_ROOT = Path(__file__).resolve().parents[2]


class DomainPackRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = REPO_ROOT / "schemas" / "domain-pack.schema.json"
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.schema)

    def test_load_builtin_packs_returns_expected_packs(self) -> None:
        packs = load_builtin_packs()

        self.assertEqual(EXPECTED_BUILTINS, set(packs))
        for pack_id, pack in packs.items():
            with self.subTest(pack_id=pack_id):
                self.assertIsInstance(pack, DomainPack)
                raw = pack.to_dict()
                errors = sorted(self.validator.iter_errors(raw), key=lambda error: list(error.path))
                self.assertEqual([], [error.message for error in errors])
                validate_domain_pack_payload(raw)

    def test_load_user_packs_returns_empty_for_absent_directory_without_writes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            ai_dir = Path(temp_dir)

            self.assertEqual({}, load_user_packs(ai_dir))
            self.assertFalse((ai_dir / "domain-packs").exists())

    def test_load_user_packs_reads_yaml_yml_and_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            pack_dir = Path(temp_dir) / "domain-packs"
            pack_dir.mkdir()
            _write_pack(pack_dir / "alpha.yaml", _pack_payload("alpha"))
            _write_pack(pack_dir / "beta.yml", _pack_payload("beta"))
            _write_json_pack(pack_dir / "gamma.json", _pack_payload("gamma"))

            packs = load_user_packs(temp_dir)

        self.assertEqual({"alpha", "beta", "gamma"}, set(packs))
        self.assertTrue(all(isinstance(pack, DomainPack) for pack in packs.values()))

    def test_load_user_packs_rejects_malformed_non_object_invalid_and_duplicate_packs(self) -> None:
        cases = (
            ("bad.yaml", "schema_version: [", "cannot parse"),
            ("list.yaml", "- not\n- object\n", "must contain an object"),
            ("invalid.yaml", "schema_version: 1\n", "invalid domain pack file"),
        )
        for filename, body, message in cases:
            with self.subTest(filename=filename), TemporaryDirectory() as temp_dir:
                pack_dir = Path(temp_dir) / "domain-packs"
                pack_dir.mkdir()
                (pack_dir / filename).write_text(body, encoding="utf-8")

                with self.assertRaisesRegex(DomainPackLoadError, message):
                    load_user_packs(temp_dir)

        with TemporaryDirectory() as temp_dir:
            pack_dir = Path(temp_dir) / "domain-packs"
            pack_dir.mkdir()
            _write_pack(pack_dir / "first.yaml", _pack_payload("duplicate"))
            _write_json_pack(pack_dir / "second.json", _pack_payload("duplicate"))

            with self.assertRaisesRegex(DomainPackLoadError, "duplicate domain pack id duplicate"):
                load_user_packs(temp_dir)

    def test_load_user_packs_wraps_non_scalar_enum_values(self) -> None:
        cases = (["other"], {"value": "other"})
        for value in cases:
            with self.subTest(value=value), TemporaryDirectory() as temp_dir:
                pack_dir = Path(temp_dir) / "domain-packs"
                pack_dir.mkdir()
                payload = _pack_payload("alpha")
                payload["default_core_domain"] = value
                _write_pack(pack_dir / "alpha.yaml", payload)

                with self.assertRaisesRegex(DomainPackLoadError, "invalid domain pack file"):
                    load_user_packs(temp_dir)

    def test_load_domain_registry_rejects_user_pack_duplicate_of_builtin(self) -> None:
        with TemporaryDirectory() as temp_dir:
            pack_dir = Path(temp_dir) / "domain-packs"
            pack_dir.mkdir()
            _write_pack(pack_dir / "generic.yaml", _pack_payload("generic"))

            with self.assertRaisesRegex(DomainPackLoadError, "duplicate domain pack ids: generic"):
                load_domain_registry(temp_dir)

    def test_domain_pack_digest_is_deterministic_and_content_sensitive(self) -> None:
        pack = load_builtin_packs()["research"]
        same_pack = load_builtin_packs()["research"]
        changed_raw = deepcopy(pack.to_dict())
        changed_raw["description"] = "Changed research pack description."

        first = domain_pack_digest(pack)
        second = domain_pack_digest(same_pack)
        changed = domain_pack_digest(domain_pack_from_dict(changed_raw))

        self.assertEqual(first, second)
        self.assertRegex(first, r"^DP-[0-9a-f]{12}$")
        self.assertNotEqual(first, changed)

    def test_registry_get_list_and_decision_type(self) -> None:
        registry = load_domain_registry()

        self.assertIsInstance(registry, DomainRegistry)
        self.assertEqual(sorted(EXPECTED_BUILTINS), [pack.pack_id for pack in registry.list()])
        self.assertEqual("research", registry.get("research").pack_id)
        self.assertEqual("primary_endpoint", registry.decision_type("research", "primary_endpoint").id)

        with self.assertRaisesRegex(KeyError, "unknown domain pack"):
            registry.get("missing")
        with self.assertRaisesRegex(KeyError, "unknown decision type"):
            registry.decision_type("research", "missing")

    def test_registry_rejects_invalid_pack_mapping(self) -> None:
        packs = load_builtin_packs()

        with self.assertRaisesRegex(ValueError, "must include generic"):
            DomainRegistry({"research": packs["research"]})
        with self.assertRaisesRegex(ValueError, "keys must match pack_id"):
            DomainRegistry({"generic": packs["generic"], "wrong": packs["research"]})
        with self.assertRaisesRegex(ValueError, "values must be DomainPack"):
            DomainRegistry({"generic": object()})

    def test_registry_packs_mapping_is_read_only(self) -> None:
        registry = load_domain_registry()

        with self.assertRaises(TypeError):
            registry.packs["extra"] = registry.get("generic")

    def test_build_interview_policy_handles_generic_known_and_unknown_packs(self) -> None:
        registry = load_domain_registry()

        generic = build_interview_policy(registry, domain_pack_id=None)
        research = build_interview_policy(registry, domain_pack_id="research")

        self.assertEqual("generic", generic.pack_id)
        self.assertTrue(generic.is_generic)
        self.assertIsNone(generic.initial_decision_type)
        self.assertEqual("research", research.pack_id)
        self.assertFalse(research.is_generic)
        self.assertEqual("research_question", research.initial_decision_type.id)
        with self.assertRaisesRegex(KeyError, "unknown domain pack"):
            build_interview_policy(registry, domain_pack_id="missing")

    def test_build_interview_policy_from_metadata_rejects_stale_metadata(self) -> None:
        registry = load_domain_registry()
        research = registry.get("research")
        valid_metadata = {
            "domain_pack_id": "research",
            "domain_pack_version": research.version,
            "domain_pack_digest": domain_pack_digest(research),
        }

        policy = build_interview_policy_from_metadata(
            registry,
            valid_metadata,
            label="session S-001.classification",
        )

        self.assertEqual("research", policy.pack_id)
        with self.assertRaisesRegex(ValueError, "domain_pack_version mismatch"):
            build_interview_policy_from_metadata(
                registry,
                {**valid_metadata, "domain_pack_version": "9.9.9"},
                label="session S-001.classification",
            )
        with self.assertRaisesRegex(ValueError, "domain_pack_digest mismatch"):
            build_interview_policy_from_metadata(
                registry,
                {**valid_metadata, "domain_pack_digest": "DP-000000000000"},
                label="session S-001.classification",
            )
        with self.assertRaisesRegex(ValueError, "incomplete domain pack metadata"):
            build_interview_policy_from_metadata(
                registry,
                {"domain_pack_id": "research"},
                label="decision D-001",
            )

    def test_apply_decision_pack_metadata_omits_type_when_inference_fails(self) -> None:
        registry = load_domain_registry()
        policy = build_interview_policy(registry, domain_pack_id="research")

        decision = apply_decision_pack_metadata(
            policy,
            {"title": "Unrelated operational topic", "priority": "P0", "frontier": "now"},
        )

        self.assertEqual("research", decision["domain_pack_id"])
        self.assertEqual(registry.get("research").version, decision["domain_pack_version"])
        self.assertEqual(domain_pack_digest(registry.get("research")), decision["domain_pack_digest"])
        self.assertNotIn("domain_decision_type", decision)
        self.assertNotIn("domain_criteria", decision)

    def test_infer_decision_type_matches_representative_pack_terms(self) -> None:
        packs = load_builtin_packs()
        cases = (
            ("research", "primary endpoint", "primary_endpoint"),
            ("research", "missing data handling", "missing_data_strategy"),
            ("research", "cohort", "cohort_definition"),
            ("procurement", "contract", "contract_review"),
            ("procurement", "security review", "security_review"),
            ("procurement", "budget", "budget_limit"),
            ("software", "auth", "auth_strategy"),
            ("software", "api", "api_contract"),
            ("software", "data model", "data_model"),
        )
        for pack_id, text, expected in cases:
            with self.subTest(pack_id=pack_id, text=text):
                self.assertEqual(expected, infer_decision_type(packs[pack_id], text))

        self.assertIsNone(infer_decision_type(packs["research"], "endpoint"))
        self.assertIsNone(infer_decision_type(packs["procurement"], "selection"))
        self.assertIsNone(infer_decision_type(packs["software"], "unrelated topic"))

    def test_infer_from_context_is_deterministic_and_uses_generic_only_as_fallback(self) -> None:
        registry = load_domain_registry()

        cases = (
            ("primary endpoint and missing data", "research"),
            ("primary-endpoint and missing-data", "research"),
            ("statistical-analysis-plan", "research"),
            ("patient_data endpoint", "research"),
            ("vendor, contract, budget, comparison", "procurement"),
            ("API, auth, endpoint, database", "software"),
            ("API/auth endpoint database", "software"),
            ("auth", "software"),
            ("API", "software"),
            ("cohort", "research"),
            ("vendor", "procurement"),
            ("contract", "procurement"),
            ("endpoint", "generic"),
            ("decision option risk evidence verification", "generic"),
            ("", "generic"),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(expected, registry.infer_from_context(text))
                self.assertEqual(expected, registry.infer_from_context(text))

    def test_infer_from_context_does_not_overclassify_ambiguous_generic_terms(self) -> None:
        registry = load_domain_registry()

        cases = (
            "planning session",
            "decision session",
            "support plan",
            "copy editing",
            "data report",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual("generic", registry.infer_from_context(text))

    def test_infer_from_context_returns_generic_on_ties(self) -> None:
        generic = load_builtin_packs()["generic"]
        first = _pack_payload("alpha")
        first["aliases"] = ["shared"]
        second = _pack_payload("beta")
        second["aliases"] = ["shared"]
        registry = DomainRegistry(
            {
                "generic": generic,
                "alpha": domain_pack_from_dict(first),
                "beta": domain_pack_from_dict(second),
            }
        )

        self.assertEqual("generic", registry.infer_from_context("shared"))


def _write_pack(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_json_pack(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _pack_payload(pack_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "pack_id": pack_id,
        "version": "0.1.0",
        "label": pack_id.replace("_", " ").title(),
        "description": f"{pack_id} test domain pack.",
        "aliases": [pack_id],
        "default_core_domain": "other",
        "decision_types": [
            {
                "id": "choose_path",
                "label": "Choose path",
                "object_type": "decision",
                "layer": "strategy",
                "kind": "choice",
                "default_priority": "P1",
                "default_reversibility": "reversible",
                "criteria": ["fit"],
                "required_evidence": [],
            }
        ],
        "criteria": [
            {
                "id": "fit",
                "label": "Fit",
                "description": "Whether the option fits the stated context.",
            }
        ],
        "evidence_requirements": [],
        "risk_types": [],
        "safety_rules": [],
        "documents": [
            {
                "document_type": "decision-brief",
                "default": True,
                "profile_id": "test_profile",
                "required_sections": ["project", "current-decisions"],
            }
        ],
        "interview": {
            "domain_hints": [],
            "question_templates": {"choose_path": "Which path should be chosen?"},
        },
    }

if __name__ == "__main__":
    unittest.main()
