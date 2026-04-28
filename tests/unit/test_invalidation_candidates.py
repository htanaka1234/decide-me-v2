from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

from decide_me.constants import DECISION_STACK_LAYERS, LINK_RELATIONS, OBJECT_TYPES
from decide_me.impact_analysis import CHANGE_KINDS
from decide_me.invalidation_candidates import CANDIDATE_KINDS, generate_invalidation_candidates


class InvalidationCandidatesTests(unittest.TestCase):
    def test_constraint_change_generates_revalidate_for_high_severity_accepted_decision(self) -> None:
        project_state = _project_state(
            nodes=[
                _node("CON-privacy", "constraint", "constraint"),
                _node("D-auth", "decision", "strategy", status="accepted"),
            ],
            edges=[_edge("L-constraint-constrains-decision", "CON-privacy", "constrains", "D-auth")],
        )
        original = deepcopy(project_state)

        report = generate_invalidation_candidates(project_state, "CON-privacy", change_kind="changed")

        self.assertEqual(original, project_state)
        self.assertEqual("CON-privacy", report["root_object_id"])
        self.assertEqual("changed", report["change_kind"])
        self.assertEqual(
            {
                "affected_count": 1,
                "highest_severity": "high",
                "affected_layers": ["strategy"],
            },
            report["impact_summary"],
        )
        self.assertEqual(1, len(report["candidates"]))
        candidate = report["candidates"][0]
        self.assertEqual("D-auth", candidate["target_object_id"])
        self.assertEqual("decision", candidate["target_object_type"])
        self.assertEqual("accepted", candidate["target_status"])
        self.assertEqual("high", candidate["severity"])
        self.assertEqual("revalidate", candidate["candidate_kind"])
        self.assertTrue(candidate["requires_human_approval"])
        self.assertEqual("explicit_acceptance", candidate["approval_threshold"])
        self.assertEqual("manual", candidate["materialization_status"])
        self.assertEqual([], candidate["proposed_events"])
        self.assertEqual(
            {
                "via_link_id": "L-constraint-constrains-decision",
                "via_relation": "constrains",
                "distance": 1,
                "impact_kind": "decision_review_required",
            },
            candidate["source_impact"],
        )

    def test_invalidated_accepted_decision_generates_invalidate_candidate(self) -> None:
        report = generate_invalidation_candidates(
            _decision_project_state(status="accepted"),
            "CON-privacy",
            change_kind="invalidated",
        )

        self.assertEqual(["invalidate"], [candidate["candidate_kind"] for candidate in report["candidates"]])
        candidate = report["candidates"][0]
        self.assertTrue(candidate["requires_human_approval"])
        self.assertEqual("explicit_acceptance", candidate["approval_threshold"])
        self.assertEqual("materialized", candidate["materialization_status"])
        self.assertEqual(
            [
                {
                    "event_type": "object_status_changed",
                    "payload": {
                        "object_id": "D-auth",
                        "from_status": "accepted",
                        "to_status": "invalidated",
                        "reason": "Accepted decision is affected by an invalidated upstream object.",
                    },
                },
                {
                    "event_type": "object_updated",
                    "payload": {
                        "object_id": "D-auth",
                        "patch": {
                            "metadata": {
                                "invalidated_by": {
                                    "decision_id": "CON-privacy",
                                    "reason": "Accepted decision is affected by an invalidated upstream object.",
                                }
                            }
                        },
                    },
                },
            ],
            candidate["proposed_events"],
        )

    def test_superseded_accepted_decision_generates_supersede_candidate(self) -> None:
        report = generate_invalidation_candidates(
            _decision_project_state(status="accepted"),
            "CON-privacy",
            change_kind="superseded",
        )

        self.assertEqual(["supersede"], [candidate["candidate_kind"] for candidate in report["candidates"]])
        self.assertTrue(report["candidates"][0]["requires_human_approval"])

    def test_supersede_candidate_materializes_supersedes_link_when_root_is_decision(self) -> None:
        report = generate_invalidation_candidates(
            _project_state(
                nodes=[
                    _node("D-new", "decision", "strategy", status="accepted"),
                    _node("D-old", "decision", "strategy", status="accepted"),
                ],
                edges=[_edge("L-new-constrains-old", "D-new", "constrains", "D-old")],
            ),
            "D-new",
            change_kind="superseded",
        )

        candidate = report["candidates"][0]

        self.assertEqual("supersede", candidate["candidate_kind"])
        self.assertEqual("materialized", candidate["materialization_status"])
        self.assertEqual(
            ["object_status_changed", "object_updated", "object_linked"],
            [event["event_type"] for event in candidate["proposed_events"]],
        )
        self.assertEqual(
            {
                "id": "L-D-new-supersedes-D-old",
                "source_object_id": "D-new",
                "relation": "supersedes",
                "target_object_id": "D-old",
                "rationale": "Accepted decision is affected by a superseded upstream object.",
            },
            candidate["proposed_events"][2]["payload"]["link"],
        )

    def test_unresolved_proposed_and_blocked_decisions_generate_review_candidates(self) -> None:
        for status in ("unresolved", "proposed", "blocked"):
            with self.subTest(status=status):
                report = generate_invalidation_candidates(
                    _decision_project_state(status=status),
                    "CON-privacy",
                    change_kind="changed",
                )

                self.assertEqual(["review"], [candidate["candidate_kind"] for candidate in report["candidates"]])
                self.assertFalse(report["candidates"][0]["requires_human_approval"])

    def test_action_generates_revise_and_missing_verification_candidate(self) -> None:
        report = generate_invalidation_candidates(
            _project_state(
                nodes=[
                    _node("D-auth", "decision", "strategy", status="accepted"),
                    _node("A-auth", "action", "execution"),
                ],
                edges=[_edge("L-action-addresses-decision", "A-auth", "addresses", "D-auth")],
            ),
            "D-auth",
            change_kind="changed",
        )

        self.assertEqual(["revise", "add_verification"], [candidate["candidate_kind"] for candidate in report["candidates"]])
        self.assertTrue(all(candidate["target_object_id"] == "A-auth" for candidate in report["candidates"]))
        add_verification = next(
            candidate for candidate in report["candidates"] if candidate["candidate_kind"] == "add_verification"
        )
        verification_id = f"VER-{add_verification['candidate_id'][3:]}"
        self.assertEqual("none", add_verification["approval_threshold"])
        self.assertEqual("materialized", add_verification["materialization_status"])
        self.assertEqual(
            ["object_recorded", "object_linked"],
            [event["event_type"] for event in add_verification["proposed_events"]],
        )
        self.assertEqual(
            {
                "id": verification_id,
                "type": "verification",
                "title": "Verify A-auth",
                "body": "Add verification for A-auth after changed impact from D-auth.",
                "status": "planned",
                "metadata": {
                    "method": "review",
                    "expected_result": "A-auth remains valid after changed impact from D-auth.",
                    "verified_at": None,
                    "result": "pending",
                },
            },
            add_verification["proposed_events"][0]["payload"]["object"],
        )
        self.assertEqual(
            {
                "id": f"L-{verification_id}-verifies-A-auth",
                "source_object_id": verification_id,
                "relation": "verifies",
                "target_object_id": "A-auth",
                "rationale": "Add verification for A-auth after changed impact from D-auth.",
            },
            add_verification["proposed_events"][1]["payload"]["link"],
        )

    def test_invalidated_root_decision_also_generates_action_invalidation_candidate(self) -> None:
        report = generate_invalidation_candidates(
            _project_state(
                nodes=[
                    _node("D-auth", "decision", "strategy", status="accepted"),
                    _node("A-auth", "action", "execution"),
                ],
                edges=[_edge("L-action-addresses-decision", "A-auth", "addresses", "D-auth")],
            ),
            "D-auth",
            change_kind="invalidated",
        )

        self.assertEqual(
            ["revise", "invalidate", "add_verification"],
            [candidate["candidate_kind"] for candidate in report["candidates"]],
        )
        invalidate = next(candidate for candidate in report["candidates"] if candidate["candidate_kind"] == "invalidate")
        self.assertTrue(invalidate["requires_human_approval"])

    def test_live_downstream_verification_suppresses_action_add_verification_candidate(self) -> None:
        report = generate_invalidation_candidates(
            _project_state(
                nodes=[
                    _node("D-auth", "decision", "strategy", status="accepted"),
                    _node("A-auth", "action", "execution"),
                    _node("V-auth", "verification", "verification"),
                ],
                edges=[
                    _edge("L-action-addresses-decision", "A-auth", "addresses", "D-auth"),
                    _edge("L-verification-requires-action", "V-auth", "requires", "A-auth"),
                ],
            ),
            "D-auth",
            change_kind="changed",
        )

        self.assertEqual(
            ["revise", "revalidate"],
            [candidate["candidate_kind"] for candidate in report["candidates"]],
        )

    def test_max_depth_limits_action_add_verification_scope(self) -> None:
        report = generate_invalidation_candidates(
            _project_state(
                nodes=[
                    _node("D-auth", "decision", "strategy", status="accepted"),
                    _node("A-auth", "action", "execution"),
                    _node("V-auth", "verification", "verification"),
                ],
                edges=[
                    _edge("L-action-addresses-decision", "A-auth", "addresses", "D-auth"),
                    _edge("L-verification-requires-action", "V-auth", "requires", "A-auth"),
                ],
            ),
            "D-auth",
            change_kind="changed",
            max_depth=1,
        )

        self.assertEqual(
            ["revise", "add_verification"],
            [candidate["candidate_kind"] for candidate in report["candidates"]],
        )

    def test_verification_and_evidence_generate_revalidate_candidates(self) -> None:
        report = generate_invalidation_candidates(
            _project_state(
                nodes=[
                    _node("D-auth", "decision", "strategy", status="accepted"),
                    _node("V-auth", "verification", "verification"),
                    _node("E-auth", "evidence", "verification"),
                ],
                edges=[
                    _edge("L-verification-requires-decision", "V-auth", "requires", "D-auth"),
                    _edge("L-evidence-derived-from-decision", "E-auth", "derived_from", "D-auth"),
                ],
            ),
            "D-auth",
            change_kind="changed",
        )

        self.assertEqual(
            {"V-auth": "revalidate", "E-auth": "revalidate"},
            {candidate["target_object_id"]: candidate["candidate_kind"] for candidate in report["candidates"]},
        )

    def test_evidence_retracted_generates_evidence_invalidate_candidate(self) -> None:
        report = generate_invalidation_candidates(
            _project_state(
                nodes=[
                    _node("D-auth", "decision", "strategy", status="accepted"),
                    _node("E-auth", "evidence", "verification"),
                ],
                edges=[_edge("L-evidence-derived-from-decision", "E-auth", "derived_from", "D-auth")],
            ),
            "D-auth",
            change_kind="evidence_retracted",
        )

        self.assertEqual(["invalidate"], [candidate["candidate_kind"] for candidate in report["candidates"]])
        self.assertTrue(report["candidates"][0]["requires_human_approval"])

    def test_mitigated_risk_generates_revalidate_candidate(self) -> None:
        report = generate_invalidation_candidates(
            _project_state(
                nodes=[
                    _node("D-auth", "decision", "strategy", status="accepted"),
                    _node("R-auth", "risk", "constraint"),
                ],
                edges=[_edge("L-decision-mitigates-risk", "D-auth", "mitigates", "R-auth")],
            ),
            "D-auth",
            change_kind="changed",
        )

        self.assertEqual(["revalidate"], [candidate["candidate_kind"] for candidate in report["candidates"]])

    def test_non_mitigation_risk_generates_review_candidate(self) -> None:
        report = generate_invalidation_candidates(
            _project_state(
                nodes=[
                    _node("CON-auth", "constraint", "constraint"),
                    _node("R-auth", "risk", "constraint"),
                ],
                edges=[_edge("L-constraint-constrains-risk", "CON-auth", "constrains", "R-auth")],
            ),
            "CON-auth",
            change_kind="changed",
        )

        self.assertEqual(["review"], [candidate["candidate_kind"] for candidate in report["candidates"]])

    def test_low_severity_candidates_are_filtered_by_default(self) -> None:
        project_state = _project_state(
            nodes=[
                _node("D-auth", "decision", "strategy", status="accepted"),
                _node("RT-auth", "revisit_trigger", "review"),
            ],
            edges=[_edge("L-decision-revisits-trigger", "D-auth", "revisits", "RT-auth")],
        )

        filtered = generate_invalidation_candidates(project_state, "D-auth", change_kind="changed")
        included = generate_invalidation_candidates(
            project_state,
            "D-auth",
            change_kind="changed",
            include_low_severity=True,
        )

        self.assertEqual([], filtered["candidates"])
        self.assertEqual(["update_revisit_trigger"], [candidate["candidate_kind"] for candidate in included["candidates"]])
        self.assertEqual("low", included["candidates"][0]["severity"])

    def test_manual_candidate_kinds_do_not_emit_proposed_events(self) -> None:
        cases = [
            (
                "review",
                generate_invalidation_candidates(
                    _decision_project_state(status="unresolved"),
                    "CON-privacy",
                    change_kind="changed",
                )["candidates"][0],
            ),
            (
                "revalidate",
                generate_invalidation_candidates(
                    _decision_project_state(status="accepted"),
                    "CON-privacy",
                    change_kind="changed",
                )["candidates"][0],
            ),
            (
                "revise",
                generate_invalidation_candidates(
                    _project_state(
                        nodes=[
                            _node("D-auth", "decision", "strategy", status="accepted"),
                            _node("A-auth", "action", "execution"),
                            _node("V-auth", "verification", "verification"),
                        ],
                        edges=[
                            _edge("L-action-addresses-decision", "A-auth", "addresses", "D-auth"),
                            _edge("L-verification-requires-action", "V-auth", "requires", "A-auth"),
                        ],
                    ),
                    "D-auth",
                    change_kind="changed",
                )["candidates"][0],
            ),
            (
                "update_revisit_trigger",
                generate_invalidation_candidates(
                    _project_state(
                        nodes=[
                            _node("D-auth", "decision", "strategy", status="accepted"),
                            _node("RT-auth", "revisit_trigger", "review"),
                        ],
                        edges=[_edge("L-decision-revisits-trigger", "D-auth", "revisits", "RT-auth")],
                    ),
                    "D-auth",
                    change_kind="changed",
                    include_low_severity=True,
                )["candidates"][0],
            ),
        ]
        for expected_kind, candidate in cases:
            with self.subTest(candidate_kind=expected_kind):
                self.assertEqual(expected_kind, candidate["candidate_kind"])
                self.assertEqual("manual", candidate["materialization_status"])
                self.assertEqual([], candidate["proposed_events"])

    def test_candidate_ids_are_stable_across_repeated_calls(self) -> None:
        project_state = _decision_project_state(status="accepted")

        first = generate_invalidation_candidates(project_state, "CON-privacy", change_kind="changed")
        second = generate_invalidation_candidates(project_state, "CON-privacy", change_kind="changed")

        self.assertEqual(
            [candidate["candidate_id"] for candidate in first["candidates"]],
            [candidate["candidate_id"] for candidate in second["candidates"]],
        )

    def test_include_invalidated_controls_invalidated_targets(self) -> None:
        project_state = _project_state(
            nodes=[
                _node("D-auth", "decision", "strategy", status="accepted"),
                _node("A-auth", "action", "execution", status="invalidated", is_invalidated=True),
            ],
            edges=[_edge("L-action-addresses-decision", "A-auth", "addresses", "D-auth")],
        )

        filtered = generate_invalidation_candidates(project_state, "D-auth", change_kind="changed")
        included = generate_invalidation_candidates(
            project_state,
            "D-auth",
            change_kind="changed",
            include_invalidated=True,
        )

        self.assertEqual([], filtered["candidates"])
        self.assertEqual(
            ["revise", "add_verification"],
            [candidate["candidate_kind"] for candidate in included["candidates"]],
        )

    def test_invalid_change_kind_is_rejected_by_impact_analysis_contract(self) -> None:
        with self.assertRaisesRegex(ValueError, "change_kind"):
            generate_invalidation_candidates(_decision_project_state(status="accepted"), "CON-privacy", change_kind="renamed")

    def test_valid_report_matches_schema(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas" / "invalidation-candidates.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)

        report = generate_invalidation_candidates(_decision_project_state(status="accepted"), "CON-privacy", change_kind="changed")

        self.assertEqual([], list(validator.iter_errors(report)))

    def test_schema_rejects_invalid_materialized_candidate_shapes(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas" / "invalidation-candidates.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        report = generate_invalidation_candidates(
            _decision_project_state(status="accepted"),
            "CON-privacy",
            change_kind="invalidated",
        )

        cases = (
            (["candidates", 0, "approval_threshold"], "human_review"),
            (["candidates", 0, "proposed_events", 0, "event_type"], "session_closed"),
            (["candidates", 0, "proposed_events", 0, "payload"], None),
        )
        for path, value in cases:
            with self.subTest(path=path):
                payload = deepcopy(report)
                _set_path(payload, path, value)

                errors = list(validator.iter_errors(payload))

                self.assertTrue(errors)

    def test_schema_enums_match_runtime_constants(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas" / "invalidation-candidates.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        self.assertEqual(CHANGE_KINDS, set(schema["$defs"]["change_kind"]["enum"]))
        self.assertEqual(CANDIDATE_KINDS, set(schema["$defs"]["candidate_kind"]["enum"]))
        self.assertEqual(OBJECT_TYPES, set(schema["$defs"]["object_type"]["enum"]))
        self.assertEqual(LINK_RELATIONS, set(schema["$defs"]["link_relation"]["enum"]))
        self.assertEqual(DECISION_STACK_LAYERS, set(schema["$defs"]["decision_stack_layer"]["enum"]))


def _decision_project_state(*, status: str) -> dict:
    return _project_state(
        nodes=[
            _node("CON-privacy", "constraint", "constraint"),
            _node("D-auth", "decision", "strategy", status=status),
        ],
        edges=[_edge("L-constraint-constrains-decision", "CON-privacy", "constrains", "D-auth")],
    )


def _project_state(*, nodes: list[dict], edges: list[dict]) -> dict:
    return {"graph": {"nodes": nodes, "edges": edges}}


def _node(
    object_id: str,
    object_type: str,
    layer: str,
    *,
    status: str = "active",
    is_invalidated: bool = False,
) -> dict:
    return {
        "object_id": object_id,
        "object_type": object_type,
        "layer": layer,
        "status": status,
        "title": object_id,
        "is_frontier": False,
        "is_invalidated": is_invalidated,
    }


def _edge(link_id: str, source: str, relation: str, target: str) -> dict:
    return {
        "link_id": link_id,
        "source_object_id": source,
        "relation": relation,
        "target_object_id": target,
        "source_layer": "strategy",
        "target_layer": "strategy",
    }


def _set_path(payload: dict, path: list[str | int], value: object) -> None:
    current: object = payload
    for part in path[:-1]:
        current = current[part]  # type: ignore[index]
    current[path[-1]] = value  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
