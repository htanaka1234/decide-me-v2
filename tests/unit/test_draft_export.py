from __future__ import annotations

import unittest
from copy import deepcopy

from jsonschema import Draft202012Validator

from decide_me.draft_export import DraftReviewQueueValidationError, build_review_queue, render_draft_exports, validate_review_queue
from decide_me.draft_projection import project_draft_set
from decide_me.projections import default_project_state
from tests.helpers.schema_validation import load_schema
from tests.unit.test_draft_set_schema import minimal_valid_draft_set


class DraftExportTests(unittest.TestCase):
    def test_review_queue_orders_blocked_before_individual_before_bulk(self) -> None:
        queue = _queue(
            [
                _decision("DD-003", priority="P2"),
                _decision("DD-002", priority="P0", risk_tier="high"),
                _decision("DD-001", priority="P1", recommendation=""),
            ]
        )

        self.assertEqual(["DD-001", "DD-002", "DD-003"], [item["draft_decision_id"] for item in queue["review_order"]])
        self.assertEqual(["blocked", "individual", "bulk"], [item["review_mode"] for item in queue["review_order"]])

    def test_p0_individual_items_sort_before_p1_items(self) -> None:
        queue = _queue(
            [
                _decision("DD-002", priority="P1", human_review={"required": True, "mode": "individual"}),
                _decision("DD-001", priority="P0", human_review={"required": True, "mode": "individual"}),
            ]
        )

        self.assertEqual(["DD-001", "DD-002"], queue["individual_review_required"])

    def test_high_and_critical_risk_are_never_bulk_promotable(self) -> None:
        queue = _queue(
            [
                _decision("DD-001", risk_tier="high"),
                _decision("DD-002", risk_tier="critical"),
            ]
        )

        self.assertEqual([], queue["bulk_promotable"])
        self.assertEqual(["DD-002", "DD-001"], queue["individual_review_required"])

    def test_low_risk_bulk_promotable_item_enters_bulk_list(self) -> None:
        queue = _queue([_decision("DD-001", risk_tier="low")])

        self.assertEqual(["DD-001"], queue["bulk_promotable"])
        self.assertEqual("bulk_materialize_candidate", queue["review_order"][0]["promotion_readiness"])

    def test_missing_recommendation_blocks_item(self) -> None:
        queue = _queue([_decision("DD-001", recommendation="")])

        self.assertEqual(["DD-001"], queue["blocked"])
        self.assertIn("missing recommendation", queue["review_order"][0]["reasons"])

    def test_missing_alternatives_blocks_item(self) -> None:
        queue = _queue([_decision("DD-001", alternatives=[])])

        self.assertEqual(["DD-001"], queue["blocked"])
        self.assertIn("missing alternatives", queue["review_order"][0]["reasons"])

    def test_challenged_evidence_forces_individual_review(self) -> None:
        queue = _queue([_decision("DD-001", evidence_status="challenged")])

        self.assertEqual(["DD-001"], queue["individual_review_required"])
        self.assertIn("evidence_coverage.status is challenged", queue["review_order"][0]["reasons"])

    def test_unknown_and_partial_missing_evidence_do_not_enter_bulk(self) -> None:
        queue = _queue([_decision("DD-001", evidence_status="unknown")])

        self.assertEqual([], queue["bulk_promotable"])
        self.assertEqual(["DD-001"], queue["individual_review_required"])

        queue = _queue([_decision("DD-001", evidence_status="partial", missing=["Need source review"])])

        self.assertEqual([], queue["bulk_promotable"])
        self.assertEqual(["DD-001"], queue["individual_review_required"])
        self.assertIn("partial evidence has missing items", queue["review_order"][0]["reasons"])

    def test_malformed_promoted_draft_remains_blocked(self) -> None:
        queue = _queue(
            [_decision("DD-001", recommendation="")],
            promotion={"promoted_decision_ids": ["DD-001"]},
        )

        self.assertEqual("blocked", queue["review_order"][0]["review_mode"])
        self.assertEqual(["DD-001"], queue["blocked"])
        self.assertIn("missing recommendation", queue["review_order"][0]["reasons"])
        self.assertTrue(any("informational only" in reason for reason in queue["review_order"][0]["reasons"]))

    def test_critical_promoted_draft_remains_individual_in_pr2(self) -> None:
        queue = _queue(
            [_decision("DD-001", risk_tier="critical")],
            promotion={"promoted_decision_ids": ["DD-001"]},
        )

        self.assertEqual("individual", queue["review_order"][0]["review_mode"])
        self.assertEqual([], queue["blocked"])
        self.assertEqual(["DD-001"], queue["individual_review_required"])
        self.assertEqual(["DD-001"], queue["must_not_bulk_promote"])
        self.assertIn("risk_tier is critical", queue["review_order"][0]["reasons"])
        self.assertTrue(any("informational only" in reason for reason in queue["review_order"][0]["reasons"]))

    def test_accepted_status_blocks_item(self) -> None:
        queue = _queue([_decision("DD-001", status="accepted")])

        self.assertEqual(["DD-001"], queue["blocked"])
        self.assertIn("status accepted is not allowed for draft decisions", queue["review_order"][0]["reasons"])

    def test_review_queue_schema_validates(self) -> None:
        queue = _queue([_decision("DD-001")])

        self.assertEqual(2, queue["schema_version"])
        self.assertIn("coverage_summary", queue)
        self.assertIn("blocking_gaps", queue)
        self.assertEqual("DD-001", queue["review_order"][0]["target_id"])
        self.assertEqual("draft_decision", queue["review_order"][0]["target_kind"])
        validate_review_queue(queue)
        Draft202012Validator(load_schema("draft-review-queue.schema.json")).validate(queue)

    def test_coverage_blocker_enters_review_queue_and_excludes_bulk(self) -> None:
        draft_set = _draft_set([_decision("DD-001", layer="purpose")])
        projection = _projection(draft_set)
        queue = _queue(draft_set["draft_decisions"], draft_projection=projection)

        self.assertIn("core.layer.strategy", queue["blocked"])
        self.assertIn("DD-001", queue["individual_review_required"])
        self.assertEqual([], queue["bulk_promotable"])
        self.assertGreater(queue["coverage_summary"]["blocking_gap_count"], 0)
        self.assertTrue(queue["blocking_gaps"])
        coverage_item = next(item for item in queue["review_order"] if item["target_id"] == "core.layer.strategy")
        self.assertEqual("coverage_gap", coverage_item["target_kind"])
        self.assertEqual("missing_required_layer", coverage_item["gap_type"])

    def test_partial_coverage_blocker_enters_individual_review(self) -> None:
        draft_set = _draft_set(
            [
                _decision("DD-001", layer="strategy", recommendation="", evidence_status="sufficient"),
            ]
        )
        projection = _projection(draft_set)
        queue = _queue(draft_set["draft_decisions"], draft_projection=projection)

        self.assertIn("core.layer.strategy", queue["individual_review_required"])
        coverage_item = next(item for item in queue["review_order"] if item["target_id"] == "core.layer.strategy")
        self.assertEqual("individual", coverage_item["review_mode"])

    def test_review_queue_schema_rejects_invalid_id_and_generated_at(self) -> None:
        queue = _queue([_decision("DD-001")])
        queue["draft_set_id"] = "DS-test"

        with self.assertRaisesRegex(DraftReviewQueueValidationError, "draft_set_id"):
            validate_review_queue(queue)

        queue = _queue([_decision("DD-001")])
        queue["generated_at"] = "not-a-date-time"

        with self.assertRaisesRegex(DraftReviewQueueValidationError, "generated_at"):
            validate_review_queue(queue)

    def test_review_queue_schema_rejects_malformed_general_target_item(self) -> None:
        queue = _queue([_decision("DD-001")])
        queue["review_order"][0].pop("target_id")

        with self.assertRaisesRegex(DraftReviewQueueValidationError, "target_id"):
            validate_review_queue(queue)

    def test_render_preflight_contains_draft_not_accepted_banner(self) -> None:
        draft_set = _draft_set([_decision("DD-001")])
        queue = _queue(draft_set["draft_decisions"])

        rendered = render_draft_exports(
            draft_set,
            queue,
            current_project_head="head-1",
            generated_at="2026-05-13T03:00:00Z",
        )

        self.assertIn("DRAFT / NOT ACCEPTED", rendered["preflight.md"])
        self.assertIn("## Human Approval Plan", rendered["preflight.md"])

    def test_render_draft_decisions_contains_recommendation_alternatives_and_missing_evidence(self) -> None:
        draft = _decision(
            "DD-001",
            recommendation="Use sidecar draft export.",
            alternatives=[{"option": "Write canonical events", "reason_not_recommended": "Would look accepted."}],
            missing=["Need maintainer review"],
        )
        draft_set = _draft_set([draft])
        queue = _queue([draft])

        rendered = render_draft_exports(
            draft_set,
            queue,
            current_project_head="head-1",
            generated_at="2026-05-13T03:00:00Z",
        )

        body = rendered["draft-decisions.md"]
        self.assertIn("Use sidecar draft export.", body)
        self.assertIn("Write canonical events", body)
        self.assertIn("Would look accepted.", body)
        self.assertIn("Need maintainer review", body)

    def test_render_assumptions_risks_contains_invalidates_if_false_and_high_risk_items(self) -> None:
        draft_set = _draft_set([_decision("DD-001", risk_tier="critical")])
        draft_set["draft_assumptions"] = [
            {
                "id": "DA-001",
                "statement": "Draft exports are derived views.",
                "evidence_status": "partial",
                "missing_evidence": ["Need usage feedback"],
                "invalidates_if_false": "Promotion must be redesigned.",
                "owner": "maintainer",
            }
        ]
        draft_set["draft_risks"] = [
            {
                "id": "DR-001",
                "statement": "Draft is mistaken for accepted state.",
                "severity": "high",
                "likelihood": "medium",
                "risk_tier": "high",
                "reversibility": "partially_reversible",
                "approval_threshold": "human_review",
            }
        ]
        queue = _queue(draft_set["draft_decisions"])

        rendered = render_draft_exports(
            draft_set,
            queue,
            current_project_head="head-1",
            generated_at="2026-05-13T03:00:00Z",
        )

        body = rendered["assumptions-risks.md"]
        self.assertIn("Invalidates if false", body)
        self.assertIn("Promotion must be redesigned.", body)
        self.assertIn("Draft is mistaken for accepted state.", body)
        self.assertIn("High/Critical risk requires individual review.", body)


def _queue(
    decisions: list[dict],
    *,
    promotion: dict | None = None,
    current_project_head: str | None = "head-1",
    draft_projection: dict | None = None,
) -> dict:
    draft_set = _draft_set(decisions)
    if promotion is not None:
        draft_set["promotion"].update(
            {
                "promoted_decision_ids": [],
                "bulk_promotable_ids": [],
                "individual_review_required_ids": [],
            }
        )
        draft_set["promotion"].update(promotion)
    return build_review_queue(
        draft_set,
        current_project_head=current_project_head,
        generated_at="2026-05-13T03:00:00Z",
        draft_projection=draft_projection,
    )


def _draft_set(decisions: list[dict]) -> dict:
    payload = minimal_valid_draft_set()
    payload["source_context"]["project_head_at_generation"] = "head-1"
    payload["draft_decisions"] = deepcopy(decisions)
    return payload


def _projection(draft_set: dict) -> dict:
    project_state = default_project_state()
    project_state["state"]["project_head"] = "head-1"
    project_state["objects"] = []
    project_state["links"] = []
    return project_draft_set(
        project_state=project_state,
        draft_set=draft_set,
        current_project_head="head-1",
        generated_at="2026-05-13T03:00:00Z",
    )


def _decision(
    draft_id: str,
    *,
    status: str = "recommended",
    priority: str = "P2",
    layer: str = "design",
    recommendation: str = "Store generated draft review output as sidecars.",
    alternatives: list[dict] | None = None,
    risk_tier: str = "low",
    evidence_status: str = "sufficient",
    missing: list[str] | None = None,
    human_review: dict | None = None,
) -> dict:
    draft = deepcopy(minimal_valid_draft_set()["draft_decisions"][0])
    draft.update(
        {
            "id": draft_id,
            "status": status,
            "priority": priority,
            "layer": layer,
            "question": f"How should {draft_id} be handled?",
            "recommendation": recommendation,
            "alternatives": alternatives
            if alternatives is not None
            else [{"option": "Write accepted state", "reason_not_recommended": "Promotion is out of scope."}],
            "risk_tier": risk_tier,
        }
    )
    draft["evidence_coverage"]["status"] = evidence_status
    draft["evidence_coverage"]["missing"] = missing or []
    draft["human_review"] = {
        "required": False,
        "mode": "bulk",
        "bulk_promotable": True,
        "reason": "Low-risk draft review surface.",
    }
    if human_review is not None:
        draft["human_review"].update(human_review)
    draft["promotion_recipe"]["blocked_for_bulk_acceptance"] = False
    return draft


if __name__ == "__main__":
    unittest.main()
