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

        final, _projection = _iterate(draft_set, max_iterations=2)

        self.assertTrue({"DD-GAP-CONSTRAINT", "DD-GAP-VERIFICATION", "DD-GAP-REVIEW"}.issubset(
            {draft["id"] for draft in final["draft_decisions"]}
        ))

    def test_autopilot_adds_coverage_decisions_for_empty_draft_set(self) -> None:
        draft_set = _complete_draft_set()
        draft_set["draft_decisions"] = []

        final, _projection = _iterate(draft_set, max_iterations=2)

        self.assertTrue({"DD-GAP-PURPOSE", "DD-GAP-CONSTRAINT", "DD-GAP-VERIFICATION", "DD-GAP-REVIEW"}.issubset(
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
    for draft_id, layer in (("DD-002", "constraint"), ("DD-003", "verification"), ("DD-004", "review")):
        draft = deepcopy(base)
        draft["id"] = draft_id
        draft["layer"] = layer
        draft["question"] = f"How should {layer} be handled?"
        payload["draft_decisions"].append(draft)
    return payload


if __name__ == "__main__":
    unittest.main()
