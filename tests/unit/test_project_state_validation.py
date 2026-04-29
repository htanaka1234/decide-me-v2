from __future__ import annotations

import unittest
from copy import deepcopy

from decide_me.events import build_event as runtime_build_event
from decide_me.projections import build_decision_stack_graph, default_project_state, rebuild_projections
from decide_me.validate import StateValidationError, validate_project_state, validate_projection_bundle
from tests.helpers.typed_metadata import (
    assumption_metadata,
    evidence_metadata,
    revisit_trigger_metadata,
    risk_metadata,
    verification_metadata,
)


class ProjectStateValidationTests(unittest.TestCase):
    def test_default_state_validates_as_uninitialized_skeleton(self) -> None:
        validate_project_state(default_project_state())

    def test_empty_rebuild_project_state_validates_as_skeleton(self) -> None:
        bundle = rebuild_projections([])

        validate_project_state(bundle["project_state"])

    def test_accepts_object_link_project_state(self) -> None:
        validate_project_state(_valid_project_state())

    def test_rejects_top_level_decisions(self) -> None:
        payload = _valid_project_state()
        payload["decisions"] = []

        with self.assertRaisesRegex(StateValidationError, "top-level decisions"):
            validate_project_state(payload)

    def test_rejects_duplicate_object_ids(self) -> None:
        payload = _valid_project_state()
        payload["objects"].append(deepcopy(payload["objects"][0]))
        payload["counts"]["object_total"] += 1
        payload["counts"]["by_type"]["decision"] = 2
        payload["counts"]["by_status"]["unresolved"] = 2

        with self.assertRaisesRegex(StateValidationError, "duplicate object id"):
            validate_project_state(payload)

    def test_rejects_missing_link_source_endpoint(self) -> None:
        payload = _valid_project_state()
        payload["links"][0]["source_object_id"] = "D-missing"

        with self.assertRaisesRegex(StateValidationError, "source_object_id"):
            validate_project_state(payload)

    def test_rejects_missing_link_target_endpoint(self) -> None:
        payload = _valid_project_state()
        payload["links"][0]["target_object_id"] = "D-missing"

        with self.assertRaisesRegex(StateValidationError, "target_object_id"):
            validate_project_state(payload)

    def test_rejects_invalid_relation(self) -> None:
        payload = _valid_project_state()
        payload["links"][0]["relation"] = "duplicates"

        with self.assertRaisesRegex(StateValidationError, "relation"):
            validate_project_state(payload)

    def test_rejects_unknown_decision_stack_layer(self) -> None:
        payload = _valid_project_state()
        payload["objects"][0]["metadata"]["layer"] = "unknown"

        with self.assertRaisesRegex(StateValidationError, "metadata.layer"):
            validate_project_state(payload)

    def test_rejects_invalid_decision_metadata_enums(self) -> None:
        for key, value in (
            ("priority", "BAD"),
            ("frontier", "someday"),
            ("kind", "unknown"),
            ("domain", "NOT_A_DOMAIN"),
            ("resolvable_by", "committee"),
            ("reversibility", "not-reversible"),
        ):
            with self.subTest(key=key):
                payload = _valid_project_state()
                payload["objects"][0]["metadata"][key] = value

                with self.assertRaisesRegex(StateValidationError, f"metadata.{key}"):
                    validate_project_state(payload)

    def test_rejects_invalidated_by_on_non_invalidated_decision(self) -> None:
        payload = _valid_project_state()
        payload["objects"][0]["metadata"]["invalidated_by"] = {
            "decision_id": "D-other",
            "invalidated_at": "2026-04-23T12:30:00Z",
        }

        with self.assertRaisesRegex(StateValidationError, "non-invalidated decision object D-001"):
            validate_project_state(payload)

    def test_rejects_invalidated_decision_without_invalidated_by_metadata(self) -> None:
        payload = _valid_project_state()
        payload["objects"][0]["status"] = "invalidated"
        payload["counts"]["by_status"] = {"invalidated": 1, "active": 2}

        with self.assertRaisesRegex(StateValidationError, "metadata.invalidated_by"):
            validate_project_state(payload)

    def test_rejects_invalidated_decision_with_invalid_invalidated_at(self) -> None:
        payload = _valid_project_state()
        payload["objects"][0]["status"] = "invalidated"
        payload["objects"][0]["metadata"]["invalidated_by"] = {
            "decision_id": "D-other",
            "invalidated_at": "not-a-timestamp",
        }
        payload["counts"]["by_status"] = {"invalidated": 1, "active": 2}

        with self.assertRaisesRegex(StateValidationError, "invalidated_at"):
            validate_project_state(payload)

    def test_accepts_typed_metadata_objects(self) -> None:
        for object_type, metadata in _typed_metadata_cases():
            with self.subTest(object_type=object_type):
                payload = _valid_project_state()
                _append_object(payload, _typed_object(f"O-{object_type}", object_type, metadata))

                validate_project_state(payload)

    def test_accepts_safety_approval_artifact_metadata(self) -> None:
        payload = _valid_project_state()
        _append_object(payload, _typed_object("ART-approval-D-001", "artifact", _safety_approval_metadata()))

        validate_project_state(payload)

    def test_rejects_missing_typed_metadata_keys(self) -> None:
        for object_type, metadata, missing_key in (
            ("evidence", evidence_metadata(), "source_ref"),
            ("assumption", assumption_metadata(), "statement"),
            ("risk", risk_metadata(), "approval_threshold"),
            ("verification", verification_metadata(), "expected_result"),
            ("revisit_trigger", revisit_trigger_metadata(target_object_ids=["D-001"]), "target_object_ids"),
        ):
            with self.subTest(object_type=object_type, missing_key=missing_key):
                payload = _valid_project_state()
                metadata.pop(missing_key)
                _append_object(payload, _typed_object(f"O-{object_type}", object_type, metadata))

                with self.assertRaisesRegex(StateValidationError, "missing required keys"):
                    validate_project_state(payload)

    def test_rejects_invalid_typed_metadata_values(self) -> None:
        cases = (
            ("evidence", evidence_metadata(confidence="certain"), "metadata.confidence"),
            ("evidence", evidence_metadata(observed_at="not-a-timestamp"), "metadata.observed_at"),
            ("assumption", assumption_metadata(invalidates_if_false=[None]), "invalidates_if_false"),
            ("assumption", assumption_metadata(expires_at="not-a-timestamp"), "metadata.expires_at"),
            ("risk", risk_metadata(risk_tier="severe"), "metadata.risk_tier"),
            ("risk", risk_metadata(mitigation_object_ids=["A-001", "A-001"]), "duplicate values"),
            ("verification", verification_metadata(result="unknown"), "metadata.result"),
            ("verification", verification_metadata(verified_at="not-a-timestamp"), "metadata.verified_at"),
            ("revisit_trigger", revisit_trigger_metadata(trigger_type="manual"), "metadata.trigger_type"),
            ("revisit_trigger", revisit_trigger_metadata(target_object_ids=[]), "target_object_ids"),
            ("artifact", _safety_approval_metadata(gate_digest="bad"), "metadata.gate_digest"),
        )
        for object_type, metadata, pattern in cases:
            with self.subTest(object_type=object_type, pattern=pattern):
                payload = _valid_project_state()
                _append_object(payload, _typed_object(f"O-{object_type}", object_type, metadata))

                with self.assertRaisesRegex(StateValidationError, pattern):
                    validate_project_state(payload)

    def test_rejects_graph_node_referencing_missing_object(self) -> None:
        payload = _valid_project_state()
        payload["graph"]["nodes"][0]["object_id"] = "D-missing"

        with self.assertRaisesRegex(StateValidationError, "graph node D-missing references missing object"):
            validate_project_state(payload)

    def test_rejects_graph_node_that_does_not_match_object_projection(self) -> None:
        payload = _valid_project_state()
        payload["graph"]["nodes"][0]["layer"] = "purpose"

        with self.assertRaisesRegex(StateValidationError, "graph node D-001 does not match object projection"):
            validate_project_state(payload)

    def test_rejects_graph_edge_referencing_missing_link(self) -> None:
        payload = _valid_project_state()
        payload["graph"]["edges"][0]["link_id"] = "L-missing"

        with self.assertRaisesRegex(StateValidationError, "graph edge L-missing references missing link"):
            validate_project_state(payload)

    def test_rejects_graph_edge_endpoint_referencing_missing_object(self) -> None:
        payload = _valid_project_state()
        payload["graph"]["edges"][0]["source_object_id"] = "O-missing"

        with self.assertRaisesRegex(StateValidationError, "source_object_id references missing object"):
            validate_project_state(payload)

    def test_rejects_graph_edge_unknown_relation(self) -> None:
        payload = _valid_project_state()
        payload["graph"]["edges"][0]["relation"] = "duplicates"

        with self.assertRaisesRegex(StateValidationError, "project_state.graph.edges\\[\\].relation"):
            validate_project_state(payload)

    def test_rejects_stale_counts(self) -> None:
        payload = _valid_project_state()
        payload["counts"]["link_total"] = 0

        with self.assertRaisesRegex(StateValidationError, "counts"):
            validate_project_state(payload)

    def test_rejects_null_project_fields_after_events(self) -> None:
        payload = _valid_project_state()
        payload["project"]["name"] = None

        with self.assertRaisesRegex(StateValidationError, "project_state.project.name"):
            validate_project_state(payload)

    def test_projection_bundle_rejects_stale_sessions_index(self) -> None:
        bundle = rebuild_projections(
            [
                _event(
                    sequence=1,
                    session_id="SYSTEM",
                    event_type="project_initialized",
                    payload={
                        "project": {
                            "name": "Demo",
                            "objective": "Plan Phase 5-2.",
                            "current_milestone": "Phase 5-2",
                            "stop_rule": "Resolve blockers.",
                        }
                    },
                    timestamp="2026-04-23T12:00:00Z",
                ),
                _event(
                    sequence=2,
                    session_id="S-001",
                    event_type="session_created",
                    payload={
                        "session": {
                            "id": "S-001",
                            "started_at": "2026-04-23T12:01:00Z",
                            "last_seen_at": "2026-04-23T12:01:00Z",
                            "bound_context_hint": "demo",
                        }
                    },
                    timestamp="2026-04-23T12:01:00Z",
                ),
            ]
        )
        validate_projection_bundle(bundle)
        bundle["project_state"]["sessions_index"]["S-001"]["last_seen_at"] = "2026-04-23T12:30:00Z"

        with self.assertRaisesRegex(StateValidationError, "sessions_index does not match sessions"):
            validate_projection_bundle(bundle)


def _valid_project_state() -> dict:
    payload = {
        "schema_version": 12,
        "project": {
            "name": "Demo",
            "objective": "Plan Phase 5-2.",
            "current_milestone": "Phase 5-2",
            "stop_rule": "Resolve blockers.",
        },
        "state": {
            "project_head": "H-001",
            "event_count": 1,
            "updated_at": "2026-04-23T12:00:00Z",
            "last_event_id": "E-001",
        },
        "protocol": {
            "plain_ok_scope": "same-session-active-proposal-only",
            "proposal_expiry_rules": ["project-head-changed", "session-boundary"],
            "close_policy": "generate-close-summary-on-close",
        },
        "sessions_index": {},
        "counts": {
            "object_total": 3,
            "link_total": 2,
            "by_type": {"decision": 1, "proposal": 1, "option": 1},
            "by_status": {"unresolved": 1, "active": 2},
            "by_relation": {"addresses": 1, "recommends": 1},
        },
        "objects": [
            {
                "id": "D-001",
                "type": "decision",
                "title": "Auth mode",
                "body": None,
                "status": "unresolved",
                "created_at": "2026-04-23T12:00:00Z",
                "updated_at": None,
                "source_event_ids": ["E-001"],
                "metadata": {
                    "requirement_id": "R-001",
                    "kind": "choice",
                    "domain": "technical",
                    "priority": "P0",
                    "frontier": "now",
                    "resolvable_by": "human",
                    "reversibility": "reversible",
                },
            },
            {
                "id": "O-option-001",
                "type": "option",
                "title": "Use magic links.",
                "body": None,
                "status": "active",
                "created_at": "2026-04-23T12:00:00Z",
                "updated_at": None,
                "source_event_ids": ["E-001"],
                "metadata": {},
            },
            {
                "id": "P-001",
                "type": "proposal",
                "title": "Use magic links.",
                "body": "Smallest auth surface.",
                "status": "active",
                "created_at": "2026-04-23T12:00:00Z",
                "updated_at": None,
                "source_event_ids": ["E-001"],
                "metadata": {},
            },
        ],
        "links": [
            {
                "id": "L-P-001-addresses-D-001",
                "source_object_id": "P-001",
                "relation": "addresses",
                "target_object_id": "D-001",
                "rationale": "Use magic links?",
                "created_at": "2026-04-23T12:00:00Z",
                "source_event_ids": ["E-001"],
            },
            {
                "id": "L-P-001-recommends-O-option-001",
                "source_object_id": "P-001",
                "relation": "recommends",
                "target_object_id": "O-option-001",
                "rationale": "Smallest auth surface.",
                "created_at": "2026-04-23T12:00:00Z",
                "source_event_ids": ["E-001"],
            },
        ],
        "graph": {},
    }
    payload["graph"] = build_decision_stack_graph(payload)
    return deepcopy(payload)


def _event(
    *,
    sequence: int,
    session_id: str,
    event_type: str,
    payload: dict,
    timestamp: str,
) -> dict:
    return runtime_build_event(
        tx_id=f"T-test-{sequence}",
        tx_index=1,
        tx_size=1,
        event_id=f"E-test-{sequence}",
        session_id=session_id,
        event_type=event_type,
        payload=payload,
        timestamp=timestamp,
        project_head=f"H-{sequence}",
    )


def _typed_metadata_cases() -> list[tuple[str, dict]]:
    return [
        ("evidence", evidence_metadata()),
        ("assumption", assumption_metadata()),
        ("risk", risk_metadata()),
        ("verification", verification_metadata()),
        ("revisit_trigger", revisit_trigger_metadata(target_object_ids=["D-001"])),
    ]


def _safety_approval_metadata(**overrides: str | None) -> dict:
    metadata = {
        "artifact_type": "safety_gate_approval",
        "target_object_id": "D-001",
        "gate_digest": "SG-123456789abc",
        "approval_threshold": "human_review",
        "approved_by": "user",
        "approved_at": "2026-04-28T00:00:00Z",
        "reason": "Reviewed.",
        "expires_at": None,
    }
    metadata.update(overrides)
    return metadata


def _typed_object(object_id: str, object_type: str, metadata: dict) -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": object_type.replace("_", " ").title(),
        "body": "Typed metadata validation fixture.",
        "status": "active",
        "created_at": "2026-04-23T12:00:00Z",
        "updated_at": None,
        "source_event_ids": ["E-typed"],
        "metadata": metadata,
    }


def _append_object(payload: dict, obj: dict) -> None:
    payload["objects"].append(obj)
    _refresh_counts_and_graph(payload)


def _refresh_counts_and_graph(payload: dict) -> None:
    payload["counts"] = {
        "object_total": len(payload["objects"]),
        "link_total": len(payload["links"]),
        "by_type": {},
        "by_status": {},
        "by_relation": {},
    }
    for obj in payload["objects"]:
        payload["counts"]["by_type"][obj["type"]] = payload["counts"]["by_type"].get(obj["type"], 0) + 1
        payload["counts"]["by_status"][obj["status"]] = payload["counts"]["by_status"].get(obj["status"], 0) + 1
    for link in payload["links"]:
        relation = link["relation"]
        payload["counts"]["by_relation"][relation] = payload["counts"]["by_relation"].get(relation, 0) + 1
    payload["graph"] = build_decision_stack_graph(payload)


if __name__ == "__main__":
    unittest.main()
