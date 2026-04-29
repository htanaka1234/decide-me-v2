from __future__ import annotations

import unittest
from copy import deepcopy

from decide_me.safety_approval import approval_artifact_id, approval_link_id, build_safety_approval_event_specs
from decide_me.safety_gate import evaluate_safety_gate
from tests.helpers.typed_metadata import evidence_metadata, risk_metadata


class SafetyApprovalTests(unittest.TestCase):
    def test_matching_approval_artifact_satisfies_gate(self) -> None:
        project_state = _approval_required_state()
        before = evaluate_safety_gate(project_state, "D-001")

        project_state = _with_approval(project_state, before["gate_digest"])
        after = evaluate_safety_gate(project_state, "D-001")

        self.assertEqual("needs_approval", before["gate_status"])
        self.assertEqual("passed", after["gate_status"])
        self.assertTrue(after["approval_required"])
        self.assertTrue(after["approval_satisfied"])
        self.assertEqual(["ART-approval-D-001"], after["approval_artifact_ids"])

    def test_digest_change_invalidates_previous_approval(self) -> None:
        project_state = _approval_required_state()
        before = evaluate_safety_gate(project_state, "D-001")
        project_state = _with_approval(project_state, before["gate_digest"])
        project_state["objects"].append(
            _object(
                "R-002",
                "risk",
                metadata=risk_metadata(
                    statement="External review is required.",
                    risk_tier="high",
                    approval_threshold="external_review",
                ),
            )
        )
        project_state["links"].append(_link("L-R-002-constrains-D-001", "R-002", "constrains", "D-001"))

        after = evaluate_safety_gate(project_state, "D-001")

        self.assertNotEqual(before["gate_digest"], after["gate_digest"])
        self.assertEqual("needs_approval", after["gate_status"])
        self.assertFalse(after["approval_satisfied"])

    def test_blocked_gate_cannot_build_approval_events(self) -> None:
        project_state = _project_state(
            objects=[
                _object("D-001", "decision"),
                _object("E-001", "evidence", metadata=evidence_metadata()),
                _object("E-002", "evidence", metadata=evidence_metadata(source_ref="docs/challenge.md")),
            ],
            links=[
                _link("L-E-001-supports-D-001", "E-001", "supports", "D-001"),
                _link("L-E-002-challenges-D-001", "E-002", "challenges", "D-001"),
            ],
        )

        with self.assertRaisesRegex(ValueError, "blocked"):
            build_safety_approval_event_specs(
                project_state,
                "S-001",
                "D-001",
                approved_by="user",
                reason="Reviewed.",
                approved_at="2026-04-28T00:00:00Z",
            )

    def test_explicit_acceptance_approval_event_specs_are_deterministic(self) -> None:
        project_state = _project_state(
            objects=[
                _object("D-001", "decision"),
                _object("E-001", "evidence", metadata=evidence_metadata()),
                _object(
                    "R-001",
                    "risk",
                    metadata=risk_metadata(risk_tier="low", approval_threshold="explicit_acceptance"),
                ),
            ],
            links=[
                _link("L-E-001-supports-D-001", "E-001", "supports", "D-001"),
                _link("L-R-001-constrains-D-001", "R-001", "constrains", "D-001"),
            ],
        )

        specs = build_safety_approval_event_specs(
            project_state,
            "S-001",
            "D-001",
            approved_by="explicit_acceptance",
            reason="Explicit acceptance.",
            approved_at="2026-04-28T00:00:00Z",
        )

        self.assertEqual(["object_recorded", "object_linked"], [spec["event_type"] for spec in specs])
        artifact = specs[0]["payload"]["object"]
        link = specs[1]["payload"]["link"]
        self.assertTrue(artifact["id"].startswith("ART-approval-D-001-"))
        self.assertEqual("safety_gate_approval", artifact["metadata"]["artifact_type"])
        self.assertEqual("explicit_acceptance", artifact["metadata"]["approval_level"])
        self.assertEqual(artifact["id"], link["source_object_id"])
        self.assertEqual("D-001", link["target_object_id"])

    def test_low_approval_level_cannot_satisfy_higher_threshold(self) -> None:
        project_state = _approval_required_state()

        with self.assertRaisesRegex(ValueError, "approval level explicit_acceptance does not satisfy human_review"):
            build_safety_approval_event_specs(
                project_state,
                "S-001",
                "D-001",
                approved_by="explicit_acceptance",
                approval_level="explicit_acceptance",
                reason="Explicit acceptance is not enough.",
                approved_at="2026-04-28T00:00:00Z",
            )

    def test_low_approval_level_artifact_does_not_satisfy_gate(self) -> None:
        project_state = _approval_required_state()
        before = evaluate_safety_gate(project_state, "D-001")
        project_state = _with_approval(project_state, before["gate_digest"], approval_level="explicit_acceptance")

        after = evaluate_safety_gate(project_state, "D-001")

        self.assertEqual("needs_approval", after["gate_status"])
        self.assertFalse(after["approval_satisfied"])
        self.assertEqual([], after["approval_artifact_ids"])

    def test_expired_approval_artifact_is_refreshed_for_same_digest(self) -> None:
        project_state = _approval_required_state()
        gate = evaluate_safety_gate(project_state, "D-001")
        artifact_id = approval_artifact_id("D-001", gate["gate_digest"])
        link_id = approval_link_id(artifact_id, "D-001")
        project_state["objects"].append(
            _object(
                artifact_id,
                "artifact",
                metadata=_approval_metadata(gate["gate_digest"], expires_at="2026-04-27T00:00:00Z"),
            )
        )
        project_state["links"].append(_link(link_id, artifact_id, "addresses", "D-001"))

        specs = build_safety_approval_event_specs(
            project_state,
            "S-001",
            "D-001",
            gate_result=gate,
            approved_by="user",
            reason="Reviewed again.",
            approved_at="2026-04-28T00:00:00Z",
            expires_at="2026-05-01T00:00:00Z",
        )

        self.assertEqual(["object_updated"], [spec["event_type"] for spec in specs])
        self.assertEqual(artifact_id, specs[0]["payload"]["object_id"])
        self.assertEqual("2026-05-01T00:00:00Z", specs[0]["payload"]["patch"]["metadata"]["expires_at"])

    def test_inactive_approval_artifact_is_reactivated_for_same_digest(self) -> None:
        project_state = _approval_required_state()
        gate = evaluate_safety_gate(project_state, "D-001")
        artifact_id = approval_artifact_id("D-001", gate["gate_digest"])
        link_id = approval_link_id(artifact_id, "D-001")
        project_state["objects"].append(
            _object(
                artifact_id,
                "artifact",
                status="invalidated",
                metadata=_approval_metadata(gate["gate_digest"]),
            )
        )
        project_state["links"].append(_link(link_id, artifact_id, "addresses", "D-001"))

        specs = build_safety_approval_event_specs(
            project_state,
            "S-001",
            "D-001",
            gate_result=gate,
            approved_by="user",
            reason="Reviewed again.",
            approved_at="2026-04-28T00:00:00Z",
        )

        self.assertEqual(["object_updated", "object_status_changed"], [spec["event_type"] for spec in specs])
        self.assertEqual("invalidated", specs[1]["payload"]["from_status"])
        self.assertEqual("active", specs[1]["payload"]["to_status"])

    def test_past_expiry_is_rejected_before_approval_events(self) -> None:
        project_state = _approval_required_state()

        with self.assertRaisesRegex(ValueError, "expires_at must be after approved_at"):
            build_safety_approval_event_specs(
                project_state,
                "S-001",
                "D-001",
                approved_by="user",
                reason="Reviewed.",
                approved_at="2026-04-28T00:00:00Z",
                expires_at="2026-04-27T00:00:00Z",
            )


def _approval_required_state() -> dict:
    return _project_state(
        objects=[
            _object("D-001", "decision"),
            _object("E-001", "evidence", metadata=evidence_metadata()),
            _object(
                "R-001",
                "risk",
                metadata=risk_metadata(risk_tier="high", approval_threshold="human_review"),
            ),
        ],
        links=[
            _link("L-E-001-supports-D-001", "E-001", "supports", "D-001"),
            _link("L-R-001-constrains-D-001", "R-001", "constrains", "D-001"),
        ],
    )


def _with_approval(project_state: dict, gate_digest: str, *, approval_level: str = "human_review") -> dict:
    copied = deepcopy(project_state)
    copied["objects"].append(
        _object(
            "ART-approval-D-001",
            "artifact",
            metadata={
                "artifact_type": "safety_gate_approval",
                "target_object_id": "D-001",
                "gate_digest": gate_digest,
                "approval_threshold": "human_review",
                "approval_level": approval_level,
                "approved_by": "user",
                "approved_at": "2026-04-28T00:00:00Z",
                "reason": "Reviewed risk.",
                "expires_at": None,
            },
        )
    )
    copied["links"].append(_link("L-ART-approval-D-001-addresses-D-001", "ART-approval-D-001", "addresses", "D-001"))
    return copied


def _approval_metadata(gate_digest: str, *, expires_at: str | None = None) -> dict:
    return {
        "artifact_type": "safety_gate_approval",
        "target_object_id": "D-001",
        "gate_digest": gate_digest,
        "approval_threshold": "human_review",
        "approval_level": "human_review",
        "approved_by": "user",
        "approved_at": "2026-04-28T00:00:00Z",
        "reason": "Reviewed risk.",
        "expires_at": expires_at,
    }


def _project_state(*, objects: list[dict], links: list[dict]) -> dict:
    return {
        "schema_version": 12,
        "state": {
            "project_head": "H-test",
            "event_count": len(objects) + len(links),
            "updated_at": "2026-04-28T00:00:00Z",
            "last_event_id": "E-last",
        },
        "objects": deepcopy(objects),
        "links": deepcopy(links),
    }


def _object(
    object_id: str,
    object_type: str,
    *,
    status: str = "active",
    metadata: dict | None = None,
) -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": object_id,
        "body": None,
        "status": status,
        "created_at": "2026-04-28T00:00:00Z",
        "updated_at": None,
        "source_event_ids": ["E-create"],
        "metadata": {} if metadata is None else deepcopy(metadata),
    }


def _link(link_id: str, source: str, relation: str, target: str) -> dict:
    return {
        "id": link_id,
        "source_object_id": source,
        "relation": relation,
        "target_object_id": target,
        "rationale": "Safety approval fixture link.",
        "created_at": "2026-04-28T00:00:00Z",
        "source_event_ids": ["E-link"],
    }


if __name__ == "__main__":
    unittest.main()
