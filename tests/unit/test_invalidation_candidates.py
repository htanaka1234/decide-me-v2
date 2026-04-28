from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

from decide_me.constants import DECISION_STACK_LAYERS, LINK_RELATIONS, OBJECT_TYPES
from decide_me.events import build_event
from decide_me.impact_analysis import CHANGE_KINDS
from decide_me.invalidation_candidates import CANDIDATE_KINDS, generate_invalidation_candidates
from decide_me.projections import apply_events_to_bundle, rebuild_projections
from decide_me.validate import validate_projection_bundle


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
            _project_state(
                nodes=[
                    _node("D-root", "decision", "strategy", status="accepted"),
                    _node("D-auth", "decision", "strategy", status="accepted"),
                ],
                edges=[_edge("L-root-constrains-decision", "D-root", "constrains", "D-auth")],
            ),
            "D-root",
            change_kind="invalidated",
        )

        self.assertEqual(["invalidate"], [candidate["candidate_kind"] for candidate in report["candidates"]])
        candidate = report["candidates"][0]
        self.assertTrue(candidate["requires_human_approval"])
        self.assertEqual("explicit_acceptance", candidate["approval_threshold"])
        self.assertEqual("materialized", candidate["materialization_status"])
        self.assertEqual(["object_status_changed", "object_updated"], _event_types(candidate))
        status_change, metadata_update = candidate["proposed_events"]
        self.assertEqual(report["generated_at"], status_change["ts"])
        self.assertEqual(report["generated_at"], status_change["payload"]["changed_at"])
        self.assertEqual(
            {
                "object_id": "D-auth",
                "from_status": "accepted",
                "to_status": "invalidated",
                "reason": "Accepted decision is affected by an invalidated upstream object.",
                "changed_at": report["generated_at"],
            },
            status_change["payload"],
        )
        self.assertEqual(report["generated_at"], metadata_update["ts"])
        self.assertEqual(
            {
                "decision_id": "D-root",
                "invalidated_at": report["generated_at"],
                "reason": "Accepted decision is affected by an invalidated upstream object.",
            },
            metadata_update["payload"]["patch"]["metadata"]["invalidated_by"],
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
            _event_types(candidate),
        )
        link_event = candidate["proposed_events"][2]
        self.assertEqual(
            {
                "id": "L-D-new-supersedes-D-old",
                "source_object_id": "D-new",
                "relation": "supersedes",
                "target_object_id": "D-old",
                "rationale": "Accepted decision is affected by a superseded upstream object.",
                "created_at": report["generated_at"],
                "source_event_ids": [link_event["event_id"]],
            },
            link_event["payload"]["link"],
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
            _event_types(add_verification),
        )
        object_event, link_event = add_verification["proposed_events"]
        self.assertEqual(
            {
                "id": verification_id,
                "type": "verification",
                "title": "Verify A-auth",
                "body": "Add verification for A-auth after changed impact from D-auth.",
                "status": "planned",
                "created_at": report["generated_at"],
                "updated_at": None,
                "source_event_ids": [object_event["event_id"]],
                "metadata": {
                    "method": "review",
                    "expected_result": "A-auth remains valid after changed impact from D-auth.",
                    "verified_at": None,
                    "result": "pending",
                },
            },
            object_event["payload"]["object"],
        )
        self.assertEqual(
            {
                "id": f"L-{verification_id}-verifies-A-auth",
                "source_object_id": verification_id,
                "relation": "verifies",
                "target_object_id": "A-auth",
                "rationale": "Add verification for A-auth after changed impact from D-auth.",
                "created_at": report["generated_at"],
                "source_event_ids": [link_event["event_id"]],
            },
            link_event["payload"]["link"],
        )

    def test_invalidate_candidate_event_specs_apply_and_validate(self) -> None:
        bundle = _supersede_bundle()
        report = generate_invalidation_candidates(
            bundle["project_state"],
            "D-new",
            change_kind="invalidated",
        )
        candidate = next(candidate for candidate in report["candidates"] if candidate["target_object_id"] == "D-old")

        updated = _apply_candidate_event_specs(bundle, candidate)
        validate_projection_bundle(updated)

        decision = _object_by_id(updated["project_state"], "D-old")
        self.assertEqual("invalidated", decision["status"])
        self.assertEqual(
            {
                "decision_id": "D-new",
                "invalidated_at": report["generated_at"],
                "reason": "Accepted decision is affected by an invalidated upstream object.",
            },
            decision["metadata"]["invalidated_by"],
        )

    def test_supersede_candidate_event_specs_apply_and_validate(self) -> None:
        bundle = _supersede_bundle()
        report = generate_invalidation_candidates(
            bundle["project_state"],
            "D-new",
            change_kind="superseded",
        )
        candidate = next(candidate for candidate in report["candidates"] if candidate["target_object_id"] == "D-old")

        updated = _apply_candidate_event_specs(bundle, candidate)
        validate_projection_bundle(updated)

        old_decision = _object_by_id(updated["project_state"], "D-old")
        self.assertEqual("invalidated", old_decision["status"])
        self.assertIn("L-D-new-supersedes-D-old", _links_by_id(updated["project_state"]))

    def test_add_verification_candidate_event_specs_apply_and_validate(self) -> None:
        bundle = _action_without_verification_bundle()
        report = generate_invalidation_candidates(
            bundle["project_state"],
            "D-auth",
            change_kind="changed",
        )
        candidate = next(candidate for candidate in report["candidates"] if candidate["candidate_kind"] == "add_verification")

        updated = _apply_candidate_event_specs(bundle, candidate)
        validate_projection_bundle(updated)

        verification_id = f"VER-{candidate['candidate_id'][3:]}"
        verification = _object_by_id(updated["project_state"], verification_id)
        self.assertEqual("verification", verification["type"])
        link = _links_by_id(updated["project_state"])[f"L-{verification_id}-verifies-A-auth"]
        self.assertEqual("A-auth", link["target_object_id"])

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
            _project_state(
                nodes=[
                    _node("D-root", "decision", "strategy", status="accepted"),
                    _node("D-auth", "decision", "strategy", status="accepted"),
                ],
                edges=[_edge("L-root-constrains-decision", "D-root", "constrains", "D-auth")],
            ),
            "D-root",
            change_kind="invalidated",
        )

        cases = (
            (["candidates", 0, "approval_threshold"], "human_review"),
            (["candidates", 0, "proposed_events", 0, "event_type"], "session_closed"),
            (["candidates", 0, "proposed_events", 0, "payload"], None),
            (["candidates", 0, "proposed_events", 0, "payload", "changed_at"], None),
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


def _supersede_bundle() -> dict:
    events = [
        *_base_runtime_events(),
        _runtime_event(3, "S-001", "object_recorded", {"object": _runtime_object("D-new", "decision", "E-test-3", status="accepted")}),
        _runtime_event(4, "S-001", "object_recorded", {"object": _runtime_object("P-new", "proposal", "E-test-4")}),
        _runtime_event(5, "S-001", "object_recorded", {"object": _runtime_object("O-new", "option", "E-test-5")}),
        _runtime_event(6, "S-001", "object_recorded", {"object": _runtime_object("D-old", "decision", "E-test-6", status="accepted")}),
        _runtime_event(7, "S-001", "object_recorded", {"object": _runtime_object("P-old", "proposal", "E-test-7")}),
        _runtime_event(8, "S-001", "object_recorded", {"object": _runtime_object("O-old", "option", "E-test-8")}),
        _runtime_event(9, "S-001", "object_linked", {"link": _runtime_link("L-P-new-addresses-D-new", "P-new", "addresses", "D-new", "E-test-9")}),
        _runtime_event(10, "S-001", "object_linked", {"link": _runtime_link("L-P-new-recommends-O-new", "P-new", "recommends", "O-new", "E-test-10")}),
        _runtime_event(11, "S-001", "object_linked", {"link": _runtime_link("L-D-new-accepts-P-new", "D-new", "accepts", "P-new", "E-test-11")}),
        _runtime_event(12, "S-001", "object_linked", {"link": _runtime_link("L-P-old-addresses-D-old", "P-old", "addresses", "D-old", "E-test-12")}),
        _runtime_event(13, "S-001", "object_linked", {"link": _runtime_link("L-P-old-recommends-O-old", "P-old", "recommends", "O-old", "E-test-13")}),
        _runtime_event(14, "S-001", "object_linked", {"link": _runtime_link("L-D-old-accepts-P-old", "D-old", "accepts", "P-old", "E-test-14")}),
        _runtime_event(15, "S-001", "object_linked", {"link": _runtime_link("L-new-constrains-old", "D-new", "constrains", "D-old", "E-test-15")}),
    ]
    bundle = rebuild_projections(events)
    validate_projection_bundle(bundle)
    return bundle


def _action_without_verification_bundle() -> dict:
    events = [
        *_base_runtime_events(),
        _runtime_event(3, "S-001", "object_recorded", {"object": _runtime_object("D-auth", "decision", "E-test-3", status="accepted")}),
        _runtime_event(4, "S-001", "object_recorded", {"object": _runtime_object("P-auth", "proposal", "E-test-4")}),
        _runtime_event(5, "S-001", "object_recorded", {"object": _runtime_object("O-auth", "option", "E-test-5")}),
        _runtime_event(6, "S-001", "object_recorded", {"object": _runtime_object("A-auth", "action", "E-test-6")}),
        _runtime_event(7, "S-001", "object_linked", {"link": _runtime_link("L-P-auth-addresses-D-auth", "P-auth", "addresses", "D-auth", "E-test-7")}),
        _runtime_event(8, "S-001", "object_linked", {"link": _runtime_link("L-P-auth-recommends-O-auth", "P-auth", "recommends", "O-auth", "E-test-8")}),
        _runtime_event(9, "S-001", "object_linked", {"link": _runtime_link("L-D-auth-accepts-P-auth", "D-auth", "accepts", "P-auth", "E-test-9")}),
        _runtime_event(10, "S-001", "object_linked", {"link": _runtime_link("L-action-addresses-decision", "A-auth", "addresses", "D-auth", "E-test-10")}),
    ]
    bundle = rebuild_projections(events)
    validate_projection_bundle(bundle)
    return bundle


def _base_runtime_events() -> list[dict]:
    return [
        _runtime_event(
            1,
            "SYSTEM",
            "project_initialized",
            {
                "project": {
                    "name": "Demo",
                    "objective": "Plan it.",
                    "current_milestone": "MVP",
                    "stop_rule": "Resolve blockers.",
                }
            },
        ),
        _runtime_event(
            2,
            "S-001",
            "session_created",
            {
                "session": {
                    "id": "S-001",
                    "started_at": "2026-04-23T13:02:00Z",
                    "last_seen_at": "2026-04-23T13:02:00Z",
                    "bound_context_hint": "Invalidation candidate test",
                }
            },
        ),
    ]


def _runtime_event(sequence: int, session_id: str, event_type: str, payload: dict) -> dict:
    return build_event(
        tx_id=f"T-test-{sequence}",
        tx_index=1,
        tx_size=1,
        event_id=f"E-test-{sequence}",
        session_id=session_id,
        event_type=event_type,
        payload=payload,
        timestamp=f"2026-04-23T13:{sequence:02d}:00Z",
        project_head="H-before",
    )


def _runtime_object(object_id: str, object_type: str, event_id: str, *, status: str = "active") -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": object_id,
        "body": None,
        "status": status,
        "created_at": "2026-04-23T13:00:00Z",
        "updated_at": None,
        "source_event_ids": [event_id],
        "metadata": {},
    }


def _runtime_link(link_id: str, source: str, relation: str, target: str, event_id: str) -> dict:
    return {
        "id": link_id,
        "source_object_id": source,
        "relation": relation,
        "target_object_id": target,
        "rationale": "Invalidation candidate test link.",
        "created_at": "2026-04-23T13:00:00Z",
        "source_event_ids": [event_id],
    }


def _apply_candidate_event_specs(bundle: dict, candidate: dict) -> dict:
    tx_size = len(candidate["proposed_events"])
    events = [
        build_event(
            tx_id=f"T-{candidate['candidate_id']}",
            tx_index=index,
            tx_size=tx_size,
            event_id=spec["event_id"],
            session_id="S-001",
            event_type=spec["event_type"],
            payload=spec["payload"],
            timestamp=spec["ts"],
            project_head=bundle["project_state"]["state"]["project_head"],
        )
        for index, spec in enumerate(candidate["proposed_events"], start=1)
    ]
    return apply_events_to_bundle(deepcopy(bundle), events)


def _object_by_id(project_state: dict, object_id: str) -> dict:
    return next(obj for obj in project_state["objects"] if obj["id"] == object_id)


def _links_by_id(project_state: dict) -> dict:
    return {link["id"]: link for link in project_state["links"]}


def _event_types(candidate: dict) -> list[str]:
    return [event["event_type"] for event in candidate["proposed_events"]]


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
