from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jsonschema import Draft202012Validator

from decide_me.lifecycle import create_session
from decide_me.store import bootstrap_runtime, rebuild_and_persist, transact
from tests.helpers.impact_runtime import event_hash_snapshot, load_schema, run_json_cli, runtime_state_snapshot
from tests.helpers.typed_metadata import (
    assumption_metadata,
    evidence_metadata,
    revisit_trigger_metadata,
    verification_metadata,
)


NOW = "2026-04-28T12:00:00Z"
PAST = "2026-04-27T12:00:00Z"
FUTURE = "2026-04-29T12:00:00Z"


class StaleDetectionCliReadOnlyTests(unittest.TestCase):
    def test_stale_detection_cli_commands_return_json_without_runtime_state_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _build_stale_detection_runtime(Path(tmp))
            validator = Draft202012Validator(load_schema("schemas/stale-diagnostics.schema.json"))
            commands = [
                ("stale_assumptions", ("show-stale-assumptions", "--ai-dir", str(ai_dir), "--now", NOW)),
                ("stale_evidence", ("show-stale-evidence", "--ai-dir", str(ai_dir), "--now", NOW)),
                ("verification_gaps", ("show-verification-gaps", "--ai-dir", str(ai_dir), "--now", NOW)),
                ("revisit_due", ("show-revisit-due", "--ai-dir", str(ai_dir), "--now", NOW)),
            ]

            for diagnostic_type, args in commands:
                with self.subTest(diagnostic_type=diagnostic_type):
                    event_before = event_hash_snapshot(ai_dir)
                    runtime_before = runtime_state_snapshot(ai_dir)

                    payload = run_json_cli(*args)

                    self.assertEqual(event_before, event_hash_snapshot(ai_dir))
                    self.assertEqual(runtime_before, runtime_state_snapshot(ai_dir))
                    self.assertEqual([], list(validator.iter_errors(payload)))
                    self.assertEqual(diagnostic_type, payload["diagnostic_type"])
                    self.assertEqual(NOW, payload["as_of"])
                    self.assertIsInstance(payload["project_head"], str)
                    self.assertTrue(payload["project_head"])
                    self.assertEqual(1, payload["summary"]["item_count"])

            stale_assumptions = run_json_cli("show-stale-assumptions", "--ai-dir", str(ai_dir), "--now", NOW)
            self.assertEqual(["AS-001"], [item["object_id"] for item in stale_assumptions["items"]])
            self.assertEqual(["DEC-001"], stale_assumptions["items"][0]["invalidates_if_false"])
            self.assertEqual(["DEC-001"], stale_assumptions["items"][0]["related_object_ids"])

            stale_evidence = run_json_cli("show-stale-evidence", "--ai-dir", str(ai_dir), "--now", NOW)
            self.assertEqual(["EV-001"], [item["object_id"] for item in stale_evidence["items"]])
            self.assertEqual(["valid_until_elapsed"], stale_evidence["items"][0]["stale_reasons"])
            self.assertEqual(["DEC-001"], stale_evidence["items"][0]["affected_decision_ids"])

            verification_gaps = run_json_cli("show-verification-gaps", "--ai-dir", str(ai_dir), "--now", NOW)
            self.assertEqual(["ACT-001"], [item["object_id"] for item in verification_gaps["items"]])
            self.assertEqual("high", verification_gaps["items"][0]["gap_severity"])

            revisit_due = run_json_cli("show-revisit-due", "--ai-dir", str(ai_dir), "--now", NOW)
            self.assertEqual(["RT-001"], [item["object_id"] for item in revisit_due["items"]])
            self.assertEqual(["DEC-001"], revisit_due["items"][0]["target_object_ids"])


def _build_stale_detection_runtime(tmp: Path) -> Path:
    ai_dir = tmp / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Detect stale Phase 7 inputs.",
        current_milestone="Phase 7 readiness",
    )
    session = create_session(str(ai_dir), context="Stale detection diagnostic")
    session_id = session["session"]["id"]
    transact(ai_dir, lambda _bundle: _events(session_id))
    rebuild_and_persist(ai_dir)
    return ai_dir


def _events(session_id: str) -> list[dict]:
    object_specs = [
        (
            "E-stale-assumption",
            "AS-001",
            "assumption",
            "active",
            assumption_metadata(
                statement="The release window remains stable.",
                confidence="medium",
                invalidates_if_false=["DEC-001"],
                expires_at=PAST,
                owner="maintainer",
            ),
        ),
        (
            "E-fresh-assumption",
            "AS-002",
            "assumption",
            "active",
            assumption_metadata(statement="A future assumption remains fresh.", expires_at=FUTURE),
        ),
        (
            "E-stale-evidence",
            "EV-001",
            "evidence",
            "active",
            evidence_metadata(source_ref="docs/stale.md", valid_until=PAST),
        ),
        (
            "E-current-evidence",
            "EV-002",
            "evidence",
            "active",
            evidence_metadata(source_ref="docs/current.md", valid_until=FUTURE),
        ),
        (
            "E-verification",
            "VER-001",
            "verification",
            "active",
            verification_metadata(method="test", result="pass", verified_at=PAST),
        ),
        (
            "E-due-revisit",
            "RT-001",
            "revisit_trigger",
            "active",
            revisit_trigger_metadata(due_at=PAST, target_object_ids=["DEC-001"]),
        ),
        (
            "E-future-revisit",
            "RT-002",
            "revisit_trigger",
            "active",
            revisit_trigger_metadata(due_at=FUTURE, target_object_ids=["DEC-001"]),
        ),
        ("E-decision", "DEC-001", "decision", "unresolved", {"priority": "P0", "frontier": "now"}),
        ("E-gap-action", "ACT-001", "action", "completed", {}),
        ("E-verified-action", "ACT-002", "action", "active", {}),
    ]
    link_specs = [
        ("E-link-assumption-decision", "L-AS-001-constrains-DEC-001", "AS-001", "constrains", "DEC-001"),
        ("E-link-stale-evidence-decision", "L-EV-001-supports-DEC-001", "EV-001", "supports", "DEC-001"),
        ("E-link-current-evidence-action", "L-EV-002-supports-ACT-002", "EV-002", "supports", "ACT-002"),
        ("E-link-verification-action", "L-VER-001-verifies-ACT-002", "VER-001", "verifies", "ACT-002"),
        ("E-link-revisit-decision", "L-RT-001-revisits-DEC-001", "RT-001", "revisits", "DEC-001"),
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
        "body": "Stale detection CLI read-only fixture object.",
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
        "rationale": "Stale detection CLI read-only fixture link.",
        "created_at": "2026-04-28T00:00:00Z",
        "source_event_ids": [event_id],
    }


if __name__ == "__main__":
    unittest.main()
