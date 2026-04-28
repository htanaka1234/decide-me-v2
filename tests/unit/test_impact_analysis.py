from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

from decide_me.constants import LINK_RELATIONS
from decide_me.impact_analysis import CHANGE_KINDS, _RELATION_SEVERITY, analyze_impact


class ImpactAnalysisTests(unittest.TestCase):
    def test_relation_severity_covers_all_link_relations(self) -> None:
        self.assertEqual(LINK_RELATIONS, set(_RELATION_SEVERITY))

    def test_constraint_change_detects_downstream_review_candidates(self) -> None:
        project_state = _impact_project_state()
        original = deepcopy(project_state)

        report = analyze_impact(project_state, "CON-privacy", change_kind="changed")

        self.assertEqual(original, project_state)
        self.assertEqual("CON-privacy", report["root_object_id"])
        self.assertEqual("changed", report["change_kind"])
        self.assertEqual(
            {
                "affected_count": 5,
                "highest_severity": "high",
                "affected_layers": ["constraint", "strategy", "execution", "verification"],
            },
            report["summary"],
        )

        by_id = {item["object_id"]: item for item in report["affected_objects"]}
        self.assertEqual("decision_review_required", by_id["D-auth"]["impact_kind"])
        self.assertEqual("high", by_id["D-auth"]["severity"])
        self.assertEqual("action_rework_candidate", by_id["A-auth"]["impact_kind"])
        self.assertEqual("medium", by_id["A-auth"]["severity"])
        self.assertEqual("verification_review_required", by_id["V-auth"]["impact_kind"])
        self.assertEqual("evidence_review_required", by_id["E-auth"]["impact_kind"])
        self.assertEqual("risk_review_required", by_id["R-auth"]["impact_kind"])
        self.assertEqual(
            {
                "target_object_id": "V-auth",
                "node_ids": ["CON-privacy", "D-auth", "A-auth", "V-auth"],
                "link_ids": [
                    "L-1-constraint-constrains-decision",
                    "L-2-action-addresses-decision",
                    "L-3-verification-requires-action",
                ],
            },
            next(path for path in report["paths"] if path["target_object_id"] == "V-auth"),
        )

    def test_accepted_decision_severity_beats_medium_relation_severity(self) -> None:
        report = analyze_impact(
            _project_state(
                nodes=[
                    _node("E-root", "evidence", "verification"),
                    _node("D-accepted", "decision", "strategy", status="accepted"),
                ],
                edges=[_edge("L-evidence-supports-decision", "E-root", "supports", "D-accepted")],
            ),
            "E-root",
            change_kind="evidence_retracted",
        )

        self.assertEqual("high", report["affected_objects"][0]["severity"])

    def test_duplicate_paths_are_preserved_but_affected_object_is_unique(self) -> None:
        report = analyze_impact(
            _project_state(
                nodes=[
                    _node("D-auth", "decision", "strategy", status="accepted"),
                    _node("A-auth", "action", "execution"),
                ],
                edges=[
                    _edge("L-1-action-addresses-decision", "A-auth", "addresses", "D-auth"),
                    _edge("L-2-action-requires-decision", "A-auth", "requires", "D-auth"),
                ],
            ),
            "D-auth",
            change_kind="changed",
        )

        self.assertEqual(["A-auth"], [item["object_id"] for item in report["affected_objects"]])
        self.assertEqual(2, len(report["paths"]))
        self.assertEqual("high", report["affected_objects"][0]["severity"])
        self.assertEqual("L-2-action-requires-decision", report["affected_objects"][0]["via_link_id"])

    def test_invalidated_targets_are_excluded_without_hiding_live_descendants(self) -> None:
        project_state = _project_state(
            nodes=[
                _node("D-auth", "decision", "strategy", status="accepted"),
                _node("A-auth", "action", "execution", status="invalidated", is_invalidated=True),
                _node("V-auth", "verification", "verification"),
            ],
            edges=[
                _edge("L-1-action-addresses-decision", "A-auth", "addresses", "D-auth"),
                _edge("L-2-verification-requires-action", "V-auth", "requires", "A-auth"),
            ],
        )

        report = analyze_impact(project_state, "D-auth", change_kind="changed")
        self.assertEqual(["V-auth"], [item["object_id"] for item in report["affected_objects"]])
        self.assertEqual(
            ["L-1-action-addresses-decision", "L-2-verification-requires-action"],
            report["affected_links"],
        )

        including_invalidated = analyze_impact(
            project_state,
            "D-auth",
            change_kind="changed",
            include_invalidated=True,
        )
        self.assertEqual(
            ["A-auth", "V-auth"],
            [item["object_id"] for item in including_invalidated["affected_objects"]],
        )

    def test_unknown_root_and_change_kind_fail_clearly(self) -> None:
        project_state = _impact_project_state()

        with self.assertRaisesRegex(ValueError, "change_kind"):
            analyze_impact(project_state, "CON-privacy", change_kind="renamed")
        with self.assertRaisesRegex(ValueError, "unknown object_id"):
            analyze_impact(project_state, "O-missing", change_kind="changed")

    def test_change_kind_is_metadata_only_for_phase_6_3(self) -> None:
        project_state = _impact_project_state()
        baseline = analyze_impact(project_state, "CON-privacy", change_kind="changed")
        baseline["change_kind"] = "<normalized>"
        baseline["generated_at"] = "<normalized>"

        for change_kind in sorted(CHANGE_KINDS):
            with self.subTest(change_kind=change_kind):
                report = analyze_impact(project_state, "CON-privacy", change_kind=change_kind)
                report["change_kind"] = "<normalized>"
                report["generated_at"] = "<normalized>"

                self.assertEqual(baseline, report)

    def test_valid_report_matches_schema(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas" / "impact-analysis.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)

        report = analyze_impact(_impact_project_state(), "CON-privacy", change_kind="changed")

        self.assertEqual([], list(validator.iter_errors(report)))


def _impact_project_state() -> dict:
    return _project_state(
        nodes=[
            _node("CON-privacy", "constraint", "constraint"),
            _node("D-auth", "decision", "strategy", status="accepted"),
            _node("A-auth", "action", "execution"),
            _node("V-auth", "verification", "verification"),
            _node("E-auth", "evidence", "verification"),
            _node("R-auth", "risk", "constraint"),
        ],
        edges=[
            _edge("L-1-constraint-constrains-decision", "CON-privacy", "constrains", "D-auth"),
            _edge("L-2-action-addresses-decision", "A-auth", "addresses", "D-auth"),
            _edge("L-3-verification-requires-action", "V-auth", "requires", "A-auth"),
            _edge("L-4-evidence-derived-from-decision", "E-auth", "derived_from", "D-auth"),
            _edge("L-5-decision-mitigates-risk", "D-auth", "mitigates", "R-auth"),
        ],
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


if __name__ == "__main__":
    unittest.main()
