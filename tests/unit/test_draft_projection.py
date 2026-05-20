from __future__ import annotations

import unittest
from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from decide_me.draft_projection import DraftProjectionValidationError, project_draft_set
from decide_me.draft_sets import default_exploration_contract
from decide_me.projections import default_project_state
from tests.helpers.schema_validation import load_schema
from tests.unit.test_draft_set_schema import minimal_valid_draft_set


class DraftProjectionTests(unittest.TestCase):
    def test_projection_schema_valid_for_minimal_draft_set(self) -> None:
        projection = _project(_draft_set())

        Draft202012Validator(load_schema("draft-projection.schema.json"), format_checker=FormatChecker()).validate(
            projection
        )
        self.assertEqual(4, projection["schema_version"])
        self.assertEqual("DS-20260513-001", projection["draft_set_id"])

    def test_projection_schema_requires_coverage_and_frontier_fields(self) -> None:
        projection = _project(_draft_set())
        schema = load_schema("draft-projection.schema.json")
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        for field in ("coverage_summary", "coverage_matrix", "frontier_queue"):
            with self.subTest(field=field):
                invalid = deepcopy(projection)
                invalid.pop(field)

                errors = list(validator.iter_errors(invalid))

                self.assertTrue(errors)
                self.assertTrue(any(error.validator == "required" for error in errors))

    def test_projection_schema_rejects_invalid_coverage_row(self) -> None:
        projection = _project(_draft_set())
        projection["coverage_matrix"][0]["status"] = "unknown"

        errors = list(
            Draft202012Validator(load_schema("draft-projection.schema.json"), format_checker=FormatChecker()).iter_errors(
                projection
            )
        )

        self.assertTrue(errors)
        self.assertTrue(any(list(error.path)[-1:] == ["status"] for error in errors))

        projection = _project(_draft_set())
        projection["coverage_matrix"][0].pop("source")
        errors = list(
            Draft202012Validator(load_schema("draft-projection.schema.json"), format_checker=FormatChecker()).iter_errors(
                projection
            )
        )

        self.assertTrue(errors)
        self.assertTrue(any(error.validator == "required" for error in errors))

    def test_projection_schema_rejects_invalid_frontier_item(self) -> None:
        projection = _project(_draft_set())
        projection["frontier_queue"][0]["id"] = "FRONTIER-1"

        errors = list(
            Draft202012Validator(load_schema("draft-projection.schema.json"), format_checker=FormatChecker()).iter_errors(
                projection
            )
        )

        self.assertTrue(errors)
        self.assertTrue(any(list(error.path)[-1:] == ["id"] for error in errors))

    def test_default_contract_generates_required_layer_rows(self) -> None:
        projection = _project(_draft_set())
        layer_rows = [row for row in projection["coverage_matrix"] if row["axis_type"] == "decision_stack_layer"]

        self.assertEqual(
            [
                "purpose",
                "principle",
                "constraint",
                "strategy",
                "design",
                "execution",
                "verification",
                "review",
            ],
            sorted([row["value"] for row in layer_rows], key=_layer_sort_key),
        )
        self.assertTrue(all(row["priority"] == "P1" and row["required"] for row in layer_rows))

    def test_missing_required_p1_layer_blocks_convergence(self) -> None:
        projection = _project(_draft_set())
        purpose_row = _coverage_row(projection, "core.layer.purpose")

        self.assertEqual("missing", purpose_row["status"])
        self.assertTrue(purpose_row["blocks_convergence"])
        gap = _gap_by_type(projection, "missing_required_layer", target_id="core.layer.purpose")
        self.assertEqual("coverage_gap", gap["target_kind"])
        self.assertEqual("blocked", projection["convergence"]["status"])

    def test_missing_required_p1_layer_creates_frontier(self) -> None:
        projection = _project(_draft_set())
        gap = _gap_by_type(projection, "missing_required_layer", target_id="core.layer.purpose")
        frontier = _frontier_by_source_gap(projection, gap["id"])

        self.assertEqual(f"F-{gap['id']}", frontier["id"])
        self.assertEqual("purpose layer is missing", frontier["topic"])
        self.assertEqual("P1", frontier["priority"])
        self.assertEqual("open", frontier["status"])
        self.assertEqual([], frontier["evidence_needed"])
        self.assertEqual(
            "Add one complete purpose-layer draft decision before review.",
            frontier["suggested_expansion"],
        )

    def test_pack_derived_required_layer_gap_blocks_and_creates_frontier(self) -> None:
        draft_set = _draft_set()
        draft_set["source_context"]["domain_pack_id"] = "software"
        draft_set["exploration_contract"] = default_exploration_contract(draft_set)

        projection = _project(draft_set)
        row = _coverage_row(projection, "domain_pack.software.safety_boundary.verification")
        gap = _gap_by_type(
            projection,
            "missing_required_layer",
            target_id="domain_pack.software.safety_boundary.verification",
        )
        frontier = _frontier_by_source_gap(projection, gap["id"])

        self.assertEqual("verification", row["value"])
        self.assertEqual("P0", row["priority"])
        self.assertTrue(row["required"])
        self.assertEqual("missing", row["status"])
        self.assertTrue(row["blocks_convergence"])
        self.assertEqual("blocked", projection["convergence"]["status"])
        self.assertEqual(f"F-{gap['id']}", frontier["id"])

    def test_domain_axis_is_not_covered_by_generic_same_layer_decision(self) -> None:
        draft_set = _draft_set()
        draft_set["source_context"]["domain_pack_id"] = "software"
        draft_set["exploration_contract"] = default_exploration_contract(draft_set)
        verification = deepcopy(draft_set["draft_decisions"][0])
        verification["id"] = "DD-VERIFY-GENERIC"
        verification["layer"] = "verification"
        verification["question"] = "How should verification be handled?"
        verification["recommendation"] = "Run a generic verification check."
        verification["rationale"] = "Generic verification covers the core layer."
        draft_set["draft_decisions"].append(verification)

        projection = _project(draft_set)
        core_row = _coverage_row(projection, "core.layer.verification")
        domain_row = _coverage_row(projection, "domain_pack.software.safety_boundary.verification")

        self.assertEqual("covered", core_row["status"])
        self.assertEqual("partial", domain_row["status"])
        self.assertEqual("domain_pack", domain_row["source"])
        self.assertEqual("software", domain_row["domain_pack_id"])
        self.assertEqual("safety_boundary", domain_row["domain_axis_id"])
        self.assertEqual("explicit_target_or_domain_axis", domain_row["match_policy"])
        self.assertTrue(domain_row["blocks_convergence"])

    def test_domain_axis_is_covered_by_explicit_coverage_target_binding(self) -> None:
        draft_set = _draft_set()
        draft_set["source_context"]["domain_pack_id"] = "software"
        draft_set["exploration_contract"] = default_exploration_contract(draft_set)
        verification = deepcopy(draft_set["draft_decisions"][0])
        verification["id"] = "DD-VERIFY-SAFETY"
        verification["layer"] = "verification"
        verification["question"] = "How should the software safety boundary be verified?"
        verification["recommendation"] = "Require observable safety-boundary verification before promotion."
        verification["rationale"] = "The safety boundary needs domain-specific proof."
        verification["coverage_target_ids"] = ["domain_pack.software.safety_boundary.verification"]
        draft_set["draft_decisions"].append(verification)

        projection = _project(draft_set)
        domain_row = _coverage_row(projection, "domain_pack.software.safety_boundary.verification")

        self.assertEqual("covered", domain_row["status"])
        self.assertEqual(["DD-VERIFY-SAFETY"], domain_row["covered_by"])
        self.assertFalse(domain_row["blocks_convergence"])

    def test_explicit_target_without_match_policy_fails_closed(self) -> None:
        draft_set = _draft_set()
        verification = deepcopy(draft_set["draft_decisions"][0])
        verification["id"] = "DD-VERIFY-GENERIC"
        verification["layer"] = "verification"
        verification["question"] = "How should verification be handled?"
        verification["recommendation"] = "Run a generic verification check."
        verification["rationale"] = "Generic verification covers the core layer."
        draft_set["draft_decisions"].append(verification)
        draft_set["exploration_contract"]["coverage_targets"] = [
            {
                "axis_id": "custom.verification.semantic",
                "axis_type": "decision_stack_layer",
                "value": "verification",
                "priority": "P1",
                "required": True,
            }
        ]

        projection = _project(draft_set)
        row = _coverage_row(projection, "custom.verification.semantic")

        self.assertEqual("explicit", row["source"])
        self.assertEqual("missing_fail_closed", row["match_policy"])
        self.assertEqual("partial", row["status"])
        self.assertTrue(row["blocks_convergence"])

    def test_frontier_queue_uses_priority_axis_layer_and_axis_order(self) -> None:
        draft_set = _draft_set()
        draft_set["exploration_contract"]["coverage_targets"] = [
            _target({
                "axis_id": "z.layer.review",
                "axis_type": "decision_stack_layer",
                "value": "review",
                "priority": "P1",
                "required": True,
            }),
            _target({
                "axis_id": "z.layer.strategy",
                "axis_type": "decision_stack_layer",
                "value": "strategy",
                "priority": "P1",
                "required": True,
            }),
            _target({
                "axis_id": "m.layer.purpose",
                "axis_type": "decision_stack_layer",
                "value": "purpose",
                "priority": "P1",
                "required": True,
            }),
            _target({
                "axis_id": "a.layer.strategy",
                "axis_type": "decision_stack_layer",
                "value": "strategy",
                "priority": "P1",
                "required": True,
            }),
            _target({
                "axis_id": "b.evidence",
                "axis_type": "evidence_coverage",
                "value": "sufficient",
                "priority": "P0",
                "required": True,
            }),
        ]

        projection = _project(draft_set)

        self.assertEqual(
            [
                "b.evidence",
                "m.layer.purpose",
                "a.layer.strategy",
                "z.layer.strategy",
                "z.layer.review",
            ],
            [
                _gap_by_id(projection, item["source_gap_id"])["target_id"]
                for item in projection["frontier_queue"]
            ],
        )

    def test_p2_p3_non_required_missing_coverage_does_not_block(self) -> None:
        draft_set = _draft_set()
        draft_set["draft_decisions"][0]["priority"] = "P2"
        draft_set["draft_decisions"][0]["evidence_coverage"]["status"] = "sufficient"
        draft_set["exploration_contract"]["coverage_targets"] = [
            _target({
                "axis_id": "core.layer.strategy.optional",
                "axis_type": "decision_stack_layer",
                "value": "strategy",
                "priority": "P3",
                "required": False,
            })
        ]

        projection = _project(draft_set)
        row = _coverage_row(projection, "core.layer.strategy.optional")

        self.assertEqual("missing", row["status"])
        self.assertFalse(row["blocks_convergence"])
        self.assertEqual(0, projection["convergence"]["blocking_gap_count"])
        self.assertEqual("converged", projection["convergence"]["status"])
        self.assertEqual([], projection["frontier_queue"])

    def test_duplicate_coverage_axis_id_rejected_instead_of_first_wins(self) -> None:
        draft_set = _draft_set()
        draft_set["exploration_contract"]["coverage_targets"] = [
            {
                "axis_id": "target.layer.strategy",
                "axis_type": "decision_stack_layer",
                "value": "strategy",
                "priority": "P3",
                "required": False,
            },
            {
                "axis_id": "target.layer.strategy",
                "axis_type": "decision_stack_layer",
                "value": "strategy",
                "priority": "P1",
                "required": True,
            },
        ]

        with self.assertRaisesRegex(DraftProjectionValidationError, "duplicate coverage target axis_id"):
            _project(draft_set)

    def test_required_evidence_target_uses_target_value_not_observed_value(self) -> None:
        draft_set = _draft_set()
        draft_set["exploration_contract"]["coverage_targets"] = [
            _target({
                "axis_id": "target.evidence.sufficient",
                "axis_type": "evidence_coverage",
                "value": "sufficient",
                "priority": "P1",
                "required": True,
            })
        ]

        projection = _project(draft_set)
        row = _coverage_row(projection, "target.evidence.sufficient")

        self.assertEqual("sufficient", row["value"])
        self.assertEqual("partial", row["observed_value"])
        self.assertEqual("partial", row["status"])
        self.assertTrue(row["blocks_convergence"])

    def test_required_evidence_target_creates_frontier_without_upgrading_evidence(self) -> None:
        draft_set = _draft_set()
        draft_set["exploration_contract"]["coverage_targets"] = [
            _target({
                "axis_id": "target.evidence.sufficient",
                "axis_type": "evidence_coverage",
                "value": "sufficient",
                "priority": "P1",
                "required": True,
            })
        ]

        projection = _project(draft_set)
        gap = _gap_by_type(projection, "insufficient_evidence", target_id="target.evidence.sufficient")
        frontier = _frontier_by_source_gap(projection, gap["id"])

        self.assertEqual("evidence coverage is partial", frontier["topic"])
        self.assertEqual(
            ["Observed evidence coverage is partial; target is sufficient."],
            frontier["evidence_needed"],
        )
        self.assertEqual("partial", draft_set["draft_decisions"][0]["evidence_coverage"]["status"])

    def test_required_human_review_target_uses_target_value_not_observed_value(self) -> None:
        draft_set = _draft_set()
        draft_set["draft_decisions"][0]["priority"] = "P2"
        draft_set["draft_decisions"][0]["risk_tier"] = "low"
        draft_set["draft_decisions"][0]["human_review"] = {
            "required": False,
            "mode": "bulk",
            "bulk_promotable": True,
            "reason": "Low-risk bulk candidate.",
        }
        draft_set["exploration_contract"]["coverage_targets"] = [
            _target({
                "axis_id": "target.review.individual",
                "axis_type": "human_review_safety",
                "value": "individual_required",
                "priority": "P1",
                "required": True,
            })
        ]

        projection = _project(draft_set)
        row = _coverage_row(projection, "target.review.individual")

        self.assertEqual("individual_required", row["value"])
        self.assertEqual("bulk_allowed", row["observed_value"])
        self.assertEqual("missing", row["status"])
        self.assertTrue(row["blocks_convergence"])

    def test_promotion_safety_target_value_observed_value_and_status(self) -> None:
        draft_set = _draft_set()
        draft_set["exploration_contract"]["coverage_targets"] = [
            _target({
                "axis_id": "target.promotion.proposal",
                "axis_type": "promotion_safety",
                "value": "proposal_required",
                "priority": "P1",
                "required": True,
            })
        ]

        projection = _project(draft_set)
        row = _coverage_row(projection, "target.promotion.proposal")

        self.assertEqual("proposal_required", row["value"])
        self.assertEqual("proposal_required", row["observed_value"])
        self.assertEqual("covered", row["status"])

        draft_set["draft_decisions"][0]["promotion_recipe"]["proposal_required"] = False
        projection = _project(draft_set)
        row = _coverage_row(projection, "target.promotion.proposal")

        self.assertEqual("proposal_required", row["value"])
        self.assertEqual("proposal_missing", row["observed_value"])
        self.assertEqual("missing", row["status"])
        self.assertTrue(row["blocks_convergence"])

    def test_projection_detects_stale_draft_set(self) -> None:
        draft_set = _draft_set()
        draft_set["source_context"]["project_head_at_generation"] = "old-head"

        projection = _project(draft_set)

        gap = _gap_by_type(projection, "stale_draft_set")
        self.assertEqual("coverage_gap", gap["target_kind"])
        self.assertTrue(gap["blocks_convergence"])

    def test_projection_detects_missing_recommendation_for_p0(self) -> None:
        draft_set = _draft_set()
        draft_set["draft_decisions"][0]["priority"] = "P0"
        draft_set["draft_decisions"][0]["recommendation"] = ""

        projection = _project(draft_set)

        gap = _gap_by_type(projection, "missing_p0_recommendation")
        self.assertEqual("high", gap["severity"])
        self.assertTrue(gap["blocks_convergence"])

    def test_projection_detects_missing_recommendation_for_p1(self) -> None:
        draft_set = _draft_set()
        draft_set["draft_decisions"][0]["priority"] = "P1"
        draft_set["draft_decisions"][0]["recommendation"] = ""

        projection = _project(draft_set)

        gap = _gap_by_type(projection, "missing_p1_recommendation")
        self.assertEqual("high", gap["severity"])
        self.assertTrue(gap["blocks_convergence"])

    def test_projection_detects_missing_alternatives(self) -> None:
        draft_set = _draft_set()
        draft_set["draft_decisions"][0]["alternatives"] = []

        projection = _project(draft_set)

        self.assertIn("missing_alternatives", _gap_types(projection))

    def test_projection_detects_challenged_evidence(self) -> None:
        draft_set = _draft_set()
        draft_set["draft_decisions"][0]["evidence_coverage"]["status"] = "challenged"

        projection = _project(draft_set)

        gap = _gap_by_type(projection, "challenged_evidence", target_id="DD-001")
        self.assertEqual("high", gap["severity"])

    def test_projection_detects_unknown_evidence(self) -> None:
        draft_set = _draft_set()
        draft_set["draft_decisions"][0]["evidence_coverage"]["status"] = "unknown"

        projection = _project(draft_set)

        gap = _gap_by_type(projection, "insufficient_evidence", target_id="DD-001")
        self.assertEqual("DD-001", gap["target_id"])
        self.assertTrue(gap["blocks_convergence"])

    def test_projection_detects_unsupported_recommendation_for_partial_evidence(self) -> None:
        draft_set = _draft_set()
        draft_set["draft_decisions"][0]["evidence_coverage"]["status"] = "partial"
        draft_set["draft_decisions"][0]["evidence_coverage"]["supporting_object_ids"] = []
        draft_set["draft_decisions"][0]["evidence_coverage"]["source_unit_ids"] = []
        draft_set["draft_decisions"][0]["evidence_coverage"]["missing"] = ["Need source review"]

        projection = _project(draft_set)

        gap = _gap_by_type(projection, "unsupported_recommendation", target_id="DD-001")
        self.assertEqual("high", gap["severity"])
        self.assertTrue(gap["blocks_convergence"])

    def test_projection_detects_dangling_supporting_object(self) -> None:
        draft_set = _draft_set()
        draft_set["draft_decisions"][0]["evidence_coverage"]["supporting_object_ids"] = ["OBJ-missing"]

        projection = _project(draft_set)

        gap = _gap_by_type(projection, "dangling_supporting_object")
        self.assertEqual("high", gap["severity"])
        self.assertTrue(gap["blocks_convergence"])

    def test_projection_rejects_high_risk_bulk_review(self) -> None:
        draft_set = _draft_set()
        draft_set["draft_decisions"][0]["risk_tier"] = "high"
        draft_set["draft_decisions"][0]["human_review"] = {
            "required": False,
            "mode": "bulk",
            "bulk_promotable": True,
            "reason": "Unsafe bulk request.",
        }

        projection = _project(draft_set)

        gap = _gap_by_type(projection, "unsafe_bulk_review")
        self.assertEqual("critical", gap["severity"])
        self.assertTrue(gap["blocks_convergence"])

    def test_projection_detects_action_without_verification(self) -> None:
        draft_set = _draft_set()
        draft_set["draft_actions"] = [{"id": "DACTION-001", "statement": "Do work.", "target_ids": ["DD-001"]}]

        projection = _project(draft_set)

        self.assertIn("verification_without_observable_command", _gap_types(projection))

    def test_projection_detects_dangling_draft_reference(self) -> None:
        draft_set = _draft_set()
        draft_set["draft_verifications"] = [{"id": "DV-001", "target_ids": ["DD-MISSING"], "method": "review"}]

        projection = _project(draft_set)

        self.assertIn("dangling_draft_reference", _gap_types(projection))

    def test_projection_detects_conflict_with_accepted_decision(self) -> None:
        draft_set = _draft_set()
        draft_set["conflicts"] = [{"draft_decision_id": "DD-001", "canonical_decision_id": "D-accepted"}]
        project_state = _project_state(
            objects=[
                {
                    "id": "D-accepted",
                    "type": "decision",
                    "status": "accepted",
                    "metadata": {},
                }
            ]
        )

        projection = _project(draft_set, project_state=project_state)

        gap = _gap_by_type(projection, "accepted_decision_conflict_possible")
        self.assertEqual("critical", gap["severity"])
        self.assertEqual("conflict_blocked", projection["convergence"]["stop_reason"])

    def test_projection_detects_promoted_but_missing_canonical(self) -> None:
        draft_set = _draft_set()
        draft_set["promotion"]["promoted_decision_ids"] = ["DD-001"]

        projection = _project(draft_set)

        gap = _gap_by_type(projection, "promoted_but_missing_canonical")
        self.assertEqual("high", gap["severity"])
        self.assertTrue(gap["blocks_convergence"])

    def test_projection_blocks_when_current_blocking_gap_exists(self) -> None:
        draft_set = _draft_set()
        draft_set["draft_decisions"][0]["recommendation"] = ""

        projection = _project(draft_set)

        self.assertEqual("blocked", projection["convergence"]["status"])
        self.assertEqual("user_review_required", projection["convergence"]["stop_reason"])
        self.assertGreaterEqual(projection["convergence"]["blocking_gap_count"], 1)

    def test_projection_override_cannot_mask_current_blocking_gap(self) -> None:
        draft_set = _draft_set()
        draft_set["draft_decisions"][0]["recommendation"] = ""

        projection = _project(
            draft_set,
            convergence_override={
                "status": "converged",
                "iterations": 2,
                "stop_reason": "converged",
                "explanation": "Previous projection converged.",
            },
        )

        self.assertEqual("blocked", projection["convergence"]["status"])
        self.assertEqual("user_review_required", projection["convergence"]["stop_reason"])
        self.assertGreaterEqual(projection["convergence"]["blocking_gap_count"], 1)

    def test_projection_does_not_mutate_project_state_or_draft_set(self) -> None:
        draft_set = _draft_set()
        project_state = _project_state()
        before_draft_set = deepcopy(draft_set)
        before_project_state = deepcopy(project_state)

        _project(draft_set, project_state=project_state)

        self.assertEqual(before_draft_set, draft_set)
        self.assertEqual(before_project_state, project_state)

    def test_projection_is_deterministically_sorted(self) -> None:
        draft_set = _draft_set()
        draft_set["draft_decisions"][0]["recommendation"] = ""
        draft_set["draft_decisions"][0]["alternatives"] = []
        draft_set["draft_decisions"][0]["evidence_coverage"]["status"] = "none"

        first = _project(draft_set)["gap_diagnostics"]
        second = _project(draft_set)["gap_diagnostics"]

        self.assertEqual(first, second)
        self.assertEqual([f"GAP-{index:03d}" for index in range(1, len(first) + 1)], [gap["id"] for gap in first])


def _project(
    draft_set: dict,
    *,
    project_state: dict | None = None,
    convergence_override: dict | None = None,
) -> dict:
    return project_draft_set(
        project_state=project_state or _project_state(),
        draft_set=draft_set,
        current_project_head="abc",
        generated_at="2026-05-13T03:00:00Z",
        convergence_override=convergence_override,
    )


def _project_state(*, objects: list[dict] | None = None) -> dict:
    project_state = default_project_state()
    project_state["state"]["project_head"] = "abc"
    project_state["objects"] = objects or []
    project_state["links"] = []
    return project_state


def _draft_set() -> dict:
    payload = minimal_valid_draft_set()
    payload["source_context"]["project_head_at_generation"] = "abc"
    draft = payload["draft_decisions"][0]
    draft["priority"] = "P1"
    draft["layer"] = "constraint"
    draft["alternatives"] = [
        {
            "option": "Skip draft diagnostics",
            "reason_not_recommended": "Reviewers would miss structural gaps.",
        }
    ]
    draft["evidence_coverage"]["status"] = "partial"
    draft["evidence_coverage"]["missing"] = []
    return payload


def _target(payload: dict) -> dict:
    normalized = dict(payload)
    normalized.setdefault("source", "explicit")
    normalized.setdefault("label", normalized["axis_id"])
    normalized.setdefault("match_policy", "layer_complete")
    return normalized


def _gap_types(projection: dict) -> list[str]:
    return [gap["type"] for gap in projection["gap_diagnostics"]]


def _gap_by_type(projection: dict, gap_type: str, *, target_id: str | None = None) -> dict:
    for gap in projection["gap_diagnostics"]:
        if gap["type"] == gap_type and (target_id is None or gap.get("target_id") == target_id):
            return gap
    suffix = f" target_id={target_id}" if target_id is not None else ""
    raise AssertionError(f"missing gap type: {gap_type}{suffix}")


def _gap_by_id(projection: dict, gap_id: str) -> dict:
    for gap in projection["gap_diagnostics"]:
        if gap["id"] == gap_id:
            return gap
    raise AssertionError(f"missing gap id: {gap_id}")


def _coverage_row(projection: dict, axis_id: str) -> dict:
    for row in projection["coverage_matrix"]:
        if row["axis_id"] == axis_id:
            return row
    raise AssertionError(f"missing coverage row: {axis_id}")


def _frontier_by_source_gap(projection: dict, source_gap_id: str) -> dict:
    for item in projection["frontier_queue"]:
        if item["source_gap_id"] == source_gap_id:
            return item
    raise AssertionError(f"missing frontier for source gap: {source_gap_id}")


def _layer_sort_key(layer: str) -> int:
    order = {
        "purpose": 0,
        "principle": 1,
        "constraint": 2,
        "strategy": 3,
        "design": 4,
        "execution": 5,
        "verification": 6,
        "review": 7,
    }
    return order[layer]


if __name__ == "__main__":
    unittest.main()
