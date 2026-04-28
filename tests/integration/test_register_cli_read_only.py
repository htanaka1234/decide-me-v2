from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jsonschema import Draft202012Validator

from decide_me.lifecycle import create_session
from decide_me.store import bootstrap_runtime, rebuild_and_persist, transact
from tests.helpers.impact_runtime import event_hash_snapshot, load_schema, run_json_cli, runtime_state_snapshot
from tests.helpers.typed_metadata import assumption_metadata, evidence_metadata, risk_metadata


class RegisterCliReadOnlyTests(unittest.TestCase):
    def test_register_cli_commands_return_json_without_runtime_state_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _build_register_runtime(Path(tmp))
            validator = Draft202012Validator(load_schema("schemas/registers.schema.json"))
            commands = [
                ("evidence", ("show-evidence-register", "--ai-dir", str(ai_dir))),
                ("assumption", ("show-assumption-register", "--ai-dir", str(ai_dir))),
                ("risk", ("show-risk-register", "--ai-dir", str(ai_dir))),
            ]

            for register_type, args in commands:
                with self.subTest(register_type=register_type):
                    event_before = event_hash_snapshot(ai_dir)
                    runtime_before = runtime_state_snapshot(ai_dir)

                    payload = run_json_cli(*args)

                    self.assertEqual(event_before, event_hash_snapshot(ai_dir))
                    self.assertEqual(runtime_before, runtime_state_snapshot(ai_dir))
                    self.assertEqual([], list(validator.iter_errors(payload)))
                    self.assertEqual(register_type, payload["register_type"])
                    self.assertIsInstance(payload["project_head"], str)
                    self.assertTrue(payload["project_head"])
                    self.assertEqual(1, payload["summary"]["item_count"])

            evidence = run_json_cli("show-evidence-register", "--ai-dir", str(ai_dir))
            self.assertEqual(["DEC-001"], evidence["items"][0]["supports_object_ids"])
            self.assertEqual("docs/registers.md", evidence["items"][0]["source_ref"])

            assumptions = run_json_cli("show-assumption-register", "--ai-dir", str(ai_dir))
            self.assertEqual(["DEC-001"], assumptions["items"][0]["constrains_object_ids"])
            self.assertEqual(["DEC-001"], assumptions["items"][0]["invalidates_if_false"])

            risks = run_json_cli("show-risk-register", "--ai-dir", str(ai_dir))
            self.assertEqual("human_review", risks["items"][0]["approval_threshold"])
            self.assertEqual(["ACT-001"], risks["items"][0]["mitigated_by_object_ids"])


def _build_register_runtime(tmp: Path) -> Path:
    ai_dir = tmp / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Build register projections.",
        current_milestone="Phase 7 readiness",
    )
    session = create_session(str(ai_dir), context="Register projection gate")
    session_id = session["session"]["id"]
    transact(ai_dir, lambda _bundle: _events(session_id))
    rebuild_and_persist(ai_dir)
    return ai_dir


def _events(session_id: str) -> list[dict]:
    object_specs = [
        (
            "E-register-evidence",
            "EV-001",
            "evidence",
            "active",
            evidence_metadata(source_ref="docs/registers.md", summary="Register docs define the contract."),
        ),
        (
            "E-register-assumption",
            "AS-001",
            "assumption",
            "active",
            assumption_metadata(
                statement="The register remains derived.",
                confidence="high",
                invalidates_if_false=["DEC-001"],
                owner="maintainer",
            ),
        ),
        (
            "E-register-risk",
            "RISK-001",
            "risk",
            "open",
            risk_metadata(
                statement="Register output may drift from safety gate needs.",
                risk_tier="high",
                mitigation_object_ids=["ACT-001"],
                approval_threshold="human_review",
            ),
        ),
        ("E-register-decision", "DEC-001", "decision", "unresolved", {"priority": "P0", "frontier": "now"}),
        ("E-register-action", "ACT-001", "action", "active", {}),
    ]
    link_specs = [
        ("E-link-evidence-decision", "L-EV-001-supports-DEC-001", "EV-001", "supports", "DEC-001"),
        ("E-link-assumption-decision", "L-AS-001-constrains-DEC-001", "AS-001", "constrains", "DEC-001"),
        ("E-link-action-risk", "L-ACT-001-mitigates-RISK-001", "ACT-001", "mitigates", "RISK-001"),
    ]
    return [
        {
            "event_id": event_id,
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {"object": _object(object_id, object_type, status, event_id, metadata)},
        }
        for event_id, object_id, object_type, status, metadata in object_specs
    ] + [
        {
            "event_id": event_id,
            "session_id": session_id,
            "event_type": "object_linked",
            "payload": {"link": _link(link_id, source, relation, target, event_id)},
        }
        for event_id, link_id, source, relation, target in link_specs
    ]


def _object(object_id: str, object_type: str, status: str, event_id: str, metadata: dict) -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": object_id,
        "body": "Register CLI read-only fixture object.",
        "status": status,
        "created_at": "2026-04-28T00:00:00Z",
        "updated_at": None,
        "source_event_ids": [event_id],
        "metadata": metadata,
    }


def _link(link_id: str, source: str, relation: str, target: str, event_id: str) -> dict:
    return {
        "id": link_id,
        "source_object_id": source,
        "relation": relation,
        "target_object_id": target,
        "rationale": "Register CLI read-only fixture link.",
        "created_at": "2026-04-28T00:00:00Z",
        "source_event_ids": [event_id],
    }


if __name__ == "__main__":
    unittest.main()
