from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jsonschema import Draft202012Validator

from decide_me.domains import domain_pack_digest, load_builtin_packs
from decide_me.lifecycle import close_session, create_session
from decide_me.store import bootstrap_runtime, load_runtime, rebuild_and_persist, runtime_paths, transact, validate_runtime
from decide_me.validate import StateValidationError
from tests.helpers.impact_runtime import event_hash_snapshot, load_schema, run_cli, run_json_cli, runtime_state_snapshot
from tests.helpers.typed_metadata import evidence_metadata, risk_metadata


class SafetyApprovalFlowTests(unittest.TestCase):
    def test_approval_cli_records_artifact_and_satisfies_same_gate_digest(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = _build_runtime(Path(tmp))
            before = run_json_cli("show-safety-gate", "--ai-dir", str(ai_dir), "--object-id", "D-001")

            approved = run_json_cli(
                "approve-safety-gate",
                "--ai-dir",
                str(ai_dir),
                "--session-id",
                session_id,
                "--object-id",
                "D-001",
                "--approved-by",
                "user",
                "--reason",
                "Reviewed rollback and monitoring.",
            )
            after = run_json_cli("show-safety-gate", "--ai-dir", str(ai_dir), "--object-id", "D-001")
            event_before = event_hash_snapshot(ai_dir)
            runtime_before = runtime_state_snapshot(ai_dir)
            approvals = run_json_cli("show-safety-approvals", "--ai-dir", str(ai_dir), "--object-id", "D-001")

            self.assertEqual("needs_approval", before["gate_status"])
            self.assertEqual("approved", approved["status"])
            self.assertEqual("passed", after["gate_status"])
            self.assertTrue(after["approval_satisfied"])
            self.assertEqual(before["gate_digest"], after["gate_digest"])
            self.assertEqual(after["approval_artifact_ids"], [item["artifact_id"] for item in approvals["approvals"]])
            self.assertEqual(event_before, event_hash_snapshot(ai_dir))
            self.assertEqual(runtime_before, runtime_state_snapshot(ai_dir))
            self.assertEqual([], list(Draft202012Validator(load_schema("schemas/safety-approval.schema.json")).iter_errors(approvals)))
            self.assertEqual([], validate_runtime(ai_dir))

            bundle = load_runtime(runtime_paths(ai_dir))
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            self.assertTrue(any(obj_id.startswith("ART-approval-D-001-") for obj_id in objects))

    def test_domain_requirement_digest_change_requires_fresh_approval(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = _build_domain_runtime(Path(tmp))
            before = run_json_cli("show-safety-gate", "--ai-dir", str(ai_dir), "--object-id", "D-domain")
            self.assertIn("domain_required_evidence_missing", before["approval_reasons"])

            run_json_cli(
                "approve-safety-gate",
                "--ai-dir",
                str(ai_dir),
                "--session-id",
                session_id,
                "--object-id",
                "D-domain",
                "--approved-by",
                "reviewer",
                "--reason",
                "Reviewed missing protocol evidence.",
            )
            approved = run_json_cli("show-safety-gate", "--ai-dir", str(ai_dir), "--object-id", "D-domain")
            transact(ai_dir, lambda _bundle: _domain_evidence_events(session_id))
            rebuild_and_persist(ai_dir)

            changed = run_json_cli("show-safety-gate", "--ai-dir", str(ai_dir), "--object-id", "D-domain")

            self.assertEqual("passed", approved["gate_status"])
            self.assertNotEqual(approved["gate_digest"], changed["gate_digest"])
            self.assertEqual("needs_approval", changed["gate_status"])
            self.assertFalse(changed["approval_satisfied"])
            self.assertTrue(
                any(
                    item["required_evidence_id"] == "protocol_or_project_brief" and item["satisfied"]
                    for item in changed["domain_requirements"]
                )
            )
            self.assertEqual([], validate_runtime(ai_dir))

    def test_digest_change_after_new_risk_requires_fresh_approval(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = _build_runtime(Path(tmp))
            run_json_cli(
                "approve-safety-gate",
                "--ai-dir",
                str(ai_dir),
                "--session-id",
                session_id,
                "--object-id",
                "D-001",
                "--approved-by",
                "user",
                "--reason",
                "Reviewed.",
            )
            approved = run_json_cli("show-safety-gate", "--ai-dir", str(ai_dir), "--object-id", "D-001")
            transact(ai_dir, lambda _bundle: _new_risk_events(session_id))
            rebuild_and_persist(ai_dir)

            changed = run_json_cli("show-safety-gate", "--ai-dir", str(ai_dir), "--object-id", "D-001")

            self.assertEqual("passed", approved["gate_status"])
            self.assertNotEqual(approved["gate_digest"], changed["gate_digest"])
            self.assertEqual("needs_approval", changed["gate_status"])
            self.assertFalse(changed["approval_satisfied"])

    def test_approval_cli_rejects_unknown_and_closed_sessions_without_runtime_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, _session_id = _build_runtime(Path(tmp))
            before_events = event_hash_snapshot(ai_dir)
            before_runtime = runtime_state_snapshot(ai_dir)

            unknown = run_cli(
                "approve-safety-gate",
                "--ai-dir",
                str(ai_dir),
                "--session-id",
                "S-NOTEXIST",
                "--object-id",
                "D-001",
                "--approved-by",
                "user",
                "--reason",
                "Reviewed.",
                check=False,
            )

            self.assertNotEqual(0, unknown.returncode)
            self.assertIn("unknown session: S-NOTEXIST", unknown.stderr)
            self.assertEqual(before_events, event_hash_snapshot(ai_dir))
            self.assertEqual(before_runtime, runtime_state_snapshot(ai_dir))
            self.assertEqual([], validate_runtime(ai_dir))

            closed_session = create_session(str(ai_dir), context="Closed approval session")["session"]["id"]
            close_session(str(ai_dir), closed_session)
            before_closed_events = event_hash_snapshot(ai_dir)
            before_closed_runtime = runtime_state_snapshot(ai_dir)

            closed = run_cli(
                "approve-safety-gate",
                "--ai-dir",
                str(ai_dir),
                "--session-id",
                closed_session,
                "--object-id",
                "D-001",
                "--approved-by",
                "user",
                "--reason",
                "Reviewed.",
                check=False,
            )

            self.assertNotEqual(0, closed.returncode)
            self.assertIn(f"session {closed_session} is closed", closed.stderr)
            self.assertEqual(before_closed_events, event_hash_snapshot(ai_dir))
            self.assertEqual(before_closed_runtime, runtime_state_snapshot(ai_dir))
            self.assertEqual([], validate_runtime(ai_dir))

    def test_transact_rejects_unknown_session_incrementally_without_runtime_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, _session_id = _build_runtime(Path(tmp))
            before_events = event_hash_snapshot(ai_dir)
            before_runtime = runtime_state_snapshot(ai_dir)

            with self.assertRaisesRegex(StateValidationError, "event references unknown session: S-NOTEXIST"):
                transact(ai_dir, lambda _bundle: [_new_risk_events("S-NOTEXIST")[0]])

            self.assertEqual(before_events, event_hash_snapshot(ai_dir))
            self.assertEqual(before_runtime, runtime_state_snapshot(ai_dir))
            self.assertEqual([], validate_runtime(ai_dir))


def _build_runtime(tmp: Path) -> tuple[Path, str]:
    ai_dir = tmp / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Approve a safety gate.",
        current_milestone="Phase 7",
    )
    session_id = create_session(str(ai_dir), context="Approval flow")["session"]["id"]
    transact(ai_dir, lambda _bundle: _events(session_id))
    rebuild_and_persist(ai_dir)
    return ai_dir, session_id


def _build_domain_runtime(tmp: Path) -> tuple[Path, str]:
    ai_dir = tmp / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Approve a research safety gate.",
        current_milestone="Phase 9",
    )
    session_id = create_session(str(ai_dir), context="Primary endpoint research", domain_pack_id="research")["session"]["id"]
    transact(ai_dir, lambda _bundle: _domain_events(session_id))
    rebuild_and_persist(ai_dir)
    return ai_dir, session_id


def _events(session_id: str) -> list[dict]:
    return [
        {"event_id": "E-d", "session_id": session_id, "event_type": "object_recorded", "payload": {"object": _object("D-001", "decision", "unresolved", {"priority": "P0", "frontier": "now"})}},
        {"event_id": "E-e", "session_id": session_id, "event_type": "object_recorded", "payload": {"object": _object("E-001", "evidence", "active", evidence_metadata())}},
        {"event_id": "E-r", "session_id": session_id, "event_type": "object_recorded", "payload": {"object": _object("R-001", "risk", "open", risk_metadata(risk_tier="high", approval_threshold="human_review"))}},
        {"event_id": "E-le", "session_id": session_id, "event_type": "object_linked", "payload": {"link": _link("L-E-001-supports-D-001", "E-001", "supports", "D-001")}},
        {"event_id": "E-lr", "session_id": session_id, "event_type": "object_linked", "payload": {"link": _link("L-R-001-constrains-D-001", "R-001", "constrains", "D-001")}},
    ]


def _new_risk_events(session_id: str) -> list[dict]:
    return [
        {"event_id": "E-r2", "session_id": session_id, "event_type": "object_recorded", "payload": {"object": _object("R-002", "risk", "open", risk_metadata(risk_tier="high", approval_threshold="external_review"))}},
        {"event_id": "E-lr2", "session_id": session_id, "event_type": "object_linked", "payload": {"link": _link("L-R-002-constrains-D-001", "R-002", "constrains", "D-001")}},
    ]


def _domain_events(session_id: str) -> list[dict]:
    return [
        {
            "event_id": "E-domain-d",
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {
                "object": _object(
                    "D-domain",
                    "decision",
                    "unresolved",
                    {
                        "priority": "P0",
                        "frontier": "now",
                        "reversibility": "hard-to-reverse",
                        **_research_pack_identity(),
                        "domain_decision_type": "primary_endpoint",
                        "domain_criteria": [
                            "scientific_validity",
                            "clinical_or_business_relevance",
                            "data_availability",
                        ],
                    },
                )
            },
        }
    ]


def _domain_evidence_events(session_id: str) -> list[dict]:
    return [
        {
            "event_id": "E-domain-e",
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {
                "object": _object(
                    "E-domain-protocol",
                    "evidence",
                    "active",
                    {
                        **evidence_metadata(source_ref="docs/protocol.md"),
                        **_research_pack_identity(),
                        "evidence_requirement_id": "protocol_or_project_brief",
                    },
                )
            },
        },
        {
            "event_id": "E-domain-le",
            "session_id": session_id,
            "event_type": "object_linked",
            "payload": {"link": _link("L-E-domain-protocol-supports-D-domain", "E-domain-protocol", "supports", "D-domain")},
        },
    ]


def _object(object_id: str, object_type: str, status: str, metadata: dict) -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": object_id,
        "body": "Approval flow fixture.",
        "status": status,
        "created_at": "2026-04-28T00:00:00Z",
        "updated_at": None,
        "source_event_ids": ["E-fixture"],
        "metadata": metadata,
    }


def _link(link_id: str, source: str, relation: str, target: str) -> dict:
    return {
        "id": link_id,
        "source_object_id": source,
        "relation": relation,
        "target_object_id": target,
        "rationale": "Approval flow fixture link.",
        "created_at": "2026-04-28T00:00:00Z",
        "source_event_ids": ["E-link"],
    }


def _research_pack_identity() -> dict:
    pack = load_builtin_packs()["research"]
    return {
        "domain_pack_id": pack.pack_id,
        "domain_pack_version": pack.version,
        "domain_pack_digest": domain_pack_digest(pack),
    }


if __name__ == "__main__":
    unittest.main()
