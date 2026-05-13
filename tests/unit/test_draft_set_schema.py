from __future__ import annotations

import unittest
from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from tests.helpers.schema_validation import load_schema


class DraftSetSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = load_schema("draft-decision-set.schema.json")
        self.validator = Draft202012Validator(self.schema, format_checker=FormatChecker())

    def test_valid_minimal_draft_set_matches_schema(self) -> None:
        self.validator.validate(minimal_valid_draft_set())

    def test_schema_requires_core_fields(self) -> None:
        for field in (
            "schema_version",
            "id",
            "status",
            "mode",
            "created_at",
            "generated_by",
            "goal",
            "source_context",
            "convergence",
            "draft_decisions",
        ):
            payload = minimal_valid_draft_set()
            payload.pop(field)

            errors = list(self.validator.iter_errors(payload))

            self.assertTrue(errors, field)
            self.assertTrue(any(error.validator == "required" for error in errors), field)

    def test_schema_rejects_accepted_draft_decision(self) -> None:
        payload = minimal_valid_draft_set()
        payload["draft_decisions"][0]["status"] = "accepted"

        errors = list(self.validator.iter_errors(payload))

        self.assertTrue(errors)
        self.assertTrue(any(list(error.path) == ["draft_decisions", 0, "status"] for error in errors))

    def test_schema_rejects_unknown_top_level_field(self) -> None:
        payload = minimal_valid_draft_set()
        payload["project_state"] = {}

        errors = list(self.validator.iter_errors(payload))

        self.assertTrue(errors)
        self.assertTrue(any(error.validator == "additionalProperties" for error in errors))

    def test_schema_rejects_invalid_draft_set_id(self) -> None:
        payload = minimal_valid_draft_set()
        payload["id"] = "../DS-20260513-001"

        errors = list(self.validator.iter_errors(payload))

        self.assertTrue(errors)
        self.assertTrue(any(list(error.path) == ["id"] for error in errors))

    def test_schema_rejects_invalid_layer_priority_frontier_kind(self) -> None:
        cases = (
            ("layer", "not-a-layer"),
            ("priority", "P9"),
            ("frontier", "eventually"),
            ("kind", "preference"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                payload = minimal_valid_draft_set()
                payload["draft_decisions"][0][field] = value

                errors = list(self.validator.iter_errors(payload))

                self.assertTrue(errors)
                self.assertTrue(any(list(error.path) == ["draft_decisions", 0, field] for error in errors))

    def test_schema_allows_empty_optional_arrays(self) -> None:
        payload = minimal_valid_draft_set()
        for field in (
            "draft_assumptions",
            "draft_risks",
            "draft_actions",
            "draft_verifications",
            "conflicts",
            "review_queue",
        ):
            payload[field] = []

        self.validator.validate(payload)


def minimal_valid_draft_set() -> dict:
    return deepcopy(
        {
            "schema_version": 1,
            "id": "DS-20260513-001",
            "status": "generated",
            "mode": "autopilot-draft",
            "created_at": "2026-05-13T03:00:00Z",
            "generated_by": "test",
            "goal": {
                "id": "G-20260513-001",
                "title": "Add draft decision sets",
                "desired_outcome": "Store draft sets safely.",
                "constraints": ["Do not mutate canonical runtime"],
            },
            "source_context": {
                "project_head_at_generation": "abc",
                "project_state_ref": "project-state.json",
                "included_session_ids": [],
                "included_object_ids": [],
                "domain_pack_id": "generic",
            },
            "convergence": {
                "status": "budget_exhausted",
                "iterations": 1,
                "stop_reason": "mvp_single_pass",
                "note": "Single pass.",
            },
            "draft_decisions": [
                {
                    "id": "DD-001",
                    "status": "recommended",
                    "layer": "constraint",
                    "priority": "P0",
                    "frontier": "now",
                    "kind": "choice",
                    "question": "Where should draft sets be stored?",
                    "recommendation": "Store them as sidecars.",
                    "rationale": "Avoid canonical event log pollution.",
                    "alternatives": [],
                    "risk_tier": "medium",
                    "reversibility": "reversible",
                    "evidence_coverage": {
                        "status": "partial",
                        "supporting_object_ids": [],
                        "source_unit_ids": [],
                        "missing": [],
                    },
                    "human_review": {
                        "required": True,
                        "mode": "individual",
                        "bulk_promotable": False,
                        "reason": "Source-of-truth policy.",
                    },
                    "promotion_recipe": {
                        "canonical_object_type": "decision",
                        "canonical_initial_status": "unresolved",
                        "proposal_required": True,
                        "acceptance_mode_allowed": ["explicit"],
                        "blocked_for_bulk_acceptance": True,
                    },
                }
            ],
            "draft_assumptions": [],
            "draft_risks": [],
            "draft_actions": [],
            "draft_verifications": [],
            "conflicts": [],
            "review_queue": [],
            "promotion": {
                "promoted_decision_ids": [],
                "bulk_promotable_ids": [],
                "individual_review_required_ids": [],
            },
        }
    )


if __name__ == "__main__":
    unittest.main()
