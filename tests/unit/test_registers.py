from __future__ import annotations

import unittest
from copy import deepcopy

from decide_me.registers import build_assumption_register, build_evidence_register, build_risk_register
from tests.helpers.typed_metadata import assumption_metadata, evidence_metadata, risk_metadata


class RegisterProjectionTests(unittest.TestCase):
    def test_empty_registers_are_deterministic_projection_payloads(self) -> None:
        project_state = _project_state(objects=[], links=[])

        for register_type, builder in (
            ("evidence", build_evidence_register),
            ("assumption", build_assumption_register),
            ("risk", build_risk_register),
        ):
            with self.subTest(register_type=register_type):
                payload = builder(project_state)

                self.assertEqual(1, payload["schema_version"])
                self.assertEqual(register_type, payload["register_type"])
                self.assertEqual("H-test", payload["project_head"])
                self.assertEqual("2026-04-28T00:00:00Z", payload["generated_at"])
                self.assertEqual([], payload["items"])
                self.assertEqual(0, payload["summary"]["item_count"])
                self.assertEqual({}, payload["summary"]["by_status"])

    def test_evidence_register_aggregates_outgoing_evidence_links(self) -> None:
        project_state = _project_state(
            objects=[
                _object(
                    "E-002",
                    "evidence",
                    metadata=evidence_metadata(
                        source="docs",
                        source_ref="docs/auth.md",
                        summary="Docs support magic links.",
                        confidence="high",
                        freshness="current",
                    ),
                    source_event_ids=["E-create-2", "E-create-1"],
                ),
                _object(
                    "E-001",
                    "evidence",
                    metadata=evidence_metadata(
                        source="tests",
                        source_ref="tests/test_auth.py",
                        summary="Regression test covers the flow.",
                        confidence="medium",
                        freshness="stale",
                    ),
                ),
                _object("D-001", "decision"),
                _object("A-001", "action"),
                _object("R-001", "risk", metadata=risk_metadata()),
            ],
            links=[
                _link("L-E-002-verifies-A-001", "E-002", "verifies", "A-001"),
                _link("L-E-002-supports-D-001", "E-002", "supports", "D-001"),
                _link("L-E-002-challenges-R-001", "E-002", "challenges", "R-001"),
                _link("L-D-001-supports-E-002", "D-001", "supports", "E-002"),
            ],
        )

        payload = build_evidence_register(project_state)

        self.assertEqual(["E-001", "E-002"], [item["object_id"] for item in payload["items"]])
        self.assertEqual({"active": 2}, payload["summary"]["by_status"])
        self.assertEqual({"high": 1, "medium": 1}, payload["summary"]["by_confidence"])
        self.assertEqual({"current": 1, "stale": 1}, payload["summary"]["by_freshness"])

        item = payload["items"][1]
        self.assertEqual(["E-create-1", "E-create-2"], item["source_event_ids"])
        self.assertEqual("docs/auth.md", item["source_ref"])
        self.assertEqual(["D-001"], item["supports_object_ids"])
        self.assertEqual(["R-001"], item["challenges_object_ids"])
        self.assertEqual(["A-001"], item["verifies_object_ids"])
        self.assertEqual(
            [
                "L-E-002-challenges-R-001",
                "L-E-002-supports-D-001",
                "L-E-002-verifies-A-001",
            ],
            item["related_link_ids"],
        )

    def test_assumption_register_aggregates_contract_fields_and_outgoing_links(self) -> None:
        project_state = _project_state(
            objects=[
                _object(
                    "AS-002",
                    "assumption",
                    metadata=assumption_metadata(statement="A later assumption."),
                ),
                _object(
                    "AS-001",
                    "assumption",
                    metadata=assumption_metadata(
                        statement="The identity provider remains available.",
                        confidence="high",
                        validation="Check vendor status.",
                        invalidates_if_false=["D-002", "D-001"],
                        expires_at="2026-05-01T00:00:00Z",
                        owner="platform",
                    ),
                ),
                _object("D-001", "decision"),
                _object("D-002", "decision"),
                _object("A-001", "action"),
                _object("E-001", "evidence", metadata=evidence_metadata()),
            ],
            links=[
                _link("L-AS-001-requires-A-001", "AS-001", "requires", "A-001"),
                _link("L-AS-001-constrains-D-001", "AS-001", "constrains", "D-001"),
                _link("L-AS-001-derived-from-E-001", "AS-001", "derived_from", "E-001"),
                _link("L-AS-001-invalidates-D-002", "AS-001", "invalidates", "D-002"),
                _link("L-D-001-requires-AS-001", "D-001", "requires", "AS-001"),
                _link("L-D-002-derived-from-AS-001", "D-002", "derived_from", "AS-001"),
            ],
        )

        payload = build_assumption_register(project_state)

        self.assertEqual(["AS-001", "AS-002"], [item["object_id"] for item in payload["items"]])
        self.assertEqual({"high": 1, "medium": 1}, payload["summary"]["by_confidence"])

        item = payload["items"][0]
        self.assertEqual(["D-001", "D-002"], item["invalidates_if_false"])
        self.assertEqual(["D-001"], item["constrains_object_ids"])
        self.assertEqual(["A-001"], item["requires_object_ids"])
        self.assertEqual(["E-001"], item["derived_from_object_ids"])
        self.assertEqual(["D-002"], item["invalidates_object_ids"])
        self.assertEqual(["D-001"], item["required_by_object_ids"])
        self.assertEqual(["D-002"], item["derived_into_object_ids"])
        self.assertEqual(
            [
                "L-AS-001-constrains-D-001",
                "L-AS-001-derived-from-E-001",
                "L-AS-001-invalidates-D-002",
                "L-AS-001-requires-A-001",
                "L-D-001-requires-AS-001",
                "L-D-002-derived-from-AS-001",
            ],
            item["related_link_ids"],
        )

    def test_risk_register_exposes_gate_relevant_fields_and_mitigations(self) -> None:
        project_state = _project_state(
            objects=[
                _object(
                    "RISK-002",
                    "risk",
                    metadata=risk_metadata(risk_tier="low", approval_threshold="none"),
                ),
                _object(
                    "RISK-001",
                    "risk",
                    metadata=risk_metadata(
                        statement="Auth rollout can block release.",
                        severity="high",
                        likelihood="medium",
                        risk_tier="high",
                        reversibility="partially_reversible",
                        mitigation_object_ids=["ACT-002", "ACT-001"],
                        approval_threshold="human_review",
                    ),
                ),
                _object("ACT-001", "action"),
                _object("DEC-001", "decision"),
            ],
            links=[
                _link("L-DEC-001-mitigates-RISK-001", "DEC-001", "mitigates", "RISK-001"),
                _link("L-ACT-001-mitigates-RISK-001", "ACT-001", "mitigates", "RISK-001"),
                _link("L-RISK-001-challenges-DEC-001", "RISK-001", "challenges", "DEC-001"),
            ],
        )

        payload = build_risk_register(project_state)

        self.assertEqual(["RISK-001", "RISK-002"], [item["object_id"] for item in payload["items"]])
        self.assertEqual({"high": 1, "low": 1}, payload["summary"]["by_risk_tier"])
        self.assertEqual({"human_review": 1, "none": 1}, payload["summary"]["by_approval_threshold"])
        self.assertEqual({"partially_reversible": 2}, payload["summary"]["by_reversibility"])

        item = payload["items"][0]
        self.assertEqual("human_review", item["approval_threshold"])
        self.assertEqual(["ACT-001", "ACT-002"], item["mitigation_object_ids"])
        self.assertEqual(["ACT-001", "DEC-001"], item["mitigated_by_object_ids"])
        self.assertEqual(
            ["L-ACT-001-mitigates-RISK-001", "L-DEC-001-mitigates-RISK-001"],
            item["mitigation_link_ids"],
        )
        self.assertEqual(item["mitigation_link_ids"], item["related_link_ids"])


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
    metadata: dict | None = None,
    source_event_ids: list[str] | None = None,
) -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": object_id,
        "body": None,
        "status": "active",
        "created_at": "2026-04-28T00:00:00Z",
        "updated_at": None,
        "source_event_ids": ["E-create"] if source_event_ids is None else source_event_ids,
        "metadata": {} if metadata is None else deepcopy(metadata),
    }


def _link(link_id: str, source: str, relation: str, target: str) -> dict:
    return {
        "id": link_id,
        "source_object_id": source,
        "relation": relation,
        "target_object_id": target,
        "rationale": "Register projection fixture link.",
        "created_at": "2026-04-28T00:00:00Z",
        "source_event_ids": ["E-link"],
    }


if __name__ == "__main__":
    unittest.main()
