from __future__ import annotations

import unittest
from copy import deepcopy

from decide_me.autopilot import iterate_draft_set
from decide_me.projections import default_project_state
from tests.unit.test_draft_set_schema import minimal_valid_draft_set


class AutopilotIterationTests(unittest.TestCase):
    def test_autopilot_converges_when_no_blocking_gaps(self) -> None:
        draft_set = _complete_draft_set()

        final, projection = _iterate(draft_set)

        self.assertNotIn("convergence", final)
        self.assertEqual("converged", projection["convergence"]["stop_reason"])

    def test_autopilot_adds_verification_for_action_gap(self) -> None:
        draft_set = _complete_draft_set()
        draft_set["draft_actions"] = [{"id": "DACTION-001", "statement": "Do work.", "target_ids": ["DD-001"]}]

        final, projection = _iterate(draft_set)

        self.assertEqual(["DV-GAP-DACTION-001"], [item["id"] for item in final["draft_verifications"]])
        self.assertEqual("converged", projection["convergence"]["stop_reason"])

    def test_autopilot_adds_layer_coverage_decisions(self) -> None:
        draft_set = _complete_draft_set()
        draft_set["draft_decisions"] = [draft_set["draft_decisions"][0]]

        final, projection = _iterate(draft_set, max_iterations=2)

        self.assertTrue({"DD-GAP-PRINCIPLE", "DD-GAP-STRATEGY", "DD-GAP-DESIGN", "DD-GAP-EXECUTION"}.issubset(
            {draft["id"] for draft in final["draft_decisions"]}
        ))
        self.assertIn("frontier_queue", projection)

    def test_autopilot_uses_frontier_order_when_decision_budget_limits_additions(self) -> None:
        draft_set = _complete_draft_set()
        draft_set["draft_decisions"] = [draft_set["draft_decisions"][0]]

        final, projection = _iterate(draft_set, max_iterations=2, max_draft_decisions=2)

        self.assertEqual(
            ["DD-001", "DD-GAP-PRINCIPLE"],
            [draft["id"] for draft in final["draft_decisions"]],
        )
        self.assertLessEqual(len(final["draft_decisions"]), 2)

    def test_autopilot_adds_coverage_decisions_for_empty_draft_set(self) -> None:
        draft_set = _complete_draft_set()
        draft_set["draft_decisions"] = []

        final, _projection = _iterate(draft_set, max_iterations=2)

        self.assertTrue({
            "DD-GAP-PURPOSE",
            "DD-GAP-PRINCIPLE",
            "DD-GAP-CONSTRAINT",
            "DD-GAP-STRATEGY",
            "DD-GAP-DESIGN",
            "DD-GAP-EXECUTION",
            "DD-GAP-VERIFICATION",
            "DD-GAP-REVIEW",
        }.issubset(
            {draft["id"] for draft in final["draft_decisions"]}
        ))

    def test_autopilot_stops_on_evidence_gap_blocked(self) -> None:
        draft_set = _complete_draft_set()
        draft_set["draft_decisions"][0]["priority"] = "P0"
        draft_set["draft_decisions"][0]["evidence_coverage"]["status"] = "none"

        final, projection = _iterate(draft_set)

        self.assertNotIn("convergence", final)
        self.assertEqual("evidence_gap_blocked", projection["convergence"]["stop_reason"])
        self.assertEqual("blocked", projection["convergence"]["status"])

    def test_autopilot_stops_on_conflict_blocked(self) -> None:
        draft_set = _complete_draft_set()
        draft_set["conflicts"] = [{"draft_decision_id": "DD-001", "canonical_decision_id": "D-accepted"}]

        final, projection = _iterate(
            draft_set,
            project_state=_project_state(
                objects=[
                    {
                        "id": "D-accepted",
                        "type": "decision",
                        "status": "accepted",
                        "metadata": {},
                    }
                ]
            ),
        )

        self.assertNotIn("convergence", final)
        self.assertEqual("conflict_blocked", projection["convergence"]["stop_reason"])

    def test_autopilot_stops_on_risk_gate_triggered(self) -> None:
        draft_set = _complete_draft_set()
        draft_set["draft_decisions"][0]["risk_tier"] = "critical"
        draft_set["draft_decisions"][0]["human_review"] = {
            "required": False,
            "mode": "bulk",
            "bulk_promotable": True,
            "reason": "Unsafe.",
        }

        final, projection = _iterate(draft_set)

        self.assertNotIn("convergence", final)
        self.assertEqual("risk_gate_triggered", projection["convergence"]["stop_reason"])

    def test_autopilot_stops_for_no_progress_user_review_required(self) -> None:
        draft_set = _complete_draft_set()
        draft_set["draft_decisions"][0].pop("human_review")

        final, projection = _iterate(draft_set)

        self.assertNotIn("convergence", final)
        self.assertEqual("user_review_required", projection["convergence"]["stop_reason"])

    def test_autopilot_budget_exhausted_when_decision_cap_reached(self) -> None:
        draft_set = _complete_draft_set()
        draft_set["draft_decisions"] = [draft_set["draft_decisions"][0]]

        final, projection = _iterate(draft_set, max_draft_decisions=1)

        self.assertNotIn("convergence", final)
        self.assertEqual("budget_exhausted", projection["convergence"]["stop_reason"])
        self.assertLessEqual(len(final["draft_decisions"]), 1)

    def test_autopilot_ids_are_stable(self) -> None:
        draft_set = _complete_draft_set()
        draft_set["draft_actions"] = [{"id": "DACTION-001", "statement": "Do work.", "target_ids": ["DD-001"]}]

        first, _first_projection = _iterate(deepcopy(draft_set))
        second, _second_projection = _iterate(deepcopy(draft_set))

        self.assertEqual(first["draft_verifications"], second["draft_verifications"])

    def test_autopilot_adds_domain_bound_decision_for_domain_axis_gap(self) -> None:
        draft_set = _complete_draft_set()
        draft_set["source_context"]["domain_pack_id"] = "software"
        draft_set["exploration_contract"]["coverage_targets"].append(_software_safety_verification_target())

        final, projection = _iterate(draft_set, max_iterations=2)

        decisions = {draft["id"]: draft for draft in final["draft_decisions"]}
        self.assertNotIn("DD-GAP-VERIFICATION", decisions)
        generated = decisions["DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION"]
        self.assertEqual(["domain_pack.software.safety_boundary.verification"], generated["coverage_target_ids"])
        self.assertFalse(generated["recommendation"].startswith("Add a "))
        self.assertEqual(
            "Require an observable verification step for safety boundary assumptions before promotion.",
            generated["recommendation"],
        )
        self.assertEqual("partial", generated["evidence_coverage"]["status"])
        self.assertNotEqual("sufficient", generated["evidence_coverage"]["status"])
        self.assertTrue(generated["human_review"]["required"])
        self.assertEqual("individual", generated["human_review"]["mode"])
        self.assertFalse(generated["human_review"]["bulk_promotable"])
        domain_row = next(
            row
            for row in projection["coverage_matrix"]
            if row["axis_id"] == "domain_pack.software.safety_boundary.verification"
        )
        self.assertEqual("covered", domain_row["status"])
        self.assertFalse(domain_row["blocks_convergence"])

    def test_autopilot_adds_core_and_domain_decisions_for_same_layer_gaps(self) -> None:
        draft_set = _complete_draft_set()
        draft_set["source_context"]["domain_pack_id"] = "software"
        draft_set["draft_decisions"] = [
            draft for draft in draft_set["draft_decisions"] if draft["layer"] != "verification"
        ]
        draft_set["exploration_contract"]["coverage_targets"].append(_software_safety_verification_target())

        final, projection = _iterate(draft_set, max_iterations=2)

        decision_ids = {draft["id"] for draft in final["draft_decisions"]}
        self.assertIn("DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION", decision_ids)
        self.assertIn("DD-GAP-VERIFICATION", decision_ids)
        self.assertEqual("covered", _coverage_row(projection, "core.layer.verification")["status"])
        self.assertEqual(
            "covered",
            _coverage_row(projection, "domain_pack.software.safety_boundary.verification")["status"],
        )

    def test_autopilot_respects_budget_for_domain_frontier_order(self) -> None:
        draft_set = _complete_draft_set()
        draft_set["source_context"]["domain_pack_id"] = "software"
        draft_set["draft_decisions"] = [
            draft for draft in draft_set["draft_decisions"] if draft["layer"] != "verification"
        ]
        draft_set["exploration_contract"]["coverage_targets"].append(_software_safety_verification_target())

        final, _projection = _iterate(draft_set, max_iterations=2, max_draft_decisions=8)

        decision_ids = [draft["id"] for draft in final["draft_decisions"]]
        self.assertIn("DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION", decision_ids)
        self.assertNotIn("DD-GAP-VERIFICATION", decision_ids)
        self.assertLessEqual(len(decision_ids), 8)

    def test_autopilot_does_not_auto_expand_past_human_review_safety_blocker(self) -> None:
        draft_set = _complete_draft_set()
        draft_set["source_context"]["domain_pack_id"] = "software"
        draft_set["exploration_contract"]["coverage_targets"].append(_software_safety_verification_target())
        draft_set["draft_decisions"][0]["priority"] = "P0"
        draft_set["draft_decisions"][0]["risk_tier"] = "low"
        draft_set["draft_decisions"][0]["human_review"] = {
            "required": False,
            "mode": "bulk",
            "bulk_promotable": True,
            "reason": "Priority requires individual review.",
        }

        final, projection = _iterate(draft_set, max_iterations=2)

        self.assertFalse(
            any(
                gap["type"] == "unsafe_bulk_review" and gap["target_kind"] == "draft_decision"
                for gap in projection["gap_diagnostics"]
            )
        )
        self.assertTrue(
            any(
                gap["type"] == "unsafe_bulk_review"
                and gap["target_kind"] == "coverage_gap"
                and gap["target_id"] == "core.human_review.safety"
                for gap in projection["gap_diagnostics"]
            )
        )
        self.assertNotIn(
            "DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION",
            {draft["id"] for draft in final["draft_decisions"]},
        )
        self.assertEqual("risk_gate_triggered", projection["convergence"]["stop_reason"])
        self.assertEqual(
            "partial",
            _coverage_row(projection, "domain_pack.software.safety_boundary.verification")["status"],
        )

    def test_autopilot_does_not_auto_expand_past_promotion_safety_blocker(self) -> None:
        draft_set = _complete_draft_set()
        draft_set["source_context"]["domain_pack_id"] = "software"
        draft_set["exploration_contract"]["coverage_targets"].append(_software_safety_verification_target())
        draft_set["draft_decisions"][0]["promotion_recipe"]["proposal_required"] = False

        final, projection = _iterate(draft_set, max_iterations=2)

        self.assertNotIn(
            "DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION",
            {draft["id"] for draft in final["draft_decisions"]},
        )
        self.assertEqual("user_review_required", projection["convergence"]["stop_reason"])
        self.assertEqual(
            "partial",
            _coverage_row(projection, "domain_pack.software.safety_boundary.verification")["status"],
        )

    def test_autopilot_disambiguates_colliding_domain_draft_ids(self) -> None:
        draft_set = _complete_draft_set()
        draft_set["source_context"]["domain_pack_id"] = "software"
        draft_set["exploration_contract"]["coverage_targets"].extend(
            [
                _software_safety_verification_target(),
                _software_safety_verification_target(
                    axis_id="domain_pack.software.safety-boundary.verification",
                    domain_axis_id="safety-boundary",
                    label="Safety-boundary",
                ),
            ]
        )

        final, projection = _iterate(draft_set, max_iterations=2)

        generated = [
            draft
            for draft in final["draft_decisions"]
            if draft.get("coverage_target_ids", [""])[0].startswith("domain_pack.software.safety")
        ]
        self.assertEqual(2, len(generated))
        self.assertEqual(2, len({draft["id"] for draft in generated}))
        self.assertEqual(
            {
                "domain_pack.software.safety_boundary.verification",
                "domain_pack.software.safety-boundary.verification",
            },
            {draft["coverage_target_ids"][0] for draft in generated},
        )
        self.assertTrue(
            any(draft["id"].startswith("DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION-") for draft in generated)
        )
        self.assertEqual(
            "covered",
            _coverage_row(projection, "domain_pack.software.safety_boundary.verification")["status"],
        )
        self.assertEqual(
            "covered",
            _coverage_row(projection, "domain_pack.software.safety-boundary.verification")["status"],
        )


def _iterate(
    draft_set: dict,
    *,
    project_state: dict | None = None,
    max_iterations: int = 3,
    max_draft_decisions: int = 30,
) -> tuple[dict, dict]:
    return iterate_draft_set(
        project_state=project_state or _project_state(),
        draft_set=draft_set,
        current_project_head="abc",
        max_iterations=max_iterations,
        max_draft_decisions=max_draft_decisions,
        risk_threshold="medium",
        now="2026-05-13T03:00:00Z",
    )


def _project_state(*, objects: list[dict] | None = None) -> dict:
    project_state = default_project_state()
    project_state["state"]["project_head"] = "abc"
    project_state["objects"] = objects or []
    project_state["links"] = []
    return project_state


def _coverage_row(projection: dict, axis_id: str) -> dict:
    for row in projection["coverage_matrix"]:
        if row["axis_id"] == axis_id:
            return row
    raise AssertionError(f"missing coverage row: {axis_id}")


def _software_safety_verification_target(
    *,
    axis_id: str = "domain_pack.software.safety_boundary.verification",
    domain_axis_id: str = "safety_boundary",
    label: str = "Safety boundary",
) -> dict:
    return {
        "axis_id": axis_id,
        "axis_type": "decision_stack_layer",
        "value": "verification",
        "priority": "P0",
        "required": True,
        "source": "domain_pack",
        "domain_pack_id": "software",
        "domain_axis_id": domain_axis_id,
        "label": label,
        "match_policy": "explicit_target_or_domain_axis",
    }


def _complete_draft_set() -> dict:
    payload = minimal_valid_draft_set()
    payload["source_context"]["project_head_at_generation"] = "abc"
    base = payload["draft_decisions"][0]
    base["priority"] = "P2"
    base["layer"] = "purpose"
    base["risk_tier"] = "low"
    base["alternatives"] = [
        {
            "option": "Skip autopilot diagnostics",
            "reason_not_recommended": "It would miss deterministic gaps.",
        }
    ]
    base["evidence_coverage"]["status"] = "sufficient"
    base["evidence_coverage"]["missing"] = []
    base["human_review"] = {
        "required": False,
        "mode": "bulk",
        "bulk_promotable": True,
        "reason": "Low-risk review candidate.",
    }
    base["promotion_recipe"]["blocked_for_bulk_acceptance"] = False
    for draft_id, layer in (
        ("DD-002", "principle"),
        ("DD-003", "constraint"),
        ("DD-004", "strategy"),
        ("DD-005", "design"),
        ("DD-006", "execution"),
        ("DD-007", "verification"),
        ("DD-008", "review"),
    ):
        draft = deepcopy(base)
        draft["id"] = draft_id
        draft["layer"] = layer
        draft["question"] = f"How should {layer} be handled?"
        payload["draft_decisions"].append(draft)
    return payload


if __name__ == "__main__":
    unittest.main()
