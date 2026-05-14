from __future__ import annotations

import unittest
from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from decide_me.draft_projection import project_draft_set
from decide_me.projections import default_project_state
from tests.helpers.schema_validation import load_schema
from tests.unit.test_draft_set_schema import minimal_valid_draft_set


class DraftProjectionTests(unittest.TestCase):
    def test_projection_schema_valid_for_minimal_draft_set(self) -> None:
        projection = _project(_draft_set())

        Draft202012Validator(load_schema("draft-projection.schema.json"), format_checker=FormatChecker()).validate(
            projection
        )
        self.assertEqual("DS-20260513-001", projection["draft_set_id"])

    def test_projection_detects_missing_recommendation_for_p0(self) -> None:
        draft_set = _draft_set()
        draft_set["draft_decisions"][0]["priority"] = "P0"
        draft_set["draft_decisions"][0]["recommendation"] = ""

        projection = _project(draft_set)

        gap = _gap_by_type(projection, "missing_recommendation")
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

        gap = _gap_by_type(projection, "insufficient_evidence")
        self.assertEqual("high", gap["severity"])

    def test_projection_detects_unknown_evidence(self) -> None:
        draft_set = _draft_set()
        draft_set["draft_decisions"][0]["evidence_coverage"]["status"] = "unknown"

        projection = _project(draft_set)

        gap = _gap_by_type(projection, "insufficient_evidence")
        self.assertEqual("DD-001", gap["target_id"])
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

        self.assertIn("action_without_verification", _gap_types(projection))

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

        gap = _gap_by_type(projection, "accepted_conflict")
        self.assertEqual("critical", gap["severity"])
        self.assertEqual("conflict_blocked", projection["convergence"]["stop_reason"])

    def test_projection_detects_promoted_but_missing_canonical(self) -> None:
        draft_set = _draft_set()
        draft_set["promotion"]["promoted_decision_ids"] = ["DD-001"]

        projection = _project(draft_set)

        gap = _gap_by_type(projection, "promoted_but_missing_canonical")
        self.assertEqual("high", gap["severity"])
        self.assertTrue(gap["blocks_convergence"])

    def test_projection_blocks_saved_converged_when_current_blocking_gap_exists(self) -> None:
        draft_set = _draft_set()
        draft_set["convergence"] = {
            "status": "converged",
            "iterations": 2,
            "stop_reason": "converged",
            "note": "Previously converged.",
        }
        draft_set["draft_decisions"][0]["recommendation"] = ""

        projection = _project(draft_set)

        self.assertEqual("blocked", projection["convergence"]["status"])
        self.assertEqual("user_review_required", projection["convergence"]["stop_reason"])
        self.assertEqual(1, projection["convergence"]["blocking_gap_count"])

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


def _project(draft_set: dict, *, project_state: dict | None = None) -> dict:
    return project_draft_set(
        project_state=project_state or _project_state(),
        draft_set=draft_set,
        current_project_head="abc",
        generated_at="2026-05-13T03:00:00Z",
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


def _gap_types(projection: dict) -> list[str]:
    return [gap["type"] for gap in projection["gap_diagnostics"]]


def _gap_by_type(projection: dict, gap_type: str) -> dict:
    for gap in projection["gap_diagnostics"]:
        if gap["type"] == gap_type:
            return gap
    raise AssertionError(f"missing gap type: {gap_type}")


if __name__ == "__main__":
    unittest.main()
